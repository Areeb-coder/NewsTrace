"""
NewsTrace - Main scraping logic
Simple, human-readable scraper for journalist profiles
"""

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import pandas as pd
import json
import argparse
from utils.website_finder import find_website
from utils.article_collector import collect_article_urls
from scrapers.article_scraper import scrape_journalist_info, scrape_all_articles
from utils.export import save_to_csv as export_to_csv


# --- Playwright Scraper (for JS-heavy sites) ---

async def scrape_with_playwright(url):
    """
    Use Playwright to load JavaScript-heavy pages
    Returns HTML content after JS execution
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Load page and wait for content
        await page.goto(url, wait_until="networkidle")
        content = await page.content()
        
        await browser.close()
        return content


# --- BeautifulSoup Parser ---

def parse_journalist_profiles(html):
    """
    Extract journalist info from HTML
    Returns list of dicts with name, role, bio, etc.
    """
    soup = BeautifulSoup(html, 'lxml')
    profiles = []
    
    # TODO: Customize selectors based on target site
    # Example structure - adapt to real sites
    
    # Look for common journalist card patterns
    cards = soup.find_all(['div', 'article'], class_=lambda x: x and any(
        term in x.lower() for term in ['author', 'journalist', 'staff', 'writer']
    ))
    
    for card in cards:
        profile = extract_profile_data(card)
        if profile:
            profiles.append(profile)
    
    return profiles


def extract_profile_data(element):
    """
    Extract individual journalist data from HTML element
    Max 30 lines - keep it simple!
    """
    profile = {}
    
    # Name - common patterns
    name_tag = element.find(['h2', 'h3', 'h4', 'a'], class_=lambda x: x and 'name' in x.lower())
    profile['name'] = name_tag.get_text(strip=True) if name_tag else None
    
    # Role/Title
    role_tag = element.find(['p', 'span'], class_=lambda x: x and any(
        t in x.lower() for t in ['role', 'title', 'position']
    ))
    profile['role'] = role_tag.get_text(strip=True) if role_tag else None
    
    # Bio
    bio_tag = element.find(['p', 'div'], class_=lambda x: x and 'bio' in x.lower())
    profile['bio'] = bio_tag.get_text(strip=True) if bio_tag else None
    
    # Email (if available)
    email_tag = element.find('a', href=lambda x: x and 'mailto:' in x)
    profile['email'] = email_tag['href'].replace('mailto:', '') if email_tag else None
    
    # Social links
    profile['twitter'] = find_social_link(element, 'twitter')
    profile['linkedin'] = find_social_link(element, 'linkedin')
    
    return profile if profile['name'] else None


def find_social_link(element, platform):
    """Find social media link for given platform"""
    link = element.find('a', href=lambda x: x and platform in x.lower())
    return link['href'] if link else None


# --- Export Functions ---

def save_to_csv(profiles, filename='data/journalists.csv'):
    """Save profiles to CSV using pandas"""
    df = pd.DataFrame(profiles)
    df.to_csv(filename, index=False)
    print(f"✅ Saved {len(profiles)} profiles to {filename}")


def save_to_json(profiles, filename='data/journalists.json'):
    """Save profiles to JSON"""
    with open(filename, 'w') as f:
        json.dump(profiles, f, indent=2)
    print(f"✅ Saved {len(profiles)} profiles to {filename}")


# --- Batch Article Scraper ---

async def scrape_articles_batch(article_urls, max_concurrent=5):
    """
    Scrape multiple articles concurrently
    Limits concurrent requests to avoid overload
    """
    results = []
    
    for i in range(0, len(article_urls), max_concurrent):
        batch = article_urls[i:i+max_concurrent]
        
        # Process batch concurrently
        tasks = [scrape_journalist_info(url) for url in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None and exceptions
        for result in batch_results:
            if result and not isinstance(result, Exception):
                results.append(result)
        
        print(f"📊 Processed {len(results)}/{len(article_urls)} articles")
    
    return results


# --- Main Runner ---

async def scrape_site(url, output_format='csv'):
    """
    Main function to scrape a news site
    1. Fetch page with Playwright
    2. Parse with BeautifulSoup
    3. Export data
    """
    print(f"🔍 Scraping: {url}")
    
    # Fetch page
    html = await scrape_with_playwright(url)
    
    # Parse profiles
    profiles = parse_journalist_profiles(html)
    print(f"📊 Found {len(profiles)} profiles")
    
    # Export
    if profiles:
        if output_format == 'csv':
            save_to_csv(profiles)
        else:
            save_to_json(profiles)
    
    return profiles


# --- CLI Entry Point ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Scrape journalist profiles')
    parser.add_argument('--url', help='News site URL')
    parser.add_argument('--outlet', help='News outlet name (will search for URL)')
    parser.add_argument('--format', default='csv', choices=['csv', 'json'])
    parser.add_argument('--collect-articles', action='store_true', 
                       help='Collect article URLs from site')
    parser.add_argument('--max-articles', type=int, default=300,
                       help='Max articles to collect (default: 300)')
    parser.add_argument('--scrape-articles', help='Scrape articles from URLs file')
    parser.add_argument('--concurrent', type=int, default=5,
                       help='Concurrent requests (default: 5)')
    
    args = parser.parse_args()
    
    # Get URL - either direct or search for outlet
    url = args.url
    if not url and args.outlet:
        url = find_website(args.outlet)
    
    if not url:
        print("❌ Please provide --url or --outlet")
        exit(1)
    
    # Collect articles mode
    if args.collect_articles:
        articles = asyncio.run(collect_article_urls(url, args.max_articles))
        # Save to file
        with open('data/article_urls.txt', 'w') as f:
            f.write('\n'.join(articles))
        print(f"📝 Saved to data/article_urls.txt")
    
    # Scrape articles from file
    elif args.scrape_articles:
        with open(args.scrape_articles, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        print(f"🔍 Scraping articles to find unique authors...")
        results = asyncio.run(scrape_all_articles(urls))
        
        if results:
            # Use new export function
            outlet = args.outlet or "newstrace"
            export_to_csv(results, outlet)
    
    else:
        # Run profile scraper
        asyncio.run(scrape_site(url, args.format))
