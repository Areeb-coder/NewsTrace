"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  api,
  Article,
  Coverage,
  DiscoveryJob,
  DiscoveryResults,
  formatDate,
  Journalist,
  safeExternalUrl,
} from "@/lib/api";

type Desk = "front" | "archive" | "coverage" | "journalists";

const NAV: { id: Desk; label: string }[] = [
  { id: "front", label: "Front page" },
  { id: "archive", label: "Archive" },
  { id: "coverage", label: "Coverage desk" },
  { id: "journalists", label: "Bylines" },
];

function todayEdition(date: Date) {
  return new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(date).toUpperCase();
}

function ArticlePhoto({
  article,
  className = "",
  lead = false,
}: {
  article: Article;
  className?: string;
  lead?: boolean;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const image = safeExternalUrl(article.image_url);
  return (
    <div className={"photo-frame " + className}>
      {image && !imageFailed ? (
        <img
          src={image}
          alt={article.title || "Article lead image"}
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <div className="photo-placeholder" aria-label="No publisher image available">
          N
        </div>
      )}
      <span className="photo-caption">
        {image && !imageFailed ? "PUBLISHER IMAGE" : lead ? "NEWS TRACE / NO IMAGE ON SOURCE" : "SOURCE IMAGE UNAVAILABLE"}
      </span>
    </div>
  );
}

function SectionHeading({
  title,
  note,
}: {
  title: string;
  note?: string;
}) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {note ? <span>{note}</span> : null}
    </div>
  );
}

function StoryCard({
  article,
  index,
  onOpen,
}: {
  article: Article;
  index: number;
  onOpen: (article: Article) => void;
}) {
  const reducedMotion = useReducedMotion();
  const hasImage = Boolean(safeExternalUrl(article.image_url));
  const deck =
    article.description ||
    article.summary ||
    "Source-linked article record collected for this investigation. Open the original report for its full text.";

  return (
    <motion.article
      className={"story" + (index === 0 ? " wide" : "")}
      initial={reducedMotion ? false : { opacity: 0, y: 14 }}
      whileInView={reducedMotion ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.12 }}
      transition={{ duration: 0.46, delay: reducedMotion ? 0 : Math.min(index * 0.035, 0.2) }}
    >
      <div className="story-section">{article.section || "GENERAL"}</div>
      <h3 className="story-title">
        <button onClick={() => onOpen(article)}>{article.title || "Untitled report"}</button>
      </h3>
      {hasImage ? (
        <ArticlePhoto article={article} className="story-photo" />
      ) : null}
      <p className="story-deck">{deck}</p>
      <div className="story-meta">
        <span>BY {article.author || "UNKNOWN"}</span>
        <span>{formatDate(article.date)}</span>
        <span>{article.outlet || "SOURCE RECORD"}</span>
      </div>
    </motion.article>
  );
}

function LeadStory({
  article,
  onOpen,
}: {
  article: Article;
  onOpen: (article: Article) => void;
}) {
  const deck =
    article.description ||
    article.summary ||
    "A report gathered from the publication and retained with its original source. Open the original article to read the complete report.";

  return (
    <>
      <SectionHeading title="The lead report" note={"FRONT PAGE / " + (article.section || "GENERAL")} />
      <article className="lead-layout">
        <div className="lead-copy">
          <div className="story-section">{article.section || "GENERAL"}</div>
          <h2 className="lead-headline">{article.title || "Untitled report"}</h2>
          <p className="lead-deck">{deck}</p>
          <div className="byline">
            <span>BY {article.author || "UNKNOWN"}</span>
            <span className="bullet">◆</span>
            <span>{formatDate(article.date)}</span>
            <span className="bullet">◆</span>
            <span>{article.outlet || "NEWS TRACE ARCHIVE"}</span>
          </div>
          <button className="source-link" onClick={() => onOpen(article)}>
            READ THE RECORD <span aria-hidden="true">↗</span>
          </button>
        </div>
        <button
          className="lead-photo photo-frame"
          aria-label={"Open " + article.title}
          onClick={() => onOpen(article)}
          style={{ padding: 0, borderRadius: 0, cursor: "pointer", width: "100%" }}
        >
          {safeExternalUrl(article.image_url) ? (
            <img
              src={safeExternalUrl(article.image_url)}
              alt={article.title || "Article lead image"}
              loading="lazy"
            />
          ) : (
            <div className="photo-placeholder">N</div>
          )}
          <span className="photo-caption">
            {safeExternalUrl(article.image_url) ? "PUBLISHER IMAGE" : "NEWS TRACE / NO IMAGE ON SOURCE"}
          </span>
        </button>
      </article>
    </>
  );
}

function JobTracker({
  job,
  onDismiss,
  onRetry,
  warnings,
}: {
  job: DiscoveryJob;
  onDismiss: () => void;
  onRetry: () => void;
  warnings?: string[];
}) {
  const done = job.status === "complete" || job.status === "partial";
  const failed = job.status === "failed" || job.status === "interrupted";
  const seenStages = Array.from(
    new Set((job.events || []).map((event) => event.stage).filter(Boolean)),
  );
  const currentCount =
    job.total > 0 ? job.current + " / " + job.total : "COUNT NOT REPORTED";

  return (
    <div className="job-panel" aria-live="polite">
      <div className="job-topline">
        <div>
          <div className="job-stage">
            <span className={"status-dot" + (done || failed ? "" : " live")} />
            {job.stage || job.status.toUpperCase()}
          </div>
          <div className="job-detail">{job.detail}</div>
        </div>
        {job.total > 0 ? <div className="job-count">{currentCount}</div> : null}
      </div>
      <div className="job-events" aria-label="Observed investigation stages">
        {seenStages.map((stage, index) => (
          <span
            className={
              "job-event" +
              (stage === job.stage ? " current" : index < seenStages.length - 1 ? " done" : "")
            }
            key={stage + index}
          >
            {stage}
          </span>
        ))}
      </div>
      {failed && job.error ? <p className="job-error">{job.error}</p> : null}
      {(warnings || []).map((warning) => (
        <p className="job-warning" key={warning}>{warning}</p>
      ))}
      {done ? (
        <div className="job-topline" style={{ marginTop: 13 }}>
          <span className="table-meta">
            {job.status === "partial" ? "PARTIAL EDITION / SOME SOURCES UNAVAILABLE" : "EDITION COMPLETE"}
          </span>
          <button className="secondary-button" onClick={onDismiss}>Dismiss</button>
        </div>
      ) : null}
      {failed ? (
        <div className="job-topline" style={{ marginTop: 13 }}>
          <span className="table-meta">THE INVESTIGATION DID NOT COMPLETE</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="action-button" onClick={onRetry}>Retry with saved settings</button>
            <button className="secondary-button" onClick={onDismiss}>Dismiss</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ArticleModal({
  article,
  onClose,
}: {
  article: Article | null;
  onClose: () => void;
}) {
  const reducedMotion = useReducedMotion();
  const href = safeExternalUrl(article?.url);
  return (
    <AnimatePresence>
      {article ? (
        <motion.div
          className="modal-backdrop"
          role="presentation"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reducedMotion ? 0 : 0.18 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.section
            className="article-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="article-modal-title"
            initial={reducedMotion ? false : { opacity: 0, y: 18, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.99 }}
            transition={{ duration: reducedMotion ? 0 : 0.23 }}
          >
            <button className="modal-close" onClick={onClose} aria-label="Close article details">×</button>
            <div className="story-section">{article.section || "GENERAL"}</div>
            <h2 className="modal-title" id="article-modal-title">{article.title || "Untitled report"}</h2>
            <div className="modal-meta">
              <span>BY {article.author || "UNKNOWN"}</span>
              <span>{formatDate(article.date)}</span>
              <span>{article.outlet || "SOURCE NOT REPORTED"}</span>
            </div>
            {safeExternalUrl(article.image_url) ? (
              <ArticlePhoto article={article} className="modal-image" />
            ) : null}
            {article.description || article.summary ? (
              <p className="modal-deck">{article.description || article.summary}</p>
            ) : (
              <p className="modal-deck">
                This record contains the article headline and available publisher metadata. The original report remains the authoritative source for its full text.
              </p>
            )}
            {article.author_bio ? (
              <>
                <SectionHeading title="Byline note" note="PUBLIC AUTHOR INFORMATION" />
                <p className="modal-deck">{article.author_bio}</p>
              </>
            ) : null}
            <div className="byline">
              {article.author_role ? <span>{article.author_role}</span> : null}
              {article.author_email ? <span>{article.author_email}</span> : null}
            </div>
            {href ? (
              <a className="action-button" href={href} target="_blank" rel="noreferrer noopener" style={{ marginTop: 20, textDecoration: "none" }}>
                Open original report ↗
              </a>
            ) : (
              <p className="job-warning">The original article URL was not available in this record.</p>
            )}
          </motion.section>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function DownloadButton({
  label,
  format,
  articles,
}: {
  label: string;
  format: "csv" | "json";
  articles: Article[];
}) {
  function download() {
    const fields = [
      "title", "author", "section", "date", "outlet", "url",
      "author_role", "author_email", "twitter", "linkedin",
    ] as const;
    let data: string;
    let type: string;
    if (format === "json") {
      data = JSON.stringify(articles, null, 2);
      type = "application/json;charset=utf-8";
    } else {
      const quote = (value: unknown) => '"' + String(value ?? "").replace(/"/g, '""') + '"';
      data = [
        fields.join(","),
        ...articles.map((article) => fields.map((field) => quote(article[field])).join(",")),
      ].join("\r\n");
      type = "text/csv;charset=utf-8";
    }
    const url = URL.createObjectURL(new Blob([data], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "newstrace-archive." + format;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  return <button className="secondary-button" onClick={download}>{label}</button>;
}

export default function HomePage() {
  const reducedMotion = useReducedMotion();
  const [editionDate, setEditionDate] = useState("");
  const [editionIssue, setEditionIssue] = useState("");
  const jobInteractionRef = useRef(false);
  const [desk, setDesk] = useState<Desk>("front");
  const [edition, setEdition] = useState<Article[]>([]);
  const [loadingEdition, setLoadingEdition] = useState(true);
  const [editionError, setEditionError] = useState("");
  const [categories, setCategories] = useState<{ name: string; count: number }[]>([]);
  const [sources, setSources] = useState<{ name: string; articles: number }[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [journalists, setJournalists] = useState<Journalist[]>([]);
  const [journalistQuery, setJournalistQuery] = useState("");
  const [archive, setArchive] = useState<Article[]>([]);
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveQuery, setArchiveQuery] = useState("");
  const archiveSearchRef = useRef<HTMLInputElement>(null);
  const [archiveSection, setArchiveSection] = useState("");
  const [archiveSource, setArchiveSource] = useState("");
  const [archiveSort, setArchiveSort] = useState("latest");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [archiveOffset, setArchiveOffset] = useState(0);
  const [showDiscovery, setShowDiscovery] = useState(false);
  const [outlet, setOutlet] = useState("");
  const [maxArticles, setMaxArticles] = useState(150);
  const [enableProfiles, setEnableProfiles] = useState(false);
  const [enableGoogle, setEnableGoogle] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activeJobId, setActiveJobId] = useState("");
  const [activeJob, setActiveJob] = useState<DiscoveryJob | null>(null);
  const [jobWarnings, setJobWarnings] = useState<string[]>([]);
  const [toast, setToast] = useState("");
  const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);

  const latestArticles = useMemo(() => edition.slice(0, 24), [edition]);
  const leadArticle = latestArticles[0];
  const smallStories = latestArticles.slice(1, 4);
  const gridStories = latestArticles.slice(4, 12);

  const refreshEdition = useCallback(async () => {
    try {
      setEditionError("");
      const response = await api<{ articles: Article[]; total: number }>("/api/articles?limit=60&sort=latest");
      setEdition(response.articles || []);
    } catch (error) {
      setEditionError(error instanceof Error ? error.message : "The edition could not be loaded.");
    } finally {
      setLoadingEdition(false);
    }
  }, []);

  const refreshFacets = useCallback(async () => {
    try {
      const [categoryResponse, sourceResponse] = await Promise.all([
        api<{ categories: { name: string; count: number }[] }>("/api/categories"),
        api<{ sources: { name: string; articles: number }[] }>("/api/sources"),
      ]);
      setCategories(categoryResponse.categories || []);
      setSources(sourceResponse.sources || []);
    } catch {
      // The page remains usable when optional archive facets are unavailable.
    }
  }, []);

  useEffect(() => {
    // This is a static Next.js export. Set the date after hydration so the
    // publication date cannot become stale or differ between build and client.
    const now = new Date();
    setEditionDate(todayEdition(now));
    setEditionIssue(String(now.getDate()).padStart(3, "0"));
  }, []);

  useEffect(() => {
    void refreshEdition();
    void refreshFacets();
  }, [refreshEdition, refreshFacets]);

  useEffect(() => {
    let cancelled = false;
    api<{ jobs: DiscoveryJob[] }>("/api/jobs?limit=20")
      .then(({ jobs }) => {
        if (cancelled || jobInteractionRef.current) return;
        const resumable = (jobs || []).find(
          (job) => job.status === "queued" || job.status === "running",
        );
        if (!resumable) return;

        // A job continues on the API process if the visitor refreshes this
        // tab. Reattach to its persisted job ID rather than losing its status.
        jobInteractionRef.current = true;
        setActiveJob(resumable);
        setActiveJobId(resumable.job_id);
        setShowDiscovery(false);
        setToast("Reconnected to the investigation already running on NewsTrace.");
      })
      .catch(() => {
        // The page and archive remain usable when job history is unavailable.
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const handleKeyboard = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isEditing = Boolean(
        target?.closest("input, textarea, select, [contenteditable='true']"),
      );
      if (event.key === "/" && !isEditing) {
        event.preventDefault();
        setDesk("archive");
        window.setTimeout(() => archiveSearchRef.current?.focus(), 0);
      }
      if (event.key === "Escape") {
        if (selectedArticle) setSelectedArticle(null);
        else if (showDiscovery) setShowDiscovery(false);
      }
    };
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, [selectedArticle, showDiscovery]);

  useEffect(() => {
    if (desk === "archive") archiveSearchRef.current?.focus();
  }, [desk]);


  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const job = await api<DiscoveryJob>("/api/discovery/" + activeJobId);
        if (cancelled) return;
        setActiveJob(job);
        if (job.status === "complete" || job.status === "partial") {
          const result = await api<DiscoveryResults>("/api/discovery/" + activeJobId + "/results");
          if (cancelled) return;
          setJobWarnings(result.warnings || []);
          setEdition((current) => {
            const byUrl = new Map<string, Article>();
            [...result.articles, ...current].forEach((article) => {
              const key = article.url || article.title;
              if (key && !byUrl.has(key)) byUrl.set(key, article);
            });
            return Array.from(byUrl.values());
          });
          setToast(result.articles.length + " article records are ready in the edition.");
          setActiveJobId("");
          void refreshFacets();
        } else if (job.status === "failed" || job.status === "interrupted") {
          setActiveJobId("");
        } else {
          timer = window.setTimeout(poll, 1600);
        }
      } catch (error) {
        if (!cancelled) {
          setToast(error instanceof Error ? error.message : "Could not refresh investigation status.");
          timer = window.setTimeout(poll, 2600);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeJobId, refreshFacets]);

  useEffect(() => {
    if (desk !== "archive") return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setArchiveLoading(true);
      const params = new URLSearchParams({
        limit: "24",
        offset: String(archiveOffset),
        q: archiveQuery,
        section: archiveSection,
        source: archiveSource,
        sort: archiveSort,
      });
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      try {
        const response = await api<{ articles: Article[]; total: number }>("/api/articles?" + params.toString());
        if (!cancelled) {
          setArchive(response.articles || []);
          setArchiveTotal(response.total || 0);
        }
      } catch (error) {
        if (!cancelled) setToast(error instanceof Error ? error.message : "Archive search failed.");
      } finally {
        if (!cancelled) setArchiveLoading(false);
      }
    }, 260);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [desk, archiveOffset, archiveQuery, archiveSection, archiveSource, archiveSort, dateFrom, dateTo]);

  useEffect(() => {
    if (desk !== "coverage") return;
    let cancelled = false;
    api<Coverage>("/api/coverage")
      .then((result) => { if (!cancelled) setCoverage(result); })
      .catch((error) => { if (!cancelled) setToast(error.message || "Coverage report unavailable."); });
    return () => { cancelled = true; };
  }, [desk]);

  useEffect(() => {
    if (desk !== "journalists") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api<{ journalists: Journalist[] }>("/api/journalists?limit=100&q=" + encodeURIComponent(journalistQuery))
        .then((result) => { if (!cancelled) setJournalists(result.journalists || []); })
        .catch((error) => { if (!cancelled) setToast(error.message || "Journalist directory unavailable."); });
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [desk, journalistQuery]);

  async function startInvestigation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!outlet.trim() || submitting || activeJobId) return;
    jobInteractionRef.current = true;
    setSubmitting(true);
    setJobWarnings([]);
    try {
      const response = await api<{ job_id: string; status: string }>("/api/discovery/start", {
        method: "POST",
        body: JSON.stringify({
          outlet: outlet.trim(),
          max_articles: maxArticles,
          enable_profiles: enableProfiles,
          enable_google: enableGoogle,
        }),
      });
      setActiveJobId(response.job_id);
      const initial = await api<DiscoveryJob>("/api/discovery/" + response.job_id);
      setActiveJob(initial);
      setShowDiscovery(false);
      setToast("Investigation accepted. Live extraction status is now available.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not start the investigation.");
    } finally {
      setSubmitting(false);
    }
  }

  const currentDesk = NAV.find((item) => item.id === desk)?.label || "Front page";
  const motionTransition = reducedMotion ? { duration: 0 } : { duration: 0.5, ease: [0.2, 0.7, 0.2, 1] as const };

  return (
    <main className="paper-shell">
      <header>
        <div className="issue-line">
          <span>VOL. 01 <strong> / </strong> ISSUE {editionIssue || "---"}</span>
          <span>THE DAILY INTELLIGENCE CHRONICLE</span>
          <span>{editionDate || "TODAY'S EDITION"} <strong> · </strong> INDIA EDITION</span>
        </div>
        <motion.div
          className="masthead"
          initial={reducedMotion ? false : { opacity: 0, y: 17 }}
          animate={{ opacity: 1, y: 0 }}
          transition={motionTransition}
        >
          <div className="masthead-wordmark">NewsTrace</div>
          <div className="masthead-subtitle">The Digital News Chronicle</div>
          <div className="masthead-meta">
            <span>Sources before statements</span>
            <span>Independent record</span>
            <span>Evidence in context</span>
          </div>
        </motion.div>
        <div className="double-rule" />
        <nav className="navigation" aria-label="Newspaper sections">
          {NAV.map((item) => (
            <button
              className={"nav-item" + (desk === item.id ? " active" : "")}
              key={item.id}
              onClick={() => setDesk(item.id)}
              aria-current={desk === item.id ? "page" : undefined}
            >
              {item.label}
            </button>
          ))}
          <button className="nav-item" onClick={() => setShowDiscovery(true)}>New investigation +</button>
        </nav>
      </header>

      <div className="edition-strap">
        <span>{desk === "front" ? "THE FRONT PAGE" : currentDesk.toUpperCase()}</span>
        <span><span className="status-dot" /> SOURCE-LED / {latestArticles.length.toString().padStart(2, "0")} VISIBLE RECORDS</span>
      </div>

      <motion.section
        className="front-intro"
        initial={reducedMotion ? false : { opacity: 0, y: 13 }}
        animate={{ opacity: 1, y: 0 }}
        transition={motionTransition}
      >
        <div>
          <div className="eyebrow">
            {desk === "front" ? "INDEPENDENT REPORTING / INTELLIGENCE / CONTEXT" : "THE NEWSROOM / " + currentDesk.toUpperCase()}
          </div>
          <h1 className="front-title">
            {desk === "front" ? (
              <span>The world, <em>observed</em> closely.</span>
            ) : desk === "archive" ? (
              <span>The record, <em>within reach.</em></span>
            ) : desk === "coverage" ? (
              <span>Follow the <em>coverage.</em></span>
            ) : (
              <span>The people behind <em>the bylines.</em></span>
            )}
          </h1>
          <p className="front-deck">
            NewsTrace turns publication coverage into a searchable record of stories, journalists and the subjects they report on. Each investigation begins with a source, and each result remains connected to its original report.
          </p>
        </div>
        <aside className="edition-stats">
          <strong>{latestArticles.length.toString().padStart(2, "0")}</strong>
          RECORDS IN THIS EDITION
          <br /><br />
          <strong>{new Set(latestArticles.map((item) => item.author).filter((name) => name && name !== "Unknown")).size}</strong>
          IDENTIFIED BYLINES
          <br /><br />
          <span className="table-meta">ISSUED {editionDate || "TODAY'S EDITION"}</span>
        </aside>
      </motion.section>

      <AnimatePresence>
        {showDiscovery ? (
          <motion.section
            className="newsroom-panel"
            initial={{ opacity: 0, height: 0, y: -8 }}
            animate={{ opacity: 1, height: "auto", y: 0 }}
            exit={{ opacity: 0, height: 0, y: -8 }}
            transition={motionTransition}
          >
            <div className="panel-head">
              <h3>Open an investigation</h3>
              <button className="secondary-button" onClick={() => setShowDiscovery(false)}>Close ×</button>
            </div>
            <form onSubmit={startInvestigation}>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="outlet">Publication name or section URL</label>
                  <input
                    id="outlet"
                    value={outlet}
                    onChange={(event) => setOutlet(event.target.value)}
                    placeholder="e.g. Reuters, The Hindu, https://example.com/world"
                    minLength={2}
                    maxLength={240}
                    required
                  />
                </div>
                <button className="action-button" type="submit" disabled={submitting || Boolean(activeJobId)}>
                  {submitting ? "Opening the file…" : activeJobId ? "Investigation in progress" : "Begin discovery →"}
                </button>
              </div>
              <div className="form-options">
                <div className="field" style={{ maxWidth: 165 }}>
                  <label htmlFor="maxArticles">Article limit</label>
                  <select id="maxArticles" value={maxArticles} onChange={(event) => setMaxArticles(Number(event.target.value))}>
                    <option value={50}>50 records</option>
                    <option value={100}>100 records</option>
                    <option value={150}>150 records</option>
                    <option value={300}>300 records</option>
                    <option value={500}>500 records</option>
                  </select>
                </div>
                <label className="check-label">
                  <input type="checkbox" checked={enableProfiles} onChange={(event) => setEnableProfiles(event.target.checked)} />
                  Public author profile enrichment
                </label>
                <label className="check-label">
                  <input type="checkbox" checked={enableGoogle} onChange={(event) => setEnableGoogle(event.target.checked)} />
                  Search enrichment (SerpAPI)
                </label>
              </div>
              <p className="table-meta" style={{ marginTop: 11 }}>
                DISCOVERY RUNS IN THE BACKGROUND. STATUS AND ARTICLE COUNTS ARE REPORTED BY THE SERVER.
              </p>
            </form>
          </motion.section>
        ) : null}
      </AnimatePresence>

      {activeJob ? (
        <JobTracker
          job={activeJob}
          warnings={jobWarnings}
          onRetry={() => {
            const parameters = activeJob.parameters || {};
            setOutlet(String(parameters.outlet || activeJob.outlet || ""));
            setMaxArticles(Number(parameters.max_articles || 150));
            setEnableProfiles(Boolean(parameters.enable_profiles));
            setEnableGoogle(Boolean(parameters.enable_google));
            setActiveJob(null);
            setActiveJobId("");
            setJobWarnings([]);
            setShowDiscovery(true);
          }}
          onDismiss={() => { setActiveJob(null); setActiveJobId(""); setJobWarnings([]); }}
        />
      ) : null}

      {desk === "front" ? (
        <>
          {loadingEdition ? (
            <section>
              <SectionHeading title="The edition" note="FETCHING ARCHIVE RECORDS" />
              <div className="loading-line" /><div className="loading-line" /><div className="loading-line" />
            </section>
          ) : editionError ? (
            <div className="empty-state">
              <h3>The edition could not be opened.</h3>
              <p>{editionError}</p>
              <button className="secondary-button" onClick={() => { setLoadingEdition(true); void refreshEdition(); }}>Retry archive connection</button>
            </div>
          ) : !leadArticle ? (
            <div className="empty-state" style={{ marginTop: 22 }}>
              <h3>Every story leaves a trail.</h3>
              <p>Begin with a publication or a section URL. NewsTrace will discover articles, extract available bylines and keep each record linked to its source.</p>
              <button className="action-button" style={{ marginTop: 14 }} onClick={() => setShowDiscovery(true)}>Open the newsroom desk →</button>
            </div>
          ) : (
            <>
              <LeadStory article={leadArticle} onOpen={setSelectedArticle} />
              <SectionHeading title="Across the pages" note={edition.length + " SOURCE-LINKED RECORDS"} />
              {smallStories.length ? (
                <div className="paper-grid">
                  {smallStories.map((article, index) => (
                    <StoryCard article={article} index={index} key={article.url || article.title} onOpen={setSelectedArticle} />
                  ))}
                </div>
              ) : null}
              {gridStories.length ? (
                <>
                  <SectionHeading title="More from the edition" note="REPORTS / BYLINES / SECTIONS" />
                  <div className="paper-grid">
                    {gridStories.map((article, index) => (
                      <StoryCard article={article} index={index} key={article.url || article.title} onOpen={setSelectedArticle} />
                    ))}
                  </div>
                </>
              ) : null}
            </>
          )}
          <div className="newsroom-panel">
            <div className="panel-head">
              <h3>Investigate a publication</h3>
              <span>THE NEWSROOM DESK</span>
            </div>
            <p className="lead-deck" style={{ marginTop: 0 }}>
              Enter a publication or a direct section URL. The API will return a job reference immediately, then report discovery and extraction as each stage actually progresses.
            </p>
            <button className="action-button" onClick={() => setShowDiscovery(true)}>Start a new investigation →</button>
          </div>
        </>
      ) : null}

      {desk === "archive" ? (
        <section>
          <SectionHeading title="Search the archive" note="HEADLINES / BYLINES / SOURCES / DATES" />
          <div className="toolbar">
            <div className="field">
              <label htmlFor="archive-query">Search the record</label>
              <input ref={archiveSearchRef} id="archive-query" value={archiveQuery} onChange={(event) => { setArchiveQuery(event.target.value); setArchiveOffset(0); }} placeholder="Search headline, journalist, publication…" />
            </div>
            <div className="field small">
              <label htmlFor="archive-section">Section</label>
              <select id="archive-section" value={archiveSection} onChange={(event) => { setArchiveSection(event.target.value); setArchiveOffset(0); }}>
                <option value="">All sections</option>
                {categories.map((category) => <option value={category.name} key={category.name}>{category.name}</option>)}
              </select>
            </div>
            <div className="field small">
              <label htmlFor="archive-source">Publication</label>
              <select id="archive-source" value={archiveSource} onChange={(event) => { setArchiveSource(event.target.value); setArchiveOffset(0); }}>
                <option value="">All publications</option>
                {sources.map((source) => <option value={source.name} key={source.name}>{source.name}</option>)}
              </select>
            </div>
            <div className="field small">
              <label htmlFor="archive-sort">Order</label>
              <select id="archive-sort" value={archiveSort} onChange={(event) => setArchiveSort(event.target.value)}>
                <option value="latest">Latest date</option>
                <option value="oldest">Oldest date</option>
                <option value="author">Byline</option>
                <option value="title">Headline</option>
              </select>
            </div>
            <div className="field small">
              <label htmlFor="date-from">From date</label>
              <input id="date-from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </div>
            <div className="field small">
              <label htmlFor="date-to">To date</label>
              <input id="date-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </div>
            <div className="record-count">{archiveTotal.toLocaleString()} RECORDS</div>
          </div>
          <div className="pagination">
            <span>CSV / JSON EXPORT OF THE CURRENT RESULTS</span>
            <div style={{ display: "flex", gap: 8 }}>
              <DownloadButton label="CSV ↓" format="csv" articles={archive} />
              <DownloadButton label="JSON ↓" format="json" articles={archive} />
            </div>
          </div>
          {archiveLoading ? (
            <div style={{ padding: "20px 0" }}><div className="loading-line" /><div className="loading-line" /><div className="loading-line" /></div>
          ) : archive.length ? (
            <>
              <div className="article-table-wrap">
                <table className="article-table">
                  <thead><tr><th>Headline / Publication</th><th>Byline</th><th>Section</th><th>Date</th><th>Source</th></tr></thead>
                  <tbody>
                    {archive.map((article) => (
                      <tr key={(article.job_id || "") + (article.url || article.title)}>
                        <td>
                          <button className="table-title" onClick={() => setSelectedArticle(article)}>{article.title}</button>
                          <div className="table-meta">{article.outlet || "SOURCE NOT REPORTED"}</div>
                        </td>
                        <td className="table-meta">{article.author || "UNKNOWN"}</td>
                        <td><span className="tag">{article.section || "GENERAL"}</span></td>
                        <td className="table-meta">{formatDate(article.date)}</td>
                        <td>
                          {safeExternalUrl(article.url) ? <a className="source-link" style={{ marginTop: 0 }} href={safeExternalUrl(article.url)} target="_blank" rel="noreferrer noopener">OPEN ↗</a> : <span className="table-meta">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <button className="secondary-button" disabled={archiveOffset === 0} onClick={() => setArchiveOffset(Math.max(0, archiveOffset - 24))}>← Previous</button>
                <span>SHOWING {archiveOffset + 1}–{Math.min(archiveOffset + archive.length, archiveTotal)} OF {archiveTotal}</span>
                <button className="secondary-button" disabled={archiveOffset + 24 >= archiveTotal} onClick={() => setArchiveOffset(archiveOffset + 24)}>Next →</button>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <h3>No matching records.</h3>
              <p>Try a broader headline search, another section or a different publication filter. New records appear here after an investigation completes.</p>
            </div>
          )}
        </section>
      ) : null}

      {desk === "coverage" ? (
        <section>
          <SectionHeading title="Coverage intelligence" note="THE PATTERNS BEHIND THE REPORTING" />
          {coverage ? (
            <>
              <div className="metric-grid">
                <div className="metric"><div className="metric-label">Article records</div><div className="metric-value">{coverage.total_articles.toLocaleString()}</div></div>
                <div className="metric"><div className="metric-label">Identified journalists</div><div className="metric-value">{coverage.identified_journalists.toLocaleString()}</div></div>
                <div className="metric"><div className="metric-label">Sections covered</div><div className="metric-value">{coverage.sections.length.toLocaleString()}</div></div>
                <div className="metric"><div className="metric-label">Publications</div><div className="metric-value">{coverage.sources.length.toLocaleString()}</div></div>
              </div>
              <div className="coverage-grid">
                <div>
                  <SectionHeading title="Most active bylines" note="ARTICLE COUNT" />
                  <div className="coverage-list">
                    {coverage.top_journalists.map((item) => (
                      <div className="coverage-row" key={item.name}><span>{item.name}</span><strong>{item.count}</strong></div>
                    ))}
                  </div>
                </div>
                <div>
                  <SectionHeading title="Sections in the archive" note="ARTICLE COUNT" />
                  <div className="coverage-list">
                    {coverage.sections.map((item) => (
                      <div className="coverage-row" key={item.name}><span>{item.name}</span><strong>{item.count}</strong></div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="empty-state"><h3>Coverage intelligence is being assembled.</h3><p>The desk will show journalist and section patterns from completed investigations.</p></div>
          )}
        </section>
      ) : null}

      {desk === "journalists" ? (
        <section>
          <SectionHeading title="The byline directory" note="PEOPLE BEHIND THE REPORTS" />
          <div className="toolbar">
            <div className="field">
              <label htmlFor="journalist-search">Find a journalist</label>
              <input id="journalist-search" value={journalistQuery} onChange={(event) => setJournalistQuery(event.target.value)} placeholder="Search a name…" />
            </div>
            <span className="record-count">{journalists.length} VISIBLE BYLINES</span>
          </div>
          {journalists.length ? (
            <div className="journalist-grid">
              {journalists.map((person) => (
                <article className="journalist" key={person.name}>
                  <div className="story-section">BYLINE / {person.article_count} REPORTS</div>
                  <h3 className="journalist-name">{person.name}</h3>
                  <div className="journalist-detail">{person.role || person.sections.join(" · ") || "COVERAGE NOT CLASSIFIED"}</div>
                  {person.bio ? <p className="journalist-bio">{person.bio}</p> : null}
                  {person.latest_article ? <p className="journalist-bio">Latest: {person.latest_article.title}</p> : null}
                  <div className="journalist-links">
                    {person.email ? <a href={"mailto:" + person.email}>Email</a> : null}
                    {safeExternalUrl(person.linkedin) ? <a href={safeExternalUrl(person.linkedin)} target="_blank" rel="noreferrer noopener">LinkedIn ↗</a> : null}
                    {safeExternalUrl(person.twitter) ? <a href={safeExternalUrl(person.twitter)} target="_blank" rel="noreferrer noopener">Twitter / X ↗</a> : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state"><h3>No identified bylines yet.</h3><p>Author records will appear after article pages expose usable bylines. Unknown or unverified names are not included in this directory.</p></div>
          )}
        </section>
      ) : null}

      <footer className="site-footer">
        <span>NEWSTRACE / THE DIGITAL NEWS CHRONICLE</span>
        <span>RESEARCH WITH CONTEXT / DATA WITH PROVENANCE</span>
        <span>INDIA EDITION / {editionDate || "TODAY'S EDITION"}</span>
      </footer>

      <ArticleModal article={selectedArticle} onClose={() => setSelectedArticle(null)} />
      <AnimatePresence>
        {toast ? (
          <motion.div
            className="toast"
            role="status"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
          >
            {toast}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </main>
  );
}
