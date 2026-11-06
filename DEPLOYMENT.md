# Deploying NewsTrace

NewsTrace is a **Streamlit + Playwright** application. It runs a long-lived
Streamlit server and launches Chromium for web scraping. It is not a static
website.

## Recommended: Render (Docker)

The repository includes a `Dockerfile` and `render.yaml`.

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint** and connect
   `Areeb-coder/NewsTrace`.
3. Render reads `render.yaml`, builds the Docker image, and deploys the
   Streamlit service.
4. When the deployment is ready, open the generated `.onrender.com` URL.

The Docker image installs the Playwright browser binaries and operating
system dependencies. The Playwright image version is pinned to match the
Python package version in `requirements.txt`.

### Optional environment variables

Configure these in Render's **Environment** settings. Do not commit them
to GitHub.

| Variable | Required? | Purpose |
|---|---|---|
| `SUPABASE_URL` | No | Enables Supabase persistence |
| `SUPABASE_KEY` | No | Supabase anon/public key used with your database RLS policies |
| `SERP_API_KEY` | No | Enables optional Google/SerpAPI enrichment |

The dashboard can run without these values. Supabase persistence and Google
enrichment are optional features.

## Run locally

Use Python 3.12, then run:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

python -m pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

Open `http://localhost:8501`.

## Why not Vercel or GitHub Pages?

GitHub stores the source code; it does not run this Streamlit server.
GitHub Pages and Vercel's normal static/frontend deployment model are not
a drop-in host for a persistent Streamlit process with Playwright/Chromium.
Use a Docker-capable application host such as Render for this repository.

## Troubleshooting

- **Chromium executable missing:** verify the service was built from the
  repository's Dockerfile. Do not deploy this app as a static site.
- **Missing Python module:** redeploy after confirming the dependency exists
  in `requirements.txt`; the HTML parser `lxml` is explicitly included.
- **Supabase connection message:** this is optional. Add valid Supabase
  environment variables only when database persistence is needed.
- **Slow or memory-heavy scraping:** reduce the dashboard's Max Articles
  setting and enable optional enrichment only when needed.


## Scraping progress and troubleshooting

The investigation panel reports each phase separately:

1. API endpoint discovery (with bounded request timeouts).
2. HTML discovery (maximum 18 pages per investigation).
3. Article extraction (six reusable Playwright pages sharing one Chromium process).
4. Optional author-profile and search enrichment.

A page that times out or is blocked is counted as a failed page/article and skipped; it should not leave the interface on a single indefinite spinner. The progress bar shows the latest stage, processed count and failure count.

If discovery finishes with no URLs, try a direct section URL rather than only the publication homepage. If URLs are found but no articles are parsed, the publication may block automated browsers, require authenticated cookies, or use a page structure that needs a source-specific extractor. The UI now shows this distinction rather than silently returning an empty result.

For production, deploy the repository's Dockerfile so Chromium and its required system libraries are present. A successful Streamlit health check confirms the server starts; it does not guarantee every publisher permits automated scraping.
