"""
Site-specific scrapers
Add custom logic for different news outlets here
"""

from bs4 import BeautifulSoup


def scrape_generic_site(html):
    """
    Generic scraper - works for most sites
    Override with custom functions for specific outlets
    """
    soup = BeautifulSoup(html, 'lxml')
    profiles = []
    
    # Look for author/staff pages
    # Most sites use similar patterns
    containers = soup.find_all(['div', 'article', 'section'])
    
    for container in containers:
        # Skip if no relevant content
        if not has_journalist_keywords(container):
            continue
        
        profile = {
            'name': extract_name(container),
            'role': extract_role(container),
            'bio': extract_bio(container),
            'email': extract_email(container),
        }
        
        if profile['name']:
            profiles.append(profile)
    
    return profiles


def has_journalist_keywords(element):
    """Check if element likely contains journalist info"""
    text = element.get_text().lower()
    keywords = ['journalist', 'reporter', 'editor', 'writer', 'author', 'correspondent']
    return any(kw in text for kw in keywords)


def extract_name(element):
    """Extract name from various HTML patterns"""
    # Try heading tags first
    for tag in ['h1', 'h2', 'h3', 'h4']:
        name = element.find(tag)
        if name:
            return name.get_text(strip=True)
    
    # Try class-based search
    name = element.find(class_=lambda x: x and 'name' in x.lower())
    return name.get_text(strip=True) if name else None


def extract_role(element):
    """Extract job title/role"""
    role = element.find(class_=lambda x: x and any(
        t in x.lower() for t in ['role', 'title', 'position', 'job']
    ))
    return role.get_text(strip=True) if role else None


def extract_bio(element):
    """Extract biography text"""
    bio = element.find(class_=lambda x: x and 'bio' in x.lower())
    if not bio:
        # Fallback to first paragraph
        bio = element.find('p')
    return bio.get_text(strip=True) if bio else None


def extract_email(element):
    """Extract email if available"""
    email_link = element.find('a', href=lambda x: x and 'mailto:' in x)
    if email_link:
        return email_link['href'].replace('mailto:', '')
    return None


# --- Add custom scrapers for specific sites below ---

def scrape_nytimes(html):
    """Custom scraper for NYTimes (example)"""
    # TODO: Add NYT-specific logic
    return scrape_generic_site(html)


def scrape_bbc(html):
    """Custom scraper for BBC (example)"""
    # TODO: Add BBC-specific logic
    return scrape_generic_site(html)
