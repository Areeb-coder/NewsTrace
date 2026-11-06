# 🔍 NewsTrace

### Journalist Intelligence & News Coverage Analysis Platform

NewsTrace is a source-led news-intelligence platform for discovering articles, identifying journalists, analyzing coverage patterns, and building a searchable archive of reporting.

The application now has a **Next.js + React + TypeScript frontend** served by a **FastAPI backend**, while preserving its existing Python discovery, Playwright extraction, author analysis, optional SerpAPI enrichment, and Supabase integrations. The original Streamlit interface remains available during the migration.

---

## 🏆 Hackathon Recognition

**Runner-Up — Hack of Thrones Hackathon**  
Organized by **Google Developer Group (GDG) JMI**

NewsTrace was developed and presented as the project that secured the **Runner-Up** position at the Hack of Thrones hackathon organized by GDG JMI.

---

## ✨ Features

### 📰 Intelligent News Discovery
- Accepts a news outlet name or website URL
- Automatically resolves the official website
- Discovers relevant article pages
- Extracts article metadata automatically
- Supports large-scale article collection

### 👤 Journalist Intelligence
Extract detailed information about journalists, including:

- Author name
- Role / designation
- Workplace
- Biography
- Email, when publicly available
- Social media profiles
- Article history
- Sections and topics covered

### 🌐 Google Enrichment
Optional enrichment can retrieve additional publicly available information about authors, including:

- Social media profiles
- Professional information
- Biographical information
- Additional contact information when publicly available

Google enrichment can be enabled or disabled from the dashboard.

### ⚡ Parallel Web Scraping
NewsTrace uses parallel scraping to process multiple articles efficiently rather than handling every page sequentially.

This significantly improves performance when analyzing larger news outlets.

### 📊 Interactive Journalist Dashboard
The dashboard provides an interactive view of extracted intelligence, including:

- Complete journalist data table
- Article information
- Social profiles
- Author statistics
- Coverage sections
- Journalist-topic relationships
- Enriched profile information

### 🕸️ Author–Topic Network
NewsTrace visualizes relationships between journalists and the topics or sections they cover.

This makes it possible to identify patterns such as:

- Which journalists cover specific topics
- Which topics dominate an outlet
- How journalists are distributed across sections
- Author specialization patterns
- Relationships between authors and coverage areas

### 📤 Data Export
Collected intelligence can be exported for further analysis.

Supported formats include:

- CSV
- JSON

---

# 🏗️ Architecture

The new web application separates the editorial frontend from the Python investigation engine:

~~~text
                 Next.js / React / TypeScript
                           |
                  HTTP same-origin API
                           |
                           v
                       FastAPI
                           |
                  SQLite discovery jobs
                           |
        +------------------+------------------+
        v                  v                  v
  Article discovery   Playwright extract   Enrichment
        |                  |                  |
        +------------------+------------------+
                           |
                   Article records
                           |
                Search / Archive / Coverage
                           |
                 Optional Supabase storage
~~~

The Streamlit dashboard and its original entry points are retained as a legacy interface while the new application is verified. See [MIGRATION.md](MIGRATION.md) for the repository audit, job lifecycle, persistence boundaries and setup details.

---
# 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| **Next.js / React / TypeScript** | New editorial web frontend |
| **Tailwind CSS v4** | Frontend styling system |
| **Motion for React** | Restrained UI transitions |
| **FastAPI / Uvicorn** | HTTP API and discovery-job lifecycle |
| **Python** | Existing article discovery and enrichment logic |
| **Playwright / Chromium** | Browser-based source and article extraction |
| **BeautifulSoup / lxml** | HTML parsing |
| **Pandas** | Article and journalist data processing |
| **SQLite** | Local job-status and result snapshots |
| **Supabase** | Optional persistent article and journalist storage |
| **SerpAPI** | Optional public-profile enrichment |

---
# 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/Areeb-coder/NewsTrace.git
cd NewsTrace
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it on Windows:

```powershell
venv\Scripts\activate
```

On macOS/Linux:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright

```bash
playwright install chromium
```

---

# ⚙️ Configuration

Create a `.env` file in the project root.

Example:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
SERP_API_KEY=your_serpapi_key
```

`SERP_API_KEY` is optional and is only required when Google enrichment is enabled.

**Never commit your `.env` file or expose API keys publicly.**

---

# ▶️ Running NewsTrace

## New Next.js + FastAPI application

Install the Python dependencies and browser runtime from the repository root:

~~~bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
python -m pip install -r requirements.txt
playwright install chromium
~~~

Start the API:

~~~bash
uvicorn backend.main:app --reload --port 8000
~~~

In a second terminal, start the frontend:

~~~bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
~~~

Open **http://localhost:3000**. The API is available at **http://localhost:8000** and the health endpoint is **/api/health**.

For PowerShell, set the local API base URL before starting Next.js:

~~~powershell
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
npm run dev
~~~

## Legacy Streamlit application

The original application remains available during the migration:

~~~bash
streamlit run app.py
~~~

It continues to use the original Streamlit UI and Playwright scraping stack. The new web service does not replace it automatically.

---
# 🔎 How It Works

### 1. Enter a News Outlet

Enter either:

```text
CNN
```

or a complete website URL:

```text
https://www.example.com
```

NewsTrace resolves the outlet and begins discovering article pages.

### 2. Discover Articles

The scraper identifies article URLs and collects relevant metadata.

### 3. Extract Journalists

NewsTrace analyzes article pages to identify authors and extract information such as:

```text
Author
Title
Section
Publication Date
Article URL
```

### 4. Enrich Author Profiles

When enabled, the enrichment system searches publicly available sources for additional information.

Possible results include:

```text
Biography
Workplace
Twitter / X
LinkedIn
Instagram
Facebook
Email
```

### 5. Analyze Coverage

The collected data can then be analyzed through:

- Journalist statistics
- Section distribution
- Author-topic relationships
- Article counts
- Journalist profiles

### 6. Export Results

The final dataset can be exported as CSV or JSON for additional analysis.

---

# 📊 Example Intelligence

NewsTrace can transform a collection of articles into structured intelligence such as:

```text
Journalist
├── Name
├── Role
├── Workplace
├── Biography
├── Social Profiles
│
└── Coverage
    ├── Politics
    ├── Technology
    ├── Business
    └── International
```

The author-topic network can then reveal relationships between journalists and the subjects they consistently cover.

---

# 🎯 Use Cases

NewsTrace can be useful for:

- 📰 Journalism research
- 🔎 Media intelligence
- 👤 Journalist discovery
- 📊 News coverage analysis
- 🧠 Topic and author analysis
- 🔗 Journalist relationship mapping
- 📚 Research projects
- 📈 Media monitoring
- 🕵️ Investigative research

---

# 📁 Project Structure

```text
NewsTrace/
│
├── dashboard.py
├── main.py
├── app.py
├── deep_scraper.py
│
├── scrapers/
│   └── ...
│
├── utils/
│   └── ...
│
├── data/
│   └── ...
│
├── test_google_enrichment.py
│
├── requirements.txt
├── runtime.txt
├── .env.example
├── .gitignore
│
├── DASHBOARD_GUIDE.txt
├── EXTRACTION_FLOW.txt
└── SUPABASE_SETUP.md
```

---

# 🔐 Privacy & Responsible Scraping

NewsTrace is designed to work with publicly accessible web information.

Users should:

- Respect website terms of service
- Follow applicable robots.txt and scraping policies
- Avoid excessive request rates
- Respect copyright and data protection laws
- Only collect information they are legally permitted to process
- Avoid storing sensitive personal information unnecessarily

---

# 🧩 Troubleshooting

### No articles found

Try:

- Using the full website URL
- Increasing the maximum article count
- Checking the website's accessibility
- Verifying your internet connection

### Scraping is slow

Try reducing the maximum number of articles or checking your network connection.

### Google enrichment isn't working

Verify that:

```env
SERP_API_KEY=your_key
```

is correctly configured and that Google enrichment is enabled in the dashboard.

### Playwright errors

Run:

```bash
playwright install chromium
```

again to ensure the required browser is installed.

---

# 📜 License

This project currently does not specify an open-source license.

If you intend to allow others to legally reuse, modify, or distribute the project, consider adding an appropriate license.

---

## Built With

**Python · Streamlit · Playwright · BeautifulSoup · Pandas · Supabase**


## 🗞️ Interface & Experience

The new frontend presents NewsTrace as a **vintage digital newspaper** rather than a generic SaaS dashboard:

- Issue/date masthead, publication navigation and asymmetric editorial story grid.
- Warm paper, charcoal ink, restrained oxblood accents, vintage serif headlines and compact monospaced metadata.
- Source-linked article records with publisher images when exposed by article metadata.
- Dedicated **Front page**, **Archive**, **Coverage desk** and **Byline directory** views.
- Article search, section/source/date filters, sorting and CSV/JSON exports.
- A long-running discovery interface backed by real server job IDs, stage events, processed counts, warnings and results.
- Responsive vertical newspaper flow on smaller screens, keyboard-visible focus and reduced-motion support.

## 🔄 Migration & Discovery Jobs

The API accepts a discovery request and returns a job ID immediately. The frontend polls the job status and displays the server's actual stage and count information. Discovery, extraction, optional author enrichment and optional Supabase writes run outside the page request.

A confirmed blocking issue in the old discovery path was fixed: the synchronous API-first requests probe now runs in a worker thread rather than blocking the asyncio event loop.

See [MIGRATION.md](MIGRATION.md) for the full audit and architecture.


## 🚀 Cloud Deployment

The Render Blueprint now defines two separate web services:

- **newstrace** — the original Streamlit application using Dockerfile and the /_stcore/health check.
- **newstrace-web** — the new Next.js + FastAPI application using Dockerfile.web and the /api/health check.

The new service builds the static Next.js export and serves it from FastAPI alongside the API endpoints. The legacy service remains configured and available during migration; the new service does not overwrite it.

**Persistence note:** the first-phase job scheduler and SQLite job store are process-local/single-service. Render's free container filesystem is ephemeral, so SQLite job/result snapshots are not guaranteed to survive container replacement or redeploy. Use a persistent disk or a shared durable database/queue before treating the new job store as a permanent archive. Optional Supabase article and journalist persistence remains supported.

For local setup, API routes, job statuses, persistence constraints and QA checks, see [MIGRATION.md](MIGRATION.md) and [DEPLOYMENT.md](DEPLOYMENT.md).

## 🚀 Cloud Deployment

NewsTrace is a Streamlit application that uses Playwright/Chromium for scraping. For a production deployment, use a Docker-capable host such as **Render** rather than a static-site host.

- The repository includes a `Dockerfile` and `render.yaml` for Render Blueprint deployment.
- Follow [DEPLOYMENT.md](DEPLOYMENT.md) for setup instructions and optional environment variables.
- Vercel and GitHub Pages are not drop-in hosts for this persistent Streamlit + Chromium application. GitHub is the source-code host; it does not run the app by itself.

