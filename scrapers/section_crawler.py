"""
Deep section crawler - FAST parallel crawling with reduced delays
"""

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import asyncio
import random


async def crawl_section_deeply(section_url, max_pages=50):
    """
    FAST crawl with reduced delays and early stopping
    Returns set of unique article URLs
    """
    article_urls = set()
    visited_pages = set()
    pages_to_visit = [section_url]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        page_count = 0
        while pages_to_visit and page_count < max_pages:
            current_url = pages_to_visit.pop(0)
            
            if current_url in visited_pages:
                continue
            
            visited_pages.add(current_url)
            page_count += 1
            
            try:
                # SPEED: Reduced delay (0.5-1s instead of 1-2s)
                await asyncio.sleep(random.uniform(0.5, 1))
                
                # SPEED: Shorter timeout (5s instead of 8s)
                await page.goto(current_url, timeout=5000, wait_until='domcontentloaded')
                html = await page.content()
                soup = BeautifulSoup(html, 'lxml')
                
                # Find article links on this page
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link['href']
                    full_url = urljoin(current_url, href)
                    
                    if is_article_url(full_url, section_url):
                        article_urls.add(full_url)
                
                # SPEED: Early stop if we have enough articles
                if len(article_urls) >= 100:
                    break
                
                # Find pagination links (limit to 2)
                next_links = find_pagination_links(soup, current_url)
                for next_url in next_links[:2]:
                    if next_url not in visited_pages:
                        pages_to_visit.append(next_url)
                
            except Exception as e:
                continue
        
        await browser.close()
    
    return article_urls


def is_article_url(url, base_url):
    """Check if URL looks like an article"""
    url_lower = url.lower()
    
    # Article patterns
    article_patterns = ['/article/', '/story/', '/news/', '/post/', '/20']
    if not any(p in url_lower for p in article_patterns):
        return False
    
    # Skip non-articles
    skip = ['/author/', '/tag/', '/category/', '/search', '.pdf', '.jpg']
    if any(s in url_lower for s in skip):
        return False
    
    return True


def find_pagination_links(soup, current_url):
    """Find next page links for pagination"""
    next_urls = []
    
    # Common pagination patterns
    next_buttons = soup.select('a.next, a[rel="next"], .pagination a, .pager a')
    
    for button in next_buttons:
        href = button.get('href')
        if href:
            full_url = urljoin(current_url, href)
            next_urls.append(full_url)
    
    return next_urls[:3]  # Limit to 3 next pages
