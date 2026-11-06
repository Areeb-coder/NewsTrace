"""
Supabase Backend Integration
Save scraped articles and journalist profiles to Supabase database
"""

import os
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Supabase credentials (set in .env file)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def get_supabase_client() -> Client:
    """Initialize and return Supabase client"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase credentials not found. Set SUPABASE_URL and SUPABASE_KEY in .env file")
    
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def save_articles(articles_df, outlet_name):
    """
    Save scraped articles to Supabase 'articles' table
    
    Schema:
    - id (auto)
    - outlet (text)
    - author (text)
    - title (text)
    - section (text)
    - date (text)
    - url (text)
    - created_at (timestamp)
    """
    try:
        supabase = get_supabase_client()
        
        # Convert DataFrame to list of dicts
        records = []
        for _, row in articles_df.iterrows():
            record = {
                "outlet": outlet_name,
                "author": row.get("author", "Unknown"),
                "title": row.get("title", ""),
                "section": row.get("section", ""),
                "date": row.get("date", ""),
                "url": row.get("url", ""),
                "created_at": datetime.now().isoformat()
            }
            records.append(record)
        
        # Batch insert (Supabase handles duplicates if url is unique key)
        response = supabase.table("articles").insert(records).execute()
        
        return {
            "success": True,
            "count": len(records),
            "message": f"Saved {len(records)} articles to Supabase"
        }
    
    except Exception as e:
        return {
            "success": False,
            "count": 0,
            "message": f"Error saving articles: {str(e)}"
        }


def save_journalist_profiles(articles_df, outlet_name):
    """
    Save journalist profiles to Supabase 'journalists' table
    
    Schema:
    - id (auto)
    - outlet (text)
    - name (text)
    - role (text)
    - email (text)
    - bio (text)
    - twitter (text)
    - linkedin (text)
    - instagram (text)
    - facebook (text)
    - article_count (int)
    - created_at (timestamp)
    """
    try:
        supabase = get_supabase_client()
        
        # Group by author and aggregate
        if 'author' not in articles_df.columns:
            return {"success": False, "count": 0, "message": "No author column found"}
        
        author_groups = articles_df[articles_df['author'] != 'Unknown'].groupby('author')
        
        records = []
        for author, group in author_groups:
            record = {
                "outlet": outlet_name,
                "name": author,
                "article_count": len(group),
                "created_at": datetime.now().isoformat()
            }
            
            # Add optional fields if they exist
            for field in ['author_role', 'author_email', 'author_bio', 'twitter', 'linkedin', 'instagram', 'facebook']:
                if field in group.columns:
                    value = group[field].dropna().iloc[0] if len(group[field].dropna()) > 0 else None
                    # Map author_* fields to shorter names
                    db_field = field.replace('author_', '')
                    record[db_field] = value
            
            records.append(record)
        
        # Batch insert
        response = supabase.table("journalists").insert(records).execute()
        
        return {
            "success": True,
            "count": len(records),
            "message": f"Saved {len(records)} journalist profiles to Supabase"
        }
    
    except Exception as e:
        return {
            "success": False,
            "count": 0,
            "message": f"Error saving profiles: {str(e)}"
        }


def get_articles(outlet_name=None, limit=100):
    """Retrieve articles from Supabase"""
    try:
        supabase = get_supabase_client()
        
        query = supabase.table("articles").select("*").limit(limit).order("created_at", desc=True)
        
        if outlet_name:
            query = query.eq("outlet", outlet_name)
        
        response = query.execute()
        return response.data
    
    except Exception as e:
        print(f"Error fetching articles: {e}")
        return []


def get_journalists(outlet_name=None, limit=100):
    """Retrieve journalist profiles from Supabase"""
    try:
        supabase = get_supabase_client()
        
        query = supabase.table("journalists").select("*").limit(limit).order("article_count", desc=True)
        
        if outlet_name:
            query = query.eq("outlet", outlet_name)
        
        response = query.execute()
        return response.data
    
    except Exception as e:
        print(f"Error fetching journalists: {e}")
        return []


def check_connection():
    """Test Supabase connection"""
    try:
        supabase = get_supabase_client()
        # Try a simple query
        response = supabase.table("articles").select("id").limit(1).execute()
        return True, "Connected to Supabase successfully"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"
