#!/usr/bin/env python3
"""Test script for enhanced URL filtering patterns."""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from headline_worker.modules.url_utils import is_valid_article_url

def test_enhanced_filtering():
    """Test all 8 points of enhanced URL filtering."""
    
    test_cases = [
        # Point 1: Enhanced File Extension Filtering
        ('https://example.com/article.mp4', 'https://example.com', False, 'Point 1: Video file extension'),
        ('https://example.com/article.ogg', 'https://example.com', False, 'Point 1: Audio file extension'),
        ('https://example.com/article.rar', 'https://example.com', False, 'Point 1: Archive file extension'),
        ('https://example.com/doc.xlsx', 'https://example.com', False, 'Point 1: Excel file extension'),
        
        # Point 2: Static/Media Subdomain Detection
        ('https://images.example.com/news/story', 'https://example.com', False, 'Point 2: Images subdomain'),
        ('https://cdn.example.com/article', 'https://example.com', False, 'Point 2: CDN subdomain'),
        ('https://static.example.com/news', 'https://example.com', False, 'Point 2: Static subdomain'),
        ('https://photos.example.com/gallery', 'https://example.com', False, 'Point 2: Photos subdomain'),
        
        # Point 3: Query Parameter Filtering
        ('https://example.com/news?print=true', 'https://example.com', False, 'Point 3: Print query param'),
        ('https://example.com/news?share=facebook', 'https://example.com', False, 'Point 3: Share query param'),
        ('https://example.com/news?action=edit', 'https://example.com', False, 'Point 3: Action query param'),
        ('https://example.com/news?format=pdf', 'https://example.com', False, 'Point 3: Format query param'),
        
        # Point 4: .gov Domain Special Logic
        ('https://cityofseattle.gov/city-news/article-title', 'https://cityofseattle.gov', True, 'Point 4: Gov news article (should pass)'),
        ('https://cityofseattle.gov/city-news/', 'https://cityofseattle.gov', False, 'Point 4: Gov news section (should fail)'),
        ('https://cityofseattle.gov/departments', 'https://cityofseattle.gov', False, 'Point 4: Gov department page (should fail)'),
        ('https://cityofseattle.gov/city-council', 'https://cityofseattle.gov', False, 'Point 4: Gov city council (should fail)'),
        
        # Point 5: Section Page vs Article Detection
        ('https://example.com/news', 'https://example.com', False, 'Point 5: News section page (should fail)'),
        ('https://example.com/news/article-title', 'https://example.com', True, 'Point 5: News article (should pass)'),
        ('https://example.com/sports', 'https://example.com', False, 'Point 5: Sports section (should fail)'),
        ('https://example.com/sports/team-wins-championship', 'https://example.com', True, 'Point 5: Sports article (should pass)'),
        
        # Point 6: Social Sharing URL Detection
        ('https://example.com/sharer/facebook', 'https://example.com', False, 'Point 6: Social sharer URL'),
        ('https://facebook.com/sharer', 'https://example.com', False, 'Point 6: Facebook sharer'),
        ('https://example.com/share?url=test', 'https://example.com', False, 'Point 6: Share URL pattern'),
        ('https://linkedin.com/sharing', 'https://example.com', False, 'Point 6: LinkedIn sharing'),
        
        # Point 7: Root/Homepage URL Filtering
        ('https://example.com/', 'https://example.com', False, 'Point 7: Homepage URL'),
        ('https://example.com/#section', 'https://example.com', False, 'Point 7: Hash-only URL'),
        ('https://example.com/?page=1', 'https://example.com', False, 'Point 7: Query-only URL'),
        
        # Point 8: Non-Article Path Patterns
        ('https://example.com/careers', 'https://example.com', False, 'Point 8: Careers page'),
        ('https://example.com/advertise', 'https://example.com', False, 'Point 8: Advertise page'),
        ('https://example.com/about', 'https://example.com', False, 'Point 8: About page'),
        ('https://example.com/privacy', 'https://example.com', False, 'Point 8: Privacy page'),
        ('https://example.com/contact', 'https://example.com', False, 'Point 8: Contact page'),
        
        # Valid articles that should pass all filters
        ('https://example.com/news/local-story-title', 'https://example.com', True, 'Valid: Local news article'),
        ('https://example.com/politics/election-results', 'https://example.com', True, 'Valid: Politics article'),
        ('https://example.com/business/company-merger', 'https://example.com', True, 'Valid: Business article'),
        ('https://cityofseattle.gov/city-news/budget-approved-2024', 'https://cityofseattle.gov', True, 'Valid: Gov news article'),
        
        # Special cases that should pass
        ('https://example.com/civicalerts.aspx?id=123', 'https://example.com', True, 'Special: CivicAlerts should pass'),
        ('https://campaign-archive.com/newsletter', 'https://example.com', True, 'Special: Campaign archive should pass'),
    ]
    
    print("🧪 Testing Enhanced URL Filtering (8 Points Implementation)")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    # Group tests by point
    current_point = ""
    
    for url, base_url, expected, description in test_cases:
        result = is_valid_article_url(url, base_url)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        
        # Extract point number for grouping
        point = description.split(':')[0]
        if point != current_point:
            current_point = point
            print(f"\n📋 {point}:")
        
        print(f"  {status} {description}")
        print(f"      URL: {url}")
        print(f"      Result: {result} (expected: {expected})")
        
        if result == expected:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Enhanced URL filtering is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Please review the implementation.")
        return False

if __name__ == "__main__":
    success = test_enhanced_filtering()
    sys.exit(0 if success else 1) 