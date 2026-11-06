"""
Test Google Enrichment - SerpAPI Integration
Demonstrates searching for journalist profiles via Google
"""

import sys
sys.path.append('.')

from utils.google_enrichment import search_journalist_profile, enrich_journalists_batch


def test_single_journalist():
    """Test searching for a single well-known journalist"""
    print("\n" + "="*60)
    print("🧪 TEST 1: Single Journalist Search")
    print("="*60)
    
    # Test with a well-known journalist
    test_name = "Anderson Cooper"
    news_outlet = "CNN"
    
    print(f"\n🔍 Searching for: {test_name} at {news_outlet}")
    
    result = search_journalist_profile(test_name, news_outlet)
    
    if result:
        print(f"\n✅ Profile Found for {test_name}:")
        print("-" * 40)
        
        if result.get('twitter'):
            print(f"   🐦 Twitter: {result['twitter']}")
        if result.get('linkedin'):
            print(f"   💼 LinkedIn: {result['linkedin']}")
        if result.get('instagram'):
            print(f"   📸 Instagram: {result['instagram']}")
        if result.get('email'):
            print(f"   📧 Email: {result['email']}")
        if result.get('workplace'):
            print(f"   🏢 Workplace: {result['workplace']}")
        if result.get('bio'):
            print(f"   📝 Bio: {result['bio'][:150]}...")
        
        print(f"\n   📰 Found {len(result.get('search_results', []))} search results")
        for i, sr in enumerate(result.get('search_results', [])[:3], 1):
            print(f"      {i}. {sr['title']}")
            print(f"         {sr['url']}")
    else:
        print(f"   ❌ No profile found")


def test_batch_journalists():
    """Test enriching multiple journalists at once"""
    print("\n" + "="*60)
    print("🧪 TEST 2: Batch Journalist Enrichment")
    print("="*60)
    
    # Test journalists
    journalists = [
        "Jake Tapper",
        "Rachel Maddow",
        "Chris Wallace"
    ]
    
    print(f"\n🔍 Searching for {len(journalists)} journalists...")
    
    results = enrich_journalists_batch(journalists, news_outlet="CNN/MSNBC/Fox", delay=1.0)
    
    print(f"\n✅ Enrichment Complete!")
    print("-" * 60)
    
    for profile in results:
        print(f"\n👤 {profile['name']}")
        
        found = []
        if profile.get('twitter'): found.append('Twitter')
        if profile.get('linkedin'): found.append('LinkedIn')
        if profile.get('workplace'): found.append('Workplace')
        if profile.get('email'): found.append('Email')
        
        if found:
            print(f"   ✅ Found: {', '.join(found)}")
            if profile.get('twitter'):
                print(f"      🐦 {profile['twitter']}")
            if profile.get('linkedin'):
                print(f"      💼 {profile['linkedin']}")
            if profile.get('workplace'):
                print(f"      🏢 {profile['workplace']}")
        else:
            print(f"   ⚠️ No additional info found")


def test_with_dataframe():
    """Test enriching a pandas DataFrame"""
    print("\n" + "="*60)
    print("🧪 TEST 3: DataFrame Enrichment")
    print("="*60)
    
    import pandas as pd
    
    # Sample data
    data = {
        'author': ['Christiane Amanpour', 'Wolf Blitzer', 'Don Lemon'],
        'title': ['Article 1', 'Article 2', 'Article 3'],
        'url': ['http://example.com/1', 'http://example.com/2', 'http://example.com/3']
    }
    
    df = pd.DataFrame(data)
    
    print("\n📊 Original DataFrame:")
    print(df)
    
    print("\n🔍 Enriching with Google search...")
    
    from utils.google_enrichment import enrich_dataframe
    enriched_df = enrich_dataframe(df, author_column='author', news_outlet='CNN')
    
    print("\n✅ Enriched DataFrame:")
    print(enriched_df[['author', 'Twitter', 'LinkedIn', 'Workplace']].to_string())


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🚀 Google Enrichment Test Suite")
    print("="*60)
    print("\nUsing SerpAPI to search Google for journalist profiles")
    print("Testing social media extraction, workplace detection, and bio scraping\n")
    
    # Run tests
    try:
        test_single_journalist()
        input("\n⏸️  Press Enter to continue to batch test...")
        
        test_batch_journalists()
        input("\n⏸️  Press Enter to continue to DataFrame test...")
        
        test_with_dataframe()
        
        print("\n" + "="*60)
        print("✅ All tests complete!")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error during tests: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
