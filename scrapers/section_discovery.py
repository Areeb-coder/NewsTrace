"""
Deep section discovery - Find all major sections on news site
"""

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re


async def discover_all_sections(website_url):
    """
    Find all major sections/categories on news site
    Returns list of section URLs
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(website_url, timeout=10000, wait_until='domcontentloaded')
        html = await page.content()
        await browser.close()
    
    soup = BeautifulSoup(html, 'lxml')
    sections = set()
    
    # Pattern 1: Main navigation menu
    nav_links = soup.select('nav a, header a, .menu a, .navbar a')
    for link in nav_links:
        href = link.get('href')
        if href:
            full_url = urljoin(website_url, href)
            if is_section_url(full_url, website_url):
                sections.add(full_url)
    
    # Pattern 2: Footer section links
    footer_links = soup.select('footer a')
    for link in footer_links:
        href = link.get('href')
        if href:
            full_url = urljoin(website_url, href)
            if is_section_url(full_url, website_url):
                sections.add(full_url)
    
    # Pattern 3: Links with section keywords
    section_keywords = ['politics', 'sports', 'business', 'tech', 'world', 
                       'opinion', 'entertainment', 'health', 'science']
    all_links = soup.find_all('a', href=True)
    for link in all_links:
        href = link['href']
        full_url = urljoin(website_url, href)
        if any(kw in full_url.lower() for kw in section_keywords):
            if is_section_url(full_url, website_url):
                sections.add(full_url)
    
    section_list = sorted(list(sections))[:15]  # Limit to 15 sections
    print(f"Discovered {len(section_list)} sections")
    return section_list


def is_section_url(url, base_url):
    """Check if URL is a valid section page"""
    if not url or not same_domain(url, base_url):
        return False
    
    # Must contain section indicators
    section_patterns = ['/section/', '/category/', '/topic/', '/news/']
    
    # Or be a main section page
    main_sections = ['politics', 'sports', 'business', 'tech', 'world',
                    'opinion', 'entertainment', 'health', 'science', 'culture']
    
    url_lower = url.lower()
    
    # Check patterns
    has_pattern = any(pattern in url_lower for pattern in section_patterns)
    has_keyword = any(section in url_lower for section in main_sections)
    
    # Skip non-section pages
    skip = ['/article/', '/story/', '/author/', '/search', '/about', '/contact']
    if any(s in url_lower for s in skip):
        return False
    
    return has_pattern or has_keyword


def same_domain(url1, url2):
    """Check if two URLs are from same domain"""
    d1 = urlparse(url1).netloc.replace('www.', '')
    d2 = urlparse(url2).netloc.replace('www.', '')
    return d1 == d2
