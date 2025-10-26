"""
Parallel scraper - Speed up article scraping with concurrent workers
"""

import asyncio
from scrapers.article_scraper import scrape_journalist_info
from datetime import datetime


async def scrape_articles_parallel(article_urls, max_workers=10, target_authors=200):
    """
    Scrape articles in parallel with worker pool (≤35 lines)
    """
    all_data = []
    unique_authors = set()
    start = datetime.now()
    
    print(f"⚡ Starting parallel scraping with {max_workers} workers...")
    
    # Create worker tasks
    semaphore = asyncio.Semaphore(max_workers)
    
    async def worker(url, idx):
        async with semaphore:
            try:
                data = await scrape_journalist_info(url)
                if data and data['author'] != 'Unknown':
                    unique_authors.add(data['author'])
                return data
            except:
                return None
    
    # Process in batches for progress tracking
    batch_size = 100
    for i in range(0, len(article_urls), batch_size):
        batch = article_urls[i:i+batch_size]
        tasks = [worker(url, i+j) for j, url in enumerate(batch)]
        results = await asyncio.gather(*tasks)
        
        # Collect successful results
        all_data.extend([r for r in results if r])
        
        # Progress
        elapsed = (datetime.now() - start).seconds
        print(f"✓ Scraped {i+len(batch)}/{len(article_urls)}... {len(unique_authors)} authors in {elapsed}s")
        
        # Early stop if target reached
        if len(unique_authors) >= target_authors:
            print(f"🎯 Reached {target_authors} authors, stopping early")
            break
    
    total_time = (datetime.now() - start).seconds
    print(f"✅ Complete! {len(unique_authors)} authors in {total_time//60}m {total_time%60}s")
    
    return all_data
