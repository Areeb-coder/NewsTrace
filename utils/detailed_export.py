"""
Enhanced CSV export with detailed journalist profiles
"""

import pandas as pd
import os
import re


def save_detailed_profiles(profiles, outlet_name):
    """
    Save comprehensive journalist profiles to CSV
    Returns filename and stats
    """
    # Clean outlet name for filename (remove URLs, special chars)
    clean_name = outlet_name
    if outlet_name.startswith('http'):
        # Extract domain from URL
        from urllib.parse import urlparse
        parsed = urlparse(outlet_name)
        clean_name = parsed.netloc.replace('www.', '').replace('.com', '').replace('.in', '')
    clean_name = re.sub(r'[^a-zA-Z0-9]+', '_', clean_name).strip('_').lower()
    
    # Prepare data for CSV
    csv_data = []
    
    for p in profiles:
        row = {
            'Name': p.get('name'),
            'Beat_Topics': p.get('beat'),
            'Bio': p.get('bio'),
            'Contact': p.get('email'),
            'Twitter_Handle': p.get('twitter_handle'),
            'Twitter_URL': p.get('twitter_url') or p.get('twitter'),
            'LinkedIn_Handle': p.get('linkedin_handle'),
            'LinkedIn_URL': p.get('linkedin_url') or p.get('linkedin'),
            'Instagram_Handle': p.get('instagram_handle'),
            'Instagram_URL': p.get('instagram_url'),
            'Social_Source': p.get('social_source'),
            'Articles_Count': p.get('articles_count', 0),
            'Recent_Article_Titles': ' | '.join(p.get('recent_articles', [])[:5]),
            'Profile_URL': p.get('profile_url'),
            'Sample_Article_URLs': ' | '.join(p.get('article_urls', [])[:3])
        }
        csv_data.append(row)
    
    # Create DataFrame
    df = pd.DataFrame(csv_data)
    
    # Save to CSV
    os.makedirs('data', exist_ok=True)
    filename = f"data/{clean_name}_journalists_detailed.csv"
    df.to_csv(filename, index=False)
    
    # Calculate stats
    from utils.aggregator import calculate_coverage_stats
    stats = calculate_coverage_stats(profiles)
    
    # Calculate social media stats
    twitter_count = sum(1 for p in profiles if p.get('twitter_handle') or p.get('twitter'))
    linkedin_count = sum(1 for p in profiles if p.get('linkedin_handle') or p.get('linkedin'))
    instagram_count = sum(1 for p in profiles if p.get('instagram_handle'))
    total = len(profiles)
    
    # Print summary
    outlet_display = outlet_name if not outlet_name.startswith('http') else clean_name.replace('_', ' ').title()
    print("\n" + "="*60)
    print(f"📊 JOURNALIST INTELLIGENCE REPORT - {outlet_display}")
    print("="*60)
    print(f"Total unique journalists: {stats['total_journalists']}")
    print(f"Journalists with full profiles: {stats['with_full_profiles']}")
    print(f"Journalists with email/contact: {stats['with_contact']}")
    print(f"Total articles scraped: {stats['total_articles']}")
    print(f"Sections covered: {', '.join(stats['sections_covered'][:10])}")
    print(f"\n📱 Social Media Found:")
    if total > 0:
        print(f"  Twitter: {twitter_count}/{total} ({twitter_count/total*100:.1f}%)")
        print(f"  LinkedIn: {linkedin_count}/{total} ({linkedin_count/total*100:.1f}%)")
        print(f"  Instagram: {instagram_count}/{total} ({instagram_count/total*100:.1f}%)")
    else:
        print(f"  No journalists found")
    print(f"\n✅ Saved detailed profiles to: {filename}")
    print("="*60 + "\n")
    
    return filename, stats
