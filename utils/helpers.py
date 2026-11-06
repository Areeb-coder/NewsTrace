"""
Helper utilities for NewsTrace
Keep functions short and focused
"""

import re
from urllib.parse import urlparse


def clean_text(text):
    """Remove extra whitespace and normalize text"""
    if not text:
        return None
    return re.sub(r'\s+', ' ', text).strip()


def is_valid_url(url):
    """Check if URL is valid"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False


def extract_domain(url):
    """Get domain from URL - useful for custom scrapers"""
    parsed = urlparse(url)
    return parsed.netloc.replace('www.', '')


def normalize_social_url(url, platform):
    """
    Normalize social media URLs
    e.g., twitter.com/user -> full URL
    """
    if not url:
        return None
    
    # Already full URL
    if url.startswith('http'):
        return url
    
    # Handle @username format
    if url.startswith('@'):
        url = url[1:]
    
    # Build full URL
    base_urls = {
        'twitter': 'https://twitter.com/',
        'linkedin': 'https://linkedin.com/in/',
        'facebook': 'https://facebook.com/'
    }
    
    return base_urls.get(platform, '') + url


def filter_empty_profiles(profiles):
    """Remove profiles with no meaningful data"""
    return [
        p for p in profiles 
        if any(p.get(k) for k in ['name', 'email', 'bio'])
    ]
