"""NewsTrace FastAPI application.

The API owns the discovery job lifecycle and serves the exported Next.js app
from the same origin in production. The original Streamlit entry points remain
available during the migration.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.investigation import run_investigation
from backend.jobs import store
from backend.source_resolver import resolve_outlet
from utils.article_collector import normalize_url


logger = logging.getLogger("newstrace.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_OUT = ROOT / "frontend" / "out"
MAX_ACTIVE_JOBS = max(1, min(int(os.getenv("NEWSTRACE_MAX_ACTIVE_JOBS", "2")), 4))
DISCOVERY_START_LIMIT = max(1, int(os.getenv("NEWSTRACE_DISCOVERY_RATE_LIMIT", "5")))
DISCOVERY_START_WINDOW = max(60, int(os.getenv("NEWSTRACE_DISCOVERY_RATE_WINDOW", "600")))
_start_attempts: dict[str, deque[float]] = defaultdict(deque)


def _validate_public_http_url(value: str) -> str:
    """Reject obvious local/private targets and malformed URL credentials."""
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a valid public http:// or https:// publication URL.")
    if parsed.username or parsed.password:
        raise ValueError("Publication URLs must not contain embedded usernames or passwords.")

    hostname = parsed.hostname.rstrip(".").lower()
    if (
        hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal", ".test"))
    ):
        raise ValueError("Local and internal network addresses cannot be used as publication sources.")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private, loopback and link-local IP addresses cannot be used as publication sources.")

    if parsed.port not in (None, 80, 443):
        raise ValueError("Publication URLs may use only the standard HTTP or HTTPS ports.")
    return value


def _check_discovery_rate_limit(client_key: str) -> None:
    now = time.monotonic()
    attempts = _start_attempts[client_key]
    cutoff = now - DISCOVERY_START_WINDOW
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if len(attempts) >= DISCOVERY_START_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many investigations were started from this connection. Please wait before starting another one.",
            headers={"Retry-After": str(DISCOVERY_START_WINDOW)},
        )
    attempts.append(now)


class DiscoveryRequest(BaseModel):
    outlet: str = Field(min_length=2, max_length=240)
    max_articles: int = Field(default=150, ge=10, le=500)
    enable_profiles: bool = False
    enable_google: bool = False


def _serialize_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    # pandas' JSON encoder converts NaN/NaT into JSON null and keeps dates safe.
    payload = frame.to_json(orient="records", date_format="iso", force_ascii=False)
    return json.loads(payload)


def _discover_from_input(raw_input: str, resolved_url: str) -> str:
    value = raw_input.strip()
    candidate = value if value.startswith(("http://", "https://")) else f"https://{value}"
    parsed = urlparse(candidate)
    if (
        parsed.netloc
        and "." in (parsed.hostname or "")
        and not any(character.isspace() for character in value)
    ):
        return normalize_url(candidate) or resolved_url
    return resolved_url


async def _run_job(job_id: str, request: DiscoveryRequest, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        try:
            store.update_progress(
                job_id, "Source resolution", 0, 1,
                "Resolving the publication and preparing the investigation.",
            )
            raw_input = request.outlet.strip()
            resolved_url, outlet_label = await asyncio.to_thread(resolve_outlet, raw_input)
            if not resolved_url:
                raise ValueError(
                    "NewsTrace could not identify that publication. Enter its full website URL, including https://, or check the publication name."
                )

            _validate_public_http_url(resolved_url)
            discovery_url = _validate_public_http_url(_discover_from_input(raw_input, resolved_url))
            outlet_label = outlet_label or urlparse(resolved_url).netloc
            store.set_source(job_id, resolved_url, outlet_label)
            store.update_progress(
                job_id, "Source resolved", 1, 1,
                f"Publication identified: {outlet_label}. Article discovery is starting.",
            )

            loop = asyncio.get_running_loop()

            def on_progress(stage: str, current: int, total: int, detail: str) -> None:
                # The API-first HTTP probe can call this from a worker thread.
                # Serialize all job-store writes through the event loop.
                if loop.is_closed():
                    return
                loop.call_soon_threadsafe(
                    store.update_progress, job_id, stage, current, total, detail
                )

            frame, stats, warnings = await run_investigation(
                resolved_url,
                outlet_label,
                request.max_articles,
                request.enable_profiles,
                request.enable_google,
                discovery_url=discovery_url,
                progress_callback=on_progress,
            )
            articles = _serialize_frame(frame)
            if not articles:
                raise RuntimeError(
                    "Discovery finished without any usable article records. Try a direct section URL or a smaller article limit."
                )

            warnings = list(warnings or [])
            # Supabase remains optional. Its failures should not discard the local
            # investigation results or leave a job spinning.
            if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"):
                try:
                    from utils.supabase_backend import save_articles, save_journalist_profiles

                    article_save, profile_save = await asyncio.gather(
                        asyncio.to_thread(save_articles, frame, outlet_label),
                        asyncio.to_thread(save_journalist_profiles, frame, outlet_label),
                    )
                    if not article_save.get("success"):
                        warnings.append("The investigation completed, but article records were not confirmed in Supabase.")
                    if not profile_save.get("success"):
                        warnings.append("The investigation completed, but journalist profiles were not confirmed in Supabase.")
                    stats["supabase_articles_saved"] = article_save.get("count", 0)
                    stats["supabase_profiles_saved"] = profile_save.get("count", 0)
                except Exception as exc:
                    logger.exception("Supabase persistence failed for job %s", job_id)
                    warnings.append("The investigation completed, but optional Supabase persistence failed.")

            failed = int(stats.get("article_failures", 0) or 0)
            store.complete_job(
                job_id,
                articles,
                stats,
                warnings,
                partial=failed > 0,
            )
        except asyncio.CancelledError:
            store.fail_job(
                job_id,
                "The API process is shutting down. This investigation was interrupted; start it again after the service is available.",
                status="interrupted",
            )
            raise
        except Exception as exc:
            logger.exception("NewsTrace job %s failed", job_id)
            public_error = str(exc).strip() or "An unexpected error interrupted the investigation."
            store.fail_job(job_id, public_error[:900])


@asynccontextmanager
async def lifespan(app: FastAPI):
    recovered = store.recover_interrupted_jobs()
    if recovered:
        logger.warning("Marked %s jobs as interrupted after a process restart.", recovered)
    app.state.tasks = {}
    app.state.job_semaphore = asyncio.Semaphore(MAX_ACTIVE_JOBS)
    yield
    tasks = list(app.state.tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="NewsTrace API",
    description="Source-led news discovery, journalist intelligence and newspaper archive API.",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "newstrace-api",
        "time": datetime.now(timezone.utc).isoformat(),
        "active_jobs": sum(
            1 for task in getattr(app.state, "tasks", {}).values() if not task.done()
        ),
    }


@app.post("/api/discovery/start", status_code=status.HTTP_202_ACCEPTED)
async def start_discovery(payload: DiscoveryRequest, request: Request) -> dict[str, Any]:
    client_key = request.client.host if request.client else "unknown"
    _check_discovery_rate_limit(client_key)

    raw_outlet = payload.outlet.strip()
    candidate = raw_outlet if raw_outlet.startswith(("http://", "https://")) else f"https://{raw_outlet}"
    candidate_parts = urlparse(candidate)
    if candidate_parts.netloc and "." in (candidate_parts.hostname or ""):
        _validate_public_http_url(candidate)

    parameters = payload.model_dump()
    job = store.create_job(raw_outlet, parameters)
    task = asyncio.create_task(
        _run_job(job["job_id"], payload, app.state.job_semaphore),
        name=f"newstrace-discovery-{job['job_id']}",
    )
    app.state.tasks[job["job_id"]] = task
    task.add_done_callback(lambda _task, job_id=job["job_id"]: app.state.tasks.pop(job_id, None))
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "status_url": f"/api/discovery/{job['job_id']}",
        "results_url": f"/api/discovery/{job['job_id']}/results",
    }


@app.get("/api/discovery/{job_id}")
async def discovery_status(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return job


@app.get("/api/discovery/{job_id}/results")
async def discovery_results(
    job_id: str,
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    result = store.get_results(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    if result["status"] not in {"complete", "partial"}:
        raise HTTPException(
            status_code=409,
            detail=f"Investigation results are not ready. Current status: {result['status']}.",
        )
    articles = result.pop("articles", [])
    result["total"] = len(articles)
    result["articles"] = articles[offset:offset + limit]
    result["offset"] = offset
    result["limit"] = limit
    return result


@app.get("/api/jobs")
async def recent_jobs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    jobs = store.list_jobs(limit)
    return {"jobs": jobs, "count": len(jobs)}


def _all_articles() -> list[dict[str, Any]]:
    return store.all_articles(limit_jobs=40)


@app.get("/api/articles")
@app.get("/api/search")
async def articles(
    q: str = Query(default="", max_length=200),
    section: str = Query(default="", max_length=100),
    source: str = Query(default="", max_length=200),
    date_from: str = Query(default="", max_length=30),
    date_to: str = Query(default="", max_length=30),
    sort: str = Query(default="latest", pattern="^(latest|oldest|author|title)$"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    records = _all_articles()
    needle = q.strip().casefold()
    selected_section = section.strip().casefold()
    selected_source = source.strip().casefold()

    filtered: list[dict[str, Any]] = []
    for item in records:
        if selected_section and str(item.get("section") or "").casefold() != selected_section:
            continue
        if selected_source and str(item.get("outlet") or "").casefold() != selected_source:
            continue
        if needle:
            searchable = " ".join(
                str(item.get(key) or "")
                for key in ("title", "author", "section", "url", "outlet", "date")
            ).casefold()
            if needle not in searchable:
                continue
        published = str(item.get("date") or "")[:10]
        if date_from and published and published < date_from:
            continue
        if date_to and published and published > date_to:
            continue
        filtered.append(item)

    if sort == "oldest":
        filtered.sort(key=lambda item: str(item.get("date") or ""))
    elif sort == "author":
        filtered.sort(key=lambda item: str(item.get("author") or "").casefold())
    elif sort == "title":
        filtered.sort(key=lambda item: str(item.get("title") or "").casefold())
    else:
        filtered.sort(key=lambda item: str(item.get("date") or ""), reverse=True)

    total = len(filtered)
    return {
        "articles": filtered[offset:offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/categories")
async def categories() -> dict[str, Any]:
    sections: dict[str, int] = {}
    for item in _all_articles():
        section = str(item.get("section") or "Unclassified").strip() or "Unclassified"
        sections[section] = sections.get(section, 0) + 1
    ordered = sorted(sections.items(), key=lambda entry: (-entry[1], entry[0].casefold()))
    return {"categories": [{"name": name, "count": count} for name, count in ordered[:100]]}


@app.get("/api/sources")
async def sources() -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    for item in _all_articles():
        outlet = str(item.get("outlet") or "Unknown source")
        source_counts[outlet] = source_counts.get(outlet, 0) + 1
    ordered = sorted(source_counts.items(), key=lambda entry: (-entry[1], entry[0].casefold()))
    return {"sources": [{"name": name, "articles": count} for name, count in ordered[:100]]}


@app.get("/api/journalists")
async def journalists(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for article in _all_articles():
        author = str(article.get("author") or "Unknown").strip()
        if not author or author.casefold() == "unknown":
            continue
        record = grouped.setdefault(author, {
            "name": author,
            "article_count": 0,
            "sections": set(),
            "sources": set(),
            "latest_article": None,
            "email": article.get("author_email"),
            "role": article.get("author_role"),
            "linkedin": article.get("linkedin") or article.get("linkedin_url"),
            "twitter": article.get("twitter") or article.get("twitter_url"),
            "bio": article.get("author_bio"),
        })
        record["article_count"] += 1
        if article.get("section"):
            record["sections"].add(str(article["section"]))
        if article.get("outlet"):
            record["sources"].add(str(article["outlet"]))
        if not record["latest_article"] or str(article.get("date") or "") > str(record["latest_article"].get("date") or ""):
            record["latest_article"] = {
                "title": article.get("title"),
                "date": article.get("date"),
                "url": article.get("url"),
            }
        for key, candidate in (
            ("email", article.get("author_email")),
            ("role", article.get("author_role")),
            ("linkedin", article.get("linkedin") or article.get("linkedin_url")),
            ("twitter", article.get("twitter") or article.get("twitter_url")),
            ("bio", article.get("author_bio")),
        ):
            if not record[key] and candidate:
                record[key] = candidate

    query = q.strip().casefold()
    result = []
    for record in grouped.values():
        if query and query not in record["name"].casefold():
            continue
        record["sections"] = sorted(record["sections"])
        record["sources"] = sorted(record["sources"])
        result.append(record)
    result.sort(key=lambda record: (-record["article_count"], record["name"].casefold()))
    return {
        "journalists": result[offset:offset + limit],
        "total": len(result),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/coverage")
async def coverage() -> dict[str, Any]:
    records = _all_articles()
    author_counts: dict[str, int] = {}
    section_counts: dict[str, int] = {}
    outlet_counts: dict[str, int] = {}
    for item in records:
        author = str(item.get("author") or "Unknown")
        if author.casefold() != "unknown":
            author_counts[author] = author_counts.get(author, 0) + 1
        section = str(item.get("section") or "Unclassified")
        section_counts[section] = section_counts.get(section, 0) + 1
        outlet = str(item.get("outlet") or "Unknown source")
        outlet_counts[outlet] = outlet_counts.get(outlet, 0) + 1
    return {
        "total_articles": len(records),
        "identified_journalists": len(author_counts),
        "sections": [
            {"name": name, "count": count}
            for name, count in sorted(section_counts.items(), key=lambda entry: -entry[1])
        ],
        "top_journalists": [
            {"name": name, "count": count}
            for name, count in sorted(author_counts.items(), key=lambda entry: -entry[1])[:15]
        ],
        "sources": [
            {"name": name, "count": count}
            for name, count in sorted(outlet_counts.items(), key=lambda entry: -entry[1])
        ],
    }


@app.get("/")
async def frontend_root():
    index = FRONTEND_OUT / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={
            "service": "newstrace-api",
            "message": "The API is running, but the Next.js frontend has not been built. Run the frontend build or use the web Dockerfile.",
            "health": "/api/health",
        },
    )


@app.get("/{file_path:path}", include_in_schema=False)
async def frontend_files(file_path: str):
    # Keep API and framework routes above this catch-all. Serve generated files
    # only from the trusted export directory, and use index.html for client routes.
    if file_path.startswith(("api/", "docs", "redoc", "openapi.json")):
        raise HTTPException(status_code=404, detail="Not found.")

    if FRONTEND_OUT.is_dir():
        candidate = (FRONTEND_OUT / file_path).resolve()
        if candidate == FRONTEND_OUT.resolve() or FRONTEND_OUT.resolve() in candidate.parents:
            if candidate.is_file():
                return FileResponse(candidate)
            if candidate.is_dir() and (candidate / "index.html").is_file():
                return FileResponse(candidate / "index.html")
        index = FRONTEND_OUT / "index.html"
        if index.is_file():
            return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend asset not found.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENVIRONMENT") == "development",
    )
