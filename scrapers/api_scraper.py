"""
API-First Scraper - Check backend APIs before HTML parsing (10x faster!)
"""

import requests
import json
from urllib.parse import urlparse, urljoin


def find_api_endpoints(website_url):
    """Detect common news API patterns (≤15 lines)"""
    domain = urlparse(website_url).netloc
    base = website_url.rstrip('/')
    
    # Common API patterns for news sites
    api_patterns = [
        f"{base}/api/articles",
        f"{base}/api/v1/content",
        f"{base}/wp-json/wp/v2/posts",  # WordPress
        f"{base}/graphql",  # GraphQL
        f"{base}/api/search",
        f"{base}/feed/json",
        f"https://api.{domain}/articles",
    ]
    
    return api_patterns


def try_api_scraping(website_url, max_articles=500):
    """Try API endpoints first, return JSON data if found (≤25 lines)"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json'
    })
    
    # Try common API endpoints
    for api_url in find_api_endpoints(website_url):
        try:
            # Test with pagination
            params = {'page': 1, 'per_page': 100, 'limit': 100, 'size': 100}
            resp = session.get(api_url, params=params, timeout=5)
            
            if resp.status_code == 200 and 'application/json' in resp.headers.get('Content-Type', ''):
                data = resp.json()
                
                # Found API! Extract articles
                articles = extract_articles_from_json(data)
                if articles:
                    print(f"✅ Found API: {api_url}")
                    print(f"📦 Extracting via API (fast mode)...")
                    
                    # Paginate to get more
                    all_articles = articles
                    for page in range(2, min(max_articles // 100 + 1, 20)):
                        params['page'] = page
                        r = session.get(api_url, params=params, timeout=5)
                        if r.status_code == 200:
                            more = extract_articles_from_json(r.json())
                            if not more:
                                break
                            all_articles.extend(more)
                        else:
                            break
                    
                    return all_articles[:max_articles]
        except:
            continue
    
    return None  # No API found, fall back to HTML


def extract_articles_from_json(data):
    """Extract article data from JSON response (≤20 lines)"""
    articles = []
    
    # Handle different JSON structures
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Try common keys
        for key in ['articles', 'posts', 'data', 'items', 'results', 'content']:
            if key in data:
                items = data[key] if isinstance(data[key], list) else [data[key]]
                break
    
    # Extract fields from each item
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        
        article = {
            'title': item.get('title') or item.get('headline') or '',
            'author': item.get('author') or item.get('byline') or 'Unknown',
            'url': item.get('url') or item.get('link') or item.get('permalink') or '',
            'date': item.get('date') or item.get('published') or item.get('created_at') or '',
            'section': item.get('section') or item.get('category') or item.get('topic') or ''
        }
        
        if article['title']:  # Only add if has title
            articles.append(article)
    
    return articles
