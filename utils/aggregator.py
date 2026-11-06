"""
Data aggregation - Combine all scraped data into comprehensive profiles
"""

from collections import defaultdict


def aggregate_journalist_data(all_articles, author_profiles=None):
    """
    Group articles by author and create comprehensive profiles
    Returns list of detailed journalist profiles
    """
    # Group by author
    by_author = defaultdict(list)
    for article in all_articles:
        if article.get('author') and article['author'] != 'Unknown':
            by_author[article['author']].append(article)
    
    profiles = []
    
    for author_name, articles in by_author.items():
        # Calculate aggregates from articles
        sections = list(set(a['section'] for a in articles if a.get('section')))
        article_urls = [a['url'] for a in articles if a.get('url')][:5]
        titles = [a['title'] for a in articles if a.get('title')][:5]
        
        # Get dates
        dates = [a['date'] for a in articles if a.get('date')]
        most_recent = max(dates) if dates else None
        
        # Base profile from articles
        profile = {
            'name': author_name,
            'beat': ', '.join(sections[:3]) if sections else None,
            'bio': None,
            'email': None,
            'twitter': None,
            'linkedin': None,
            'articles_count': len(articles),
            'recent_articles': titles,
            'article_urls': article_urls,
            'most_recent_date': most_recent,
            'profile_url': None
        }
        
        # Merge with detailed profile if available
        if author_profiles and author_name in author_profiles:
            detailed = author_profiles[author_name]
            profile.update({k: v for k, v in detailed.items() if v})
        
        profiles.append(profile)
    
    # Sort by article count (most active first)
    profiles.sort(key=lambda x: x['articles_count'], reverse=True)
    
    return profiles


def calculate_coverage_stats(profiles):
    """Calculate summary statistics"""
    total_journalists = len(profiles)
    with_profiles = sum(1 for p in profiles if p.get('bio'))
    with_contact = sum(1 for p in profiles if p.get('email'))
    total_articles = sum(p['articles_count'] for p in profiles)
    
    all_sections = set()
    for p in profiles:
        if p.get('beat'):
            all_sections.update(p['beat'].split(', '))
    
    return {
        'total_journalists': total_journalists,
        'with_full_profiles': with_profiles,
        'with_contact': with_contact,
        'total_articles': total_articles,
        'sections_covered': sorted(list(all_sections))
    }
