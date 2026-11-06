"""
Enhanced Author/Journalist Information Extractor
Comprehensive extraction with multiple strategies + social media detection
"""

import re
import json
from bs4 import BeautifulSoup


def extract_author_comprehensive(soup, html_content):
    """
    Extract author with 10+ strategies - returns detailed author info
    Returns: dict with name, role, email, bio snippet
    """
    author_info = {
        'name': None,
        'role': None,
        'email': None,
        'bio_snippet': None,
        'social': {}
    }
    
    # ============ STRATEGY 1: Author Box / Card ============
    author_box = soup.find(class_=re.compile(r'author-box|author-card|author-bio|contributor-box', re.I))
    if author_box:
        # Extract name from author box
        name_elem = author_box.find(['h2', 'h3', 'h4', 'strong', 'a'])
        if name_elem:
            author_info['name'] = clean_author_name(name_elem.get_text(strip=True))
        
        # Extract role/title
        role_elem = author_box.find(class_=re.compile(r'role|title|position|designation', re.I))
        if role_elem:
            author_info['role'] = role_elem.get_text(strip=True)
        
        # Extract bio
        bio_elem = author_box.find(['p', 'span'], class_=re.compile(r'bio|description|about', re.I))
        if bio_elem:
            author_info['bio_snippet'] = bio_elem.get_text(strip=True)[:200]
        
        # Extract email
        email = extract_email(author_box)
        if email:
            author_info['email'] = email
        
        # Extract social from author box
        author_info['social'] = extract_social_media(author_box)
    
    # ============ STRATEGY 2: Byline with rel="author" ============
    if not author_info['name']:
        byline = soup.find('a', rel='author')
        if byline:
            author_info['name'] = clean_author_name(byline.get_text(strip=True))
            # Try to get profile URL
            if byline.get('href'):
                author_info['profile_url'] = byline['href']
    
    # ============ STRATEGY 3: Common CSS Classes ============
    if not author_info['name']:
        selectors = [
            '.byline', '.author-name', '.author', '.contributor-name',
            '.writer-name', '[itemprop="author"]', '.article-author',
            '.post-author', '.entry-author', '.story-byline'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                name = clean_author_name(elem.get_text(strip=True))
                if name:
                    author_info['name'] = name
                    break
    
    # ============ STRATEGY 4: Meta Tags ============
    if not author_info['name']:
        # Author meta tag
        meta_author = soup.find('meta', attrs={'name': 'author'})
        if meta_author and meta_author.get('content'):
            author_info['name'] = clean_author_name(meta_author['content'])
        
        # Article author property
        if not author_info['name']:
            meta_article = soup.find('meta', attrs={'property': 'article:author'})
            if meta_article and meta_article.get('content'):
                author_info['name'] = clean_author_name(meta_article['content'])
    
    # ============ STRATEGY 5: JSON-LD Structured Data ============
    if not author_info['name']:
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Handle array of items
                if isinstance(data, list):
                    data = data[0] if data else {}
                
                if isinstance(data, dict) and 'author' in data:
                    author = data['author']
                    
                    if isinstance(author, dict):
                        author_info['name'] = clean_author_name(author.get('name', ''))
                        author_info['role'] = author.get('jobTitle', '')
                        if 'email' in author:
                            author_info['email'] = author['email']
                        if 'description' in author:
                            author_info['bio_snippet'] = author['description'][:200]
                        
                        # Social media from structured data
                        if 'sameAs' in author:
                            urls = author['sameAs'] if isinstance(author['sameAs'], list) else [author['sameAs']]
                            for url in urls:
                                parse_social_url(url, author_info['social'])
                    
                    elif isinstance(author, str):
                        author_info['name'] = clean_author_name(author)
                    
                    if author_info['name']:
                        break
            except:
                continue
    
    # ============ STRATEGY 6: Search in first 3 paragraphs for "By [Name]" ============
    if not author_info['name']:
        paragraphs = soup.find_all('p', limit=3)
        for p in paragraphs:
            text = p.get_text()
            match = re.search(r'By\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})', text)
            if match:
                author_info['name'] = clean_author_name(match.group(1))
                break
    
    # ============ STRATEGY 7: Look for contributor info ============
    contributor = soup.find(class_=re.compile(r'contributor|writer-info', re.I))
    if contributor and not author_info['name']:
        name_elem = contributor.find(['a', 'span', 'strong'])
        if name_elem:
            author_info['name'] = clean_author_name(name_elem.get_text(strip=True))
    
    # ============ Extract Social Media if not found yet ============
    if not author_info['social']:
        author_info['social'] = extract_social_media(soup)
    
    # ============ Extract Email if not found yet ============
    if not author_info['email']:
        author_info['email'] = extract_email(soup)
    
    return author_info


def clean_author_name(name):
    """Clean and validate author name"""
    if not name:
        return None
    
    # Remove common prefixes
    name = re.sub(r'^(By|Written by|Posted by|Author:|Reported by)\s+', '', name, flags=re.I)
    
    # Remove email addresses
    name = re.sub(r'\S+@\S+', '', name)
    
    # Remove extra whitespace
    name = ' '.join(name.split())
    
    # Validate
    if not name or len(name) < 3:
        return None
    
    # Reject if too long (>50 chars) or too many words (>5)
    if len(name) > 50 or len(name.split()) > 5:
        return None
    
    # Reject generic terms
    bad_terms = ['news desk', 'editorial', 'staff writer', 'news team', 'bureau', 
                 'unknown', 'anonymous', 'correspondent', 'wire service']
    name_lower = name.lower()
    if any(term in name_lower for term in bad_terms):
        return None
    
    # Must have at least one capital letter (name characteristic)
    if not any(c.isupper() for c in name):
        return None
    
    return name


def extract_social_media(soup_element):
    """
    Extract social media handles and URLs from page element
    Returns dict with platform: {handle, url}
    """
    social = {}
    
    # Find all links
    links = soup_element.find_all('a', href=True)
    
    for link in links:
        url = link['href']
        parse_social_url(url, social)
    
    return social


def parse_social_url(url, social_dict):
    """Parse social media URL and add to dict"""
    url = url.lower()
    
    # Twitter/X
    if 'twitter.com' in url or 'x.com' in url:
        handle = url.rstrip('/').split('/')[-1]
        if handle and not handle.startswith('intent') and not handle.startswith('share'):
            social_dict['twitter'] = {
                'handle': f"@{handle}" if not handle.startswith('@') else handle,
                'url': url
            }
    
    # LinkedIn
    elif 'linkedin.com/in/' in url:
        handle = url.rstrip('/').split('/')[-1]
        social_dict['linkedin'] = {
            'handle': handle,
            'url': url
        }
    
    # Instagram
    elif 'instagram.com' in url:
        handle = url.rstrip('/').split('/')[-1]
        if handle and handle not in ['p', 'reel', 'tv']:
            social_dict['instagram'] = {
                'handle': f"@{handle}" if not handle.startswith('@') else handle,
                'url': url
            }
    
    # Facebook
    elif 'facebook.com' in url:
        handle = url.rstrip('/').split('/')[-1]
        if handle and handle not in ['sharer', 'share']:
            social_dict['facebook'] = {
                'handle': handle,
                'url': url
            }
    
    # Medium
    elif 'medium.com/@' in url:
        handle = url.split('medium.com/')[-1].split('/')[0]
        social_dict['medium'] = {
            'handle': handle,
            'url': url
        }


def extract_email(soup_element):
    """Extract email address from element"""
    # Look for mailto: links
    mailto = soup_element.find('a', href=re.compile(r'mailto:', re.I))
    if mailto:
        email = mailto['href'].replace('mailto:', '').split('?')[0]
        if is_valid_email(email):
            return email
    
    # Search text for email patterns
    text = soup_element.get_text()
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    matches = re.findall(email_pattern, text)
    
    for email in matches:
        if is_valid_email(email):
            return email
    
    return None


def is_valid_email(email):
    """Validate email address"""
    if not email or len(email) < 5:
        return False
    
    # Must have @ and .
    if '@' not in email or '.' not in email.split('@')[1]:
        return False
    
    # Reject common fake emails
    fake_domains = ['example.com', 'test.com', 'domain.com', 'email.com']
    if any(domain in email.lower() for domain in fake_domains):
        return False
    
    return True


def extract_author_articles_count(soup_element):
    """Extract number of articles by author (if shown on page)"""
    # Look for article count indicators
    patterns = [
        r'(\d+)\s+articles?',
        r'(\d+)\s+stories',
        r'(\d+)\s+posts?'
    ]
    
    text = soup_element.get_text()
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    
    return None


def extract_author_expertise(soup_element):
    """Extract author's topics/expertise areas"""
    expertise = []
    
    # Look for tags/categories
    tags = soup_element.find_all(class_=re.compile(r'tag|topic|category|expertise', re.I))
    for tag in tags[:5]:  # Limit to 5
        text = tag.get_text(strip=True)
        if text and len(text) < 30:
            expertise.append(text)
    
    return expertise if expertise else None
