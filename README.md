# 🔍 NewsTrace

### Journalist Intelligence & News Coverage Analysis Platform

NewsTrace is an intelligent web-scraping platform designed to discover journalists, analyze their coverage patterns, and extract structured information from news websites.

Instead of manually searching through hundreds of articles and author pages, NewsTrace automates the process of discovering articles, identifying journalists, extracting author information, and enriching journalist profiles with additional publicly available data.

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

```text
                    ┌─────────────────────┐
                    │   NewsTrace UI      │
                    │     Streamlit       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Website Resolver  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Article Discovery  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Parallel Web Scraper │
                    │      Playwright      │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
             ┌──────────────┐     ┌───────────────┐
             │ Author       │     │ Article       │
             │ Extraction   │     │ Metadata      │
             └──────┬───────┘     └───────┬───────┘
                    │                      │
                    └──────────┬───────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Google Enrichment  │
                    │      (Optional)     │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Structured Journalist│
                    │       Dataset       │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
             ┌──────────────┐     ┌───────────────┐
             │ Data Table   │     │ Author-Topic  │
             │              │     │ Network       │
             └──────────────┘     └───────────────┘
```

---

# 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| **Python** | Core application |
| **Streamlit** | Interactive dashboard |
| **Playwright** | Browser automation & web scraping |
| **BeautifulSoup** | HTML parsing |
| **Pandas** | Data processing & analysis |
| **Google / SERP API** | Optional journalist enrichment |
| **Supabase** | Optional backend data storage |

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

Start the Streamlit dashboard:

```bash
streamlit run app.py
```

Then open:

```text
http://localhost:8501
```

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


## 🎛️ Interface & Experience

The Streamlit interface is designed as a focused media-intelligence workspace:

- A persistent workspace sidebar and clear investigation entry point.
- A dark newsroom-inspired visual system with restrained mint accents, compact metadata and readable typography.
- Separate **Overview**, **Coverage**, **Journalists** and **Dataset** workspaces.
- Search and section filters for collected records, with CSV and JSON exports.
- Coverage charts and an author–section relationship view.
- Responsive layout adjustments and reduced-motion support.

The interface prioritizes evidence, legibility and useful data exploration over decorative animation.

## 🚀 Cloud Deployment

NewsTrace is a Streamlit application that uses Playwright/Chromium for scraping. For a production deployment, use a Docker-capable host such as **Render** rather than a static-site host.

- The repository includes a `Dockerfile` and `render.yaml` for Render Blueprint deployment.
- Follow [DEPLOYMENT.md](DEPLOYMENT.md) for setup instructions and optional environment variables.
- Vercel and GitHub Pages are not drop-in hosts for this persistent Streamlit + Chromium application. GitHub is the source-code host; it does not run the app by itself.

