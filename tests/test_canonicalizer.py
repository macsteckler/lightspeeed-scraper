"""Tests for URL canonicalizer."""
import pytest
from headline_worker.modules.content_extractor import canonicalize_url

def test_canonicalize_url():
    """Test URL canonicalization."""
    # Test basic canonicalization
    assert canonicalize_url("http://example.com") == "http://example.com"
    
    # Test scheme lowercasing
    assert canonicalize_url("HTTP://example.com") == "http://example.com"
    
    # Test host lowercasing
    assert canonicalize_url("http://EXAMPLE.com") == "http://example.com"
    
    # Test www stripping
    assert canonicalize_url("http://www.example.com") == "http://example.com"
    
    # Test trailing slash removal
    assert canonicalize_url("http://example.com/") == "http://example.com"
    
    # Test path preservation
    assert canonicalize_url("http://example.com/path/to/page") == "http://example.com/path/to/page"
    
    # Test tracking params removal
    assert canonicalize_url("http://example.com?utm_source=test") == "http://example.com"
    
    # Test regular params preservation
    assert canonicalize_url("http://example.com?id=123") == "http://example.com?id=123"
    
    # Test fragment removal
    assert canonicalize_url("http://example.com#section") == "http://example.com"
    
    # Test combined case
    assert canonicalize_url("HTTP://WWW.EXAMPLE.COM/page/?utm_source=test#section") == "http://example.com/page" 