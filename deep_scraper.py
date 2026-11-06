"""
Master orchestrator - Deep intelligence gathering pipeline (OPTIMIZED)
"""

import asyncio
from scrapers.section_discovery import discover_all_sections
from scrapers.section_crawler import crawl_section_deeply
from scrapers.parallel_scraper import scrape_articles_parallel
from scrapers.author_profiles import get_author_profile_page, scrape_author_details
from utils.aggregator import aggregate_journalist_data
from utils.detailed_export import save_detailed_profiles
from utils.article_collector import try_rss_feeds
from utils.google_enrichment import enrich_journalists_batch


async def run_deep_intelligence(website_url, outlet_name, max_articles=500, use_google_enrichment=True):
    """
    FAST deep intelligence pipeline with parallel processing + Google enrichment
    1. RSS feeds first (instant)
    2. Parallel section discovery + crawling
    3. Parallel article scraping (10 workers)
    4. Parallel profile enrichment (from website)
    5. Google enrichment (SerpAPI search for social media, workplace, bio)
    6. Export detailed CSV
    """
    print(f"\n🔍 Starting Deep Intelligence Gathering for {outlet_name}")
    print("="*60)
    
    all_article_urls = set()
    
    # SPEED BOOST 1: Try RSS feeds first (instant 50-100 articles)
    print("\n� Step 1: Checking RSS feeds...")
    rss_urls = try_rss_feeds(website_url)
    all_article_urls.update(rss_urls)
    print(f"Found {len(rss_urls)} articles from RSS")
    
    # SPEED BOOST 2: Parallel section crawling
    if len(all_article_urls) < max_articles:
        print(f"\n📂 Step 2: Discovering & crawling sections in parallel...")
        sections = await discover_all_sections(website_url)
        
        # Crawl top 5 sections in parallel
        remaining = max_articles - len(all_article_urls)
        tasks = [crawl_section_deeply(s, max_pages=20) for s in sections[:5]]
        results = await asyncio.gather(*tasks)
        
        for section_articles in results:
            all_article_urls.update(section_articles)
            if len(all_article_urls) >= max_articles:
                break
        
        print(f"Crawled {len(sections[:5])} sections, found {len(all_article_urls)} total URLs")
    
    article_list = list(all_article_urls)[:max_articles]
    
    # SPEED BOOST 3: Parallel article scraping with 10 workers
    print(f"\n⚡ Step 3: Scraping {len(article_list)} articles with 10 workers...")
    articles_data = await scrape_articles_parallel(article_list, max_workers=10, target_authors=200)
    
    # SPEED BOOST 4: Parallel profile enrichment (5 concurrent)
    print(f"\n👤 Step 4: Enriching profiles in parallel...")
    unique_authors = list(set(a['author'] for a in articles_data if a.get('author') != 'Unknown'))
    
    async def get_profile(author):
        profile_url = await get_author_profile_page(author, website_url)
        if profile_url:
            details = await scrape_author_details(profile_url)
            if details:
                details['profile_url'] = profile_url
                return author, details
        return author, None
    
    # Process 5 profiles at a time
    semaphore = asyncio.Semaphore(5)
    async def limited_get_profile(author):
        async with semaphore:
            return await get_profile(author)
    
    tasks = [limited_get_profile(a) for a in unique_authors[:50]]
    results = await asyncio.gather(*tasks)
    
    author_profiles = {author: details for author, details in results if details}
    print(f"✅ Enriched {len(author_profiles)}/{len(unique_authors)} profiles")
    
    # Step 5: Google enrichment (optional but powerful!)
    if use_google_enrichment:
        print(f"\n🌐 Step 5: Google enrichment (searching for social media, workplace, bio)...")
        google_profiles = enrich_journalists_batch(unique_authors[:30], news_outlet=outlet_name, delay=1.0)
        
        # Merge Google data with existing profiles
        for gprofile in google_profiles:
            author = gprofile['name']
            if author not in author_profiles:
                author_profiles[author] = {}
            
            # Add Google-found data
            if gprofile.get('twitter'):
                author_profiles[author]['twitter'] = gprofile['twitter']
            if gprofile.get('linkedin'):
                author_profiles[author]['linkedin'] = gprofile['linkedin']
            if gprofile.get('instagram'):
                author_profiles[author]['instagram'] = gprofile['instagram']
            if gprofile.get('email'):
                author_profiles[author]['email'] = gprofile['email']
            if gprofile.get('workplace'):
                author_profiles[author]['workplace'] = gprofile['workplace']
            if gprofile.get('bio'):
                author_profiles[author]['bio'] = gprofile['bio']
    
    # Step 6: Aggregate and export
    print(f"\n📊 Step 6: Aggregating data...")
    comprehensive_profiles = aggregate_journalist_data(articles_data, author_profiles)
    
    # Export
    filename, stats = save_detailed_profiles(comprehensive_profiles, outlet_name)
    
    return comprehensive_profiles, stats


# CLI runner
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python deep_scraper.py <outlet_name>")
        sys.exit(1)
    
    outlet = sys.argv[1]
    
    # Import website finder
    from utils.website_finder import find_website
    
    # Find website
    url = find_website(outlet)
    if not url:
        print(f"Could not find website for {outlet}")
        sys.exit(1)
    
    # Run deep intelligence
    asyncio.run(run_deep_intelligence(url, outlet, max_articles=500))
