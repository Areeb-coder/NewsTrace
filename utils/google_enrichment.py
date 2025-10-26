
#it's an optional ,its not our main feature, like in this we used api(its additional feature)
"""
Google Search Enrichment using SerpAPI
Searches for journalist profiles and extracts social media, workplace, bio
"""

import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse
import time


SERPAPI_KEY = "5a0974604595d6a98d345fc137f734e5a6f7531c36e0425a5608fd7cbb830397"


def search_journalist_profile(author_name, news_outlet=None):
    """
    Search Google for journalist profile using SerpAPI
    Returns: dict with social media, workplace, bio, etc.
    """
    # Build search query
    if news_outlet:
        query = f'"{author_name}" journalist {news_outlet}'
    else:
        query = f'"{author_name}" journalist author reporter'
    
    # SerpAPI request
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 10  # Get top 10 results
    }
    
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=10)
        data = response.json()
        
        # Extract information from search results
        profile = {
            'name': author_name,
            'twitter': None,
            'linkedin': None,
            'instagram': None,
            'facebook': None,
            'email': None,
            'workplace': None,
            'bio': None,
            'website': None,
            'search_results': []
        }
        
        # Parse organic results
        if 'organic_results' in data:
            for result in data['organic_results'][:10]:
                url = result.get('link', '')
                snippet = result.get('snippet', '')
                title = result.get('title', '')
                
                # Store search result
                profile['search_results'].append({
                    'title': title,
                    'url': url,
                    'snippet': snippet
                })
                
                # Extract social media from URLs
                if 'twitter.com' in url.lower():
                    profile['twitter'] = url
                elif 'linkedin.com/in' in url.lower():
                    profile['linkedin'] = url
                elif 'instagram.com' in url.lower():
                    profile['instagram'] = url
                elif 'facebook.com' in url.lower():
                    profile['facebook'] = url
                
                # Extract workplace from snippet/title
                if not profile['workplace']:
                    workplace = extract_workplace(snippet + " " + title, author_name)
                    if workplace:
                        profile['workplace'] = workplace
                
                # Extract bio
                if not profile['bio'] and len(snippet) > 50:
                    profile['bio'] = snippet[:200]
                
                # Extract email
                if not profile['email']:
                    email = extract_email(snippet)
                    if email:
                        profile['email'] = email
        
        # Check knowledge graph for verified info
        if 'knowledge_graph' in data:
            kg = data['knowledge_graph']
            if 'description' in kg and not profile['bio']:
                profile['bio'] = kg['description']
            if 'profiles' in kg:
                for prof_link in kg['profiles']:
                    url = prof_link.get('link', '')
                    if 'twitter.com' in url and not profile['twitter']:
                        profile['twitter'] = url
                    elif 'linkedin.com' in url and not profile['linkedin']:
                        profile['linkedin'] = url
                    elif 'instagram.com' in url and not profile['instagram']:
                        profile['instagram'] = url
        
        return profile
        
    except Exception as e:
        print(f"⚠️ Search failed for {author_name}: {e}")
        return None


def extract_workplace(text, author_name):
    """Extract workplace/news organization from text"""
    # Common patterns for workplace mentions
    patterns = [
        rf'{re.escape(author_name)}[,\s]+(?:a|an|the)?\s*(?:journalist|reporter|correspondent|writer|editor)\s+(?:at|for|with)\s+([A-Z][A-Za-z\s&]+)',
        r'(?:works?|working|employed)\s+(?:at|for|with)\s+([A-Z][A-Za-z\s&]+)',
        r'(?:journalist|reporter|correspondent)\s+(?:at|for|with)\s+([A-Z][A-Za-z\s&]+)',
        r'([A-Z][A-Za-z\s&]+)\s+(?:journalist|reporter|correspondent|writer)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            workplace = match.group(1).strip()
            # Clean up
            workplace = re.sub(r'\s+', ' ', workplace)
            if len(workplace) < 50 and not any(w in workplace.lower() for w in ['http', 'www', 'twitter', 'linkedin']):
                return workplace
    
    return None


def extract_email(text):
    """Extract email address from text"""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(email_pattern, text)
    if match:
        return match.group(0)
    return None


def enrich_journalists_batch(journalists, news_outlet=None, delay=1.0):
    """
    Enrich multiple journalists with Google search data
    
    Args:
        journalists: List of journalist names or dict with 'author' key
        news_outlet: Optional news outlet name for better search
        delay: Delay between requests (respect API limits)
    
    Returns:
        List of enriched profiles
    """
    enriched = []
    
    for i, journalist in enumerate(journalists, 1):
        # Get author name
        if isinstance(journalist, dict):
            author_name = journalist.get('author') or journalist.get('Author')
        else:
            author_name = journalist
        
        if not author_name or author_name.lower() in ['unknown', 'staff', 'team']:
            continue
        
        print(f"🔍 Searching {i}/{len(journalists)}: {author_name}")
        
        # Search and enrich
        profile = search_journalist_profile(author_name, news_outlet)
        
        if profile:
            # Merge with existing data if dict
            if isinstance(journalist, dict):
                profile.update(journalist)
            enriched.append(profile)
            
            # Show what we found
            found = []
            if profile.get('twitter'): found.append('Twitter')
            if profile.get('linkedin'): found.append('LinkedIn')
            if profile.get('workplace'): found.append('Workplace')
            if profile.get('email'): found.append('Email')
            
            if found:
                print(f"   ✅ Found: {', '.join(found)}")
            else:
                print(f"   ⚠️ No additional info found")
        
        # Respect API rate limits
        if i < len(journalists):
            time.sleep(delay)
    
    return enriched


def enrich_dataframe(df, author_column='author', news_outlet=None):
    """
    Enrich a pandas DataFrame with Google search data
    
    Args:
        df: DataFrame with journalist data
        author_column: Name of the column containing author names
        news_outlet: Optional news outlet name
    
    Returns:
        Enriched DataFrame with new columns
    """
    import pandas as pd
    
    # Get unique authors
    unique_authors = df[author_column].unique()
    valid_authors = [a for a in unique_authors if a and a.lower() not in ['unknown', 'staff', 'team']]
    
    print(f"\n🔍 Enriching {len(valid_authors)} unique journalists...")
    
    # Search for profiles
    profiles = enrich_journalists_batch(valid_authors, news_outlet)
    
    # Create lookup dict
    profile_dict = {p['name']: p for p in profiles}
    
    # Add new columns to dataframe
    df['Twitter'] = df[author_column].map(lambda x: profile_dict.get(x, {}).get('twitter'))
    df['LinkedIn'] = df[author_column].map(lambda x: profile_dict.get(x, {}).get('linkedin'))
    df['Instagram'] = df[author_column].map(lambda x: profile_dict.get(x, {}).get('instagram'))
    df['Email'] = df[author_column].map(lambda x: profile_dict.get(x, {}).get('email'))
    df['Workplace'] = df[author_column].map(lambda x: profile_dict.get(x, {}).get('workplace'))
    df['Bio'] = df[author_column].map(lambda x: profile_dict.get(x, {}).get('bio'))
    
    # Stats
    print(f"\n📊 Enrichment Results:")
    print(f"   Twitter: {df['Twitter'].notna().sum()}")
    print(f"   LinkedIn: {df['LinkedIn'].notna().sum()}")
    print(f"   Instagram: {df['Instagram'].notna().sum()}")
    print(f"   Email: {df['Email'].notna().sum()}")
    print(f"   Workplace: {df['Workplace'].notna().sum()}")
    
    return df


# Test function
if __name__ == "__main__":
    # Test with a single journalist
    test_name = "Jane Doe"
    result = search_journalist_profile(test_name)
    
    if result:
        print(f"\n✅ Profile for {test_name}:")
        for key, value in result.items():
            if value and key != 'search_results':
                print(f"   {key}: {value}")
