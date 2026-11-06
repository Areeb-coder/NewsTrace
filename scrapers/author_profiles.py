"""
Author profile discovery and detailed scraping
"""

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re


async def get_author_profile_page(author_name, website_url):
    """
    Find author profile page URL
    Tries common patterns
    """
    # Create URL slug from name
    slug = author_name.lower().replace(' ', '-').replace("'", '')
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    
    # Common URL patterns
    patterns = [
        f'{website_url}/author/{slug}',
        f'{website_url}/journalist/{slug}',
        f'{website_url}/contributor/{slug}',
        f'{website_url}/profile/{slug}',
        f'{website_url}/writers/{slug}',
        f'{website_url}/staff/{slug}',
    ]
    
    # Try each pattern
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        for url in patterns:
            try:
                response = await page.goto(url, timeout=5000)
                if response and response.status < 400:
                    await browser.close()
                    return url
            except:
                continue
        
        await browser.close()
    
    return None


async def scrape_author_details(author_profile_url):
    """
    Extract detailed author info from profile page
    Returns dict with all available fields
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            await page.goto(author_profile_url, timeout=8000)
            html = await page.content()
            await browser.close()
        except:
            await browser.close()
            return None
    
    soup = BeautifulSoup(html, 'lxml')
    
    details = {
        'name': extract_author_name(soup),
        'beat': extract_beat(soup),
        'bio': extract_bio(soup),
        'email': extract_email(soup),
        'twitter': extract_social(soup, 'twitter'),
        'linkedin': extract_social(soup, 'linkedin'),
        'articles_count': extract_article_count(soup),
        'recent_articles': extract_recent_articles(soup)
    }
    
    # Add comprehensive social media extraction
    from scrapers.article_scraper import extract_social_comprehensive
    social_data = extract_social_comprehensive(soup)
    details.update(social_data)
    
    return details


def extract_author_name(soup):
    """Extract full name from profile"""
    name_elem = soup.select_one('h1, .author-name, .profile-name')
    return name_elem.get_text(strip=True) if name_elem else None


def extract_beat(soup):
    """Extract topics/beat covered"""
    beat_elem = soup.select_one('.beat, .topics, .expertise, .coverage')
    if beat_elem:
        return beat_elem.get_text(strip=True)
    
    # Try meta tags
    meta = soup.find('meta', attrs={'name': 'keywords'})
    return meta['content'] if meta else None


def extract_bio(soup):
    """Extract biography"""
    bio_elem = soup.select_one('.bio, .biography, .about, .description')
    if bio_elem:
        bio = bio_elem.get_text(strip=True)
        return bio[:200] + '...' if len(bio) > 200 else bio
    return None


def extract_email(soup):
    """Extract email if available"""
    email_link = soup.find('a', href=re.compile(r'mailto:'))
    return email_link['href'].replace('mailto:', '') if email_link else None


def extract_social(soup, platform):
    """Extract social media link"""
    pattern = platform.lower()
    social_link = soup.find('a', href=re.compile(pattern))
    return social_link['href'] if social_link else None


def extract_article_count(soup):
    """Extract total articles count if shown"""
    count_elem = soup.find(text=re.compile(r'\d+\s+(articles|stories|posts)'))
    if count_elem:
        match = re.search(r'(\d+)', count_elem)
        return int(match.group(1)) if match else None
    return None


def extract_recent_articles(soup):
    """Extract list of recent article titles"""
    articles = []
    article_links = soup.select('.article-title a, .story-title a, h3 a, h4 a')[:5]
    
    for link in article_links:
        title = link.get_text(strip=True)
        if title and len(title) > 10:
            articles.append(title)
    
    return articles if articles else None
