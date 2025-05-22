"""URL utilities for the headline worker."""
import re
from urllib.parse import urlparse, parse_qs, urlunparse

# Constants for URL filtering
NON_CONTENT_EXTENSIONS = re.compile(r'\.(jpg|jpeg|png|gif|svg|webp|css|js|pdf|zip|doc|docx|xls|xlsx|ppt|pptx|mp3|mp4|wav|avi|mov|wmv)$', re.IGNORECASE)
SOCIAL_HOSTS = re.compile(r'(facebook\.com|twitter\.com|instagram\.com|linkedin\.com|youtube\.com|tiktok\.com|pinterest\.com)', re.IGNORECASE)

def canonicalize_url(url: str) -> str:
    """
    Canonicalize a URL by normalizing various components.
    
    Args:
        url: The URL to canonicalize
        
    Returns:
        The canonicalized URL
    """
    # Parse URL
    parsed = urlparse(url)
    
    # Convert scheme and netloc to lowercase
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    # Remove www.
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    
    # Parse query parameters
    query_params = parse_qs(parsed.query)
    
    # Remove tracking parameters (common ones)
    tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 
                      'fbclid', 'gclid', '_ga', 'ref', 'source'}
    query_params = {k: v for k, v in query_params.items() if k.lower() not in tracking_params}
    
    # Rebuild query string
    query_items = []
    for key in sorted(query_params.keys()):  # Sort for consistency
        for value in sorted(query_params[key]):  # Sort values too
            query_items.append(f"{key}={value}")
    query = '&'.join(query_items)
    
    # Remove fragment
    fragment = ''
    
    # Remove trailing slash from path
    path = parsed.path.rstrip('/')
    if not path:
        path = '/'
    
    # Rebuild URL
    canonical = urlunparse((scheme, netloc, path, '', query, fragment))
    return canonical

def is_valid_article_url(url: str, base_url: str) -> bool:
    """
    Check if a URL is likely to be a valid article URL.
    
    Args:
        url: The URL to check
        base_url: The base URL of the source
        
    Returns:
        bool: True if the URL is likely an article, False otherwise
    """
    # Skip URLs that don't start with http:// or https://
    if not url.startswith(('http://', 'https://')):
        return False
        
    # Skip URLs with non-content extensions
    if NON_CONTENT_EXTENSIONS.search(url):
        return False
        
    # Skip social media links
    if SOCIAL_HOSTS.search(url):
        return False
        
    # Skip URLs that don't belong to the same domain
    # Extract domain from base_url
    try:
        base_domain = re.search(r'https?://([^/]+)', base_url).group(1)
        url_domain = re.search(r'https?://([^/]+)', url).group(1)
        
        # Strip www. prefix for comparison
        base_domain = base_domain.replace('www.', '')
        url_domain = url_domain.replace('www.', '')
        
        # Check if it's the same domain or a subdomain
        if not (url_domain == base_domain or url_domain.endswith('.' + base_domain)):
            # But allow common CDN domains that news sites might use
            common_cdn_patterns = ['cdn.', 'media.', 'assets.', 'img.', 'images.']
            is_cdn = any(cdn in url_domain for cdn in common_cdn_patterns)
            if not is_cdn:
                return False
    except:
        # If we can't parse the domain, consider it invalid
        return False
    
    # Return true for everything else
    return True 