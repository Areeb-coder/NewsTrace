"""
Article URL collector - FAST: API > Crawling
RSS feeds removed (unreliable - always 0 results)
"""

import asyncio
import time
import random
from playwright.async_api import async_playwright
from urllib.parse import urljoin, urlparse
from scrapers.api_scraper import try_api_scraping


# User agent rotation (anti-blocking)
USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101',
]


async def collect_article_urls(website_url, max_articles=300):
    """
    SPEED PRIORITY: API > Crawling
    RSS removed (unreliable)
    """
    start_time = time.time()
    article_urls = set()
    
    # Step 0: Try backend API first (FASTEST - 100s of articles in seconds!)
    print("🚀 Checking for backend API...")
    api_data = try_api_scraping(website_url, max_articles)
    if api_data:
        article_urls.update([a['url'] for a in api_data if a.get('url')])
        elapsed = int(time.time() - start_time)
        print(f"⚡ API Mode: Collected {len(article_urls)} URLs in {elapsed}s")
        return list(article_urls)[:max_articles]
    
    # Step 1: RSS feeds removed (unreliable, always returns 0)
    # Directly use section crawling for reliable URL collection
    
    # Step 2: HTML crawling (main method)
    print("🔍 Crawling sections...")
    remaining = max_articles
    crawled = await crawl_sections_parallel(website_url, remaining)
    article_urls.update(crawled)
    
    elapsed = int(time.time() - start_time)
    print(f"📦 Collected {len(article_urls)} total URLs in {elapsed}s")
    
    return list(article_urls)[:max_articles]


async def crawl_sections_parallel(website_url, target):
    """Crawl multiple sections in parallel"""
    article_urls = set()
    visited_pages = set()
    failed_urls = []
    start_time = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS)
        )
        page = await context.new_page()
        
        # Start crawling from homepage
        pages_to_visit = [website_url]
        
        while pages_to_visit and len(article_urls) < target:
            # Timeout check (5 minutes)
            if time.time() - start_time > 300:
                print(f"⏰ Timeout reached (5 min)")
                break
            
            current_url = pages_to_visit.pop(0)
            
            # Skip if already visited
            if current_url in visited_pages:
                continue
            
            visited_pages.add(current_url)
            
            try:
                # Random delay (1-3 seconds)
                await asyncio.sleep(random.uniform(1, 3))
                
                # Load page with timeout
                await page.goto(current_url, timeout=15000, wait_until='domcontentloaded')
                
                # Find all links on page
                links = await page.query_selector_all('a')
                
                for link in links:
                    href = await link.get_attribute('href')
                    if not href:
                        continue
                    
                    # Convert to absolute URL
                    absolute_url = urljoin(current_url, href)
                    
                    # Check if it's an article
                    if is_article_url(absolute_url, website_url):
                        article_urls.add(absolute_url)
                        
                        # Progress update
                        if len(article_urls) % 50 == 0:
                            print(f"Collected {len(article_urls)} article links...")
                    
                    # Check if it's a section/category page
                    elif is_section_page(absolute_url, website_url):
                        if absolute_url not in visited_pages:
                            pages_to_visit.append(absolute_url)
                
                # Look for pagination
                next_button = await page.query_selector('a[rel="next"], a.next, a:has-text("Next")')
                if next_button:
                    next_href = await next_button.get_attribute('href')
                    if next_href:
                        next_url = urljoin(current_url, next_href)
                        if next_url not in visited_pages:
                            pages_to_visit.append(next_url)
                
            except Exception as e:
                failed_urls.append(current_url)
                continue
        
        await browser.close()
    
    print(f"✅ Collected {len(article_urls)} unique article URLs")
    if failed_urls:
        print(f"⚠️  Failed to load {len(failed_urls)} pages")
    
    return list(article_urls)


def is_article_url(url, base_domain):
    """Check if URL looks like a news article"""
    # Must be same domain
    if not same_domain(url, base_domain):
        return False
    
    # Common article URL patterns
    article_patterns = [
        '/article/', '/story/', '/news/', '/post/',
        '/20', '/2025/', '/2024/',  # Date-based URLs
    ]
    
    # Skip non-article pages
    skip_patterns = [
        '/author/', '/tag/', '/category/', '/search',
        '/about', '/contact', '/privacy', '/terms',
        '.pdf', '.jpg', '.png', '/feed', '/rss'
    ]
    
    url_lower = url.lower()
    
    if any(skip in url_lower for skip in skip_patterns):
        return False
    
    return any(pattern in url_lower for pattern in article_patterns)


def is_section_page(url, base_domain):
    """Check if URL is a section/category page to crawl"""
    if not same_domain(url, base_domain):
        return False
    
    section_keywords = [
        '/politics', '/sports', '/business', '/tech',
        '/world', '/opinion', '/entertainment', '/health',
        '/section/', '/category/', '/topic/'
    ]
    
    return any(kw in url.lower() for kw in section_keywords)


def same_domain(url1, url2):
    """Check if two URLs are from same domain"""
    domain1 = urlparse(url1).netloc.replace('www.', '')
    domain2 = urlparse(url2).netloc.replace('www.', '')
    return domain1 == domain2
