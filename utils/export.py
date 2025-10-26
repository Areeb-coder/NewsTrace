"""
Data export utilities
Clean CSV saving with deduplication
"""

import pandas as pd
import os
import re


def save_to_csv(data, outlet_name):
    """
    Save journalist data to CSV with deduplication
    Returns filename
    """
    # Clean outlet name for filename (handle URLs)
    clean_name = outlet_name
    if outlet_name.startswith('http'):
        from urllib.parse import urlparse
        parsed = urlparse(outlet_name)
        clean_name = parsed.netloc.replace('www.', '').replace('.com', '').replace('.in', '')
    clean_name = re.sub(r'[^a-zA-Z0-9]+', '_', clean_name).strip('_').lower()
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    # Rename columns for clean output
    df = df.rename(columns={
        'author': 'Author',
        'section': 'Section', 
        'title': 'Title',
        'date': 'Date',
        'url': 'URL'
    })
    
    # Remove duplicates by Author + Title
    original_count = len(df)
    df = df.drop_duplicates(subset=['Author', 'Title'], keep='first')
    
    # Save to file
    os.makedirs('data', exist_ok=True)
    filename = f"data/{clean_name}_journalists.csv"
    df.to_csv(filename, index=False)
    
    # Print stats
    unique_authors = len(df[df['Author'] != 'Unknown']['Author'].unique())
    print(f"Saved {len(df)} journalist profiles to {filename}")
    print(f"Unique authors: {unique_authors}, Total entries: {len(df)}")
    
    return filename
