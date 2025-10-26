# Supabase Backend Setup Guide

## Quick Start

1. **Create Supabase Account**
   - Go to https://supabase.com
   - Create a new project
   - Note your project URL and anon key

2. **Create Database Tables**

Run this SQL in Supabase SQL Editor:

```sql
-- Articles table
CREATE TABLE articles (
  id BIGSERIAL PRIMARY KEY,
  outlet TEXT NOT NULL,
  author TEXT,
  title TEXT,
  section TEXT,
  date TEXT,
  url TEXT UNIQUE,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Journalists table
CREATE TABLE journalists (
  id BIGSERIAL PRIMARY KEY,
  outlet TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT,
  email TEXT,
  bio TEXT,
  twitter TEXT,
  linkedin TEXT,
  instagram TEXT,
  facebook TEXT,
  article_count INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(outlet, name)
);

-- Indexes for performance
CREATE INDEX idx_articles_outlet ON articles(outlet);
CREATE INDEX idx_articles_author ON articles(author);
CREATE INDEX idx_journalists_outlet ON journalists(outlet);
CREATE INDEX idx_journalists_name ON journalists(name);
```

3. **Configure Environment**

Create `.env` file in project root:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here
```

4. **Install Dependencies**

```bash
pip install supabase python-dotenv
```

5. **Test Connection**

```python
from utils.supabase_backend import check_connection

connected, msg = check_connection()
print(msg)
```

## Features

- ✅ Auto-save scraped articles to database
- ✅ Auto-save journalist profiles
- ✅ Duplicate prevention (URL-based for articles, name+outlet for journalists)
- ✅ Query by outlet
- ✅ Historical tracking

## Dashboard Integration

When Supabase is configured:
1. After scraping completes, data is automatically saved
2. Dashboard shows "✅ Saved to database: X articles, Y profiles"
3. If not configured, scraping still works (database is optional)

## API Usage

```python
from utils.supabase_backend import get_articles, get_journalists

# Get recent articles from BBC
articles = get_articles(outlet_name="bbc.com", limit=50)

# Get top journalists from any outlet
journalists = get_journalists(limit=100)
```

## Notes

- Database storage is **optional** — app works fine without it
- Supabase free tier: 500MB database, 1GB bandwidth/month
- Credentials stored in `.env` (never commit this file!)
