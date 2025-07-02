"""URL utilities for the headline worker."""
import re
from urllib.parse import urlparse, parse_qs, urlunparse

# Enhanced file extension filtering (Point 1)
NON_CONTENT_EXTENSIONS = re.compile(r'\.(jpg|jpeg|png|gif|bmp|webp|svg|ico|tiff|mp4|avi|mov|wmv|flv|mkv|m4v|webm|mp3|wav|ogg|m4a|aac|css|js|json|xml|rss|pdf|zip|rar|doc|docx|xls|xlsx|ppt|pptx)$', re.IGNORECASE)

# Enhanced social hosts patterns (Point 6)
SOCIAL_HOSTS = re.compile(r'(facebook\.com|twitter\.com|instagram\.com|linkedin\.com|youtube\.com|tiktok\.com|pinterest\.com)', re.IGNORECASE)

# Static/Media subdomain patterns (Point 2)
STATIC_MEDIA_PATTERNS = [
    'images.', 'img.', 'cdn.', 'static.', 'image.',
    'media.', 'assets.', 'videos.', 'video.',
    'pics.', 'photos.', 'thumbs.', 'thumbnail.',
    'mcdn.', 'lura.live', 'cloudfront.net',
    'akamai.net', 'fastly.net', 'cloudinary.com',
    'foxtv.', 'q13fox.'
]

# Query parameter filtering (Point 3)
SKIP_QUERY_PARAMS = [
    'print=', 'share=', 'format=', 'output=',
    'view=', 'action=', 'filter=', 'sort=',
    'search=', 'query=', 'page=', 'ref='
]

# Social sharing URL patterns (Point 6)
SOCIAL_SHARING_PATTERNS = [
    '/sharer/', '/share?', 'share-offsite', 
    '/facebook', '/twitter', '/linkedin', '/pinterest', '/youtube',
    'linkedin.com/sharing', 'facebook.com/sharer',
    'twitter.com/share', 'pinterest.com/pin'
]

# Section page paths (Point 5)
SECTION_PATHS = [
    '/live', '/news', '/sports', '/weather', '/shows',
    '/about', '/contact', '/search', '/tag', '/category'
]

# Government site skip paths (Point 4)
GOV_SKIP_PATHS = [
    '/city-government', '/departments', '/services',
    '/business', '/community', '/recreation',
    '/permits', '/utilities', '/transportation',
    '/city-council', '/mayor', '/administration',
    '/planning', '/development', '/police', '/video',
    '/fire', '/parks', '/library', '/MyAccount', '/MyAccount.aspx', '/Business', '/Business.aspx', '/Our-Community', '/Our-Community.aspx',
    '/municipal', '/public-works',
    '/discover', '/city-news$', # Only skip the main news page
    '/resident-resources', '/newcomers-guide',
    '/about', '/contact', '/faqs',
    '/meetings', '/events', '/calendar'
]

# Non-article path patterns (Point 8)
NON_ARTICLE_PATHS = [
    # Common non-article paths
    '/search', '/tag', '/category', '/author', '/about', '/contact', '/privacy', '/terms', '/login', '/register', '/welcome',
    '/contact', '/privacy', '/terms', '/login', '/register', '/public-safety', '/public-safety.aspx', '/public-safety.html', '/public-safety.php', '/public-safety.asp',
    '/subscribe', '/wp-admin', '/wp-includes', '/cdn-cgi', '#main-content', '/emergency-preparedness',
    '/static', '/media', '/images', '/css', '/js', '/fonts', '/doing-business',
    '/assets', '/weather', '/traffic', '/contests', '/apps',
    '/advertise', '/careers', '/jobs', '/staff', '/newsletters',
    '/subscribe', '/subscription', '/help', '/faq', '/support','/welcome',
    '/calendar', '/events', '/directory', '/classified', '/person', '/winning-question', 
    '/marketplace', '/shop', '/donate', '/giving', '/sponsors',
    '/discover', '/development-pipeline', '/development', '/team',
    '/pipeline', '/projects', '/construction', '/future-projects', '/links-you-saw-on-tv', '/ProfileCreate', '/ProfileCreate.aspx', '/ProfileEdit', '/ProfileEdit.aspx', '/ProfileView', '/ProfileView.aspx',
    # Adding administrative page patterns
    '/eeo-report', '/public-file', '/closed-captioning', '/Business', '/Business.aspx', '/Our-Community', '/Our-Community.aspx', '/City-Services',
    '/fcc-applications', '/fcc-public-file', '/advertise-with-us',
    '/station-info', '/corporate-info', '/legal', '/accessibility-statement'
]

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
    Enhanced URL validation with comprehensive filtering based on JS patterns.
    
    Args:
        url: The URL to check
        base_url: The base URL of the source
        
    Returns:
        bool: True if the URL is likely an article, False otherwise
    """
    # Skip URLs that don't start with http:// or https://
    if not url.startswith(('http://', 'https://')):
        return False
    
    try:
        parsed_url = urlparse(url)
        path = parsed_url.path.lower()
        hostname = parsed_url.netloc.lower()
        full_url = url.lower()
        
        # Point 7: Root/Homepage URL filtering
        if path == '/' or path == '' or '#' in url:
            return False
        
        # Point 7: Skip URLs with only query parameters and no path
        if path == '/' and parsed_url.query:
            return False
        
        # Point 1: Enhanced file extension filtering
        if NON_CONTENT_EXTENSIONS.search(url):
            return False
        
        # Point 2: Static/Media subdomain detection
        if any(pattern in hostname for pattern in STATIC_MEDIA_PATTERNS):
            return False
        
        # Point 3: Query parameter filtering
        if any(param in parsed_url.query for param in SKIP_QUERY_PARAMS):
            return False
        
        # Point 6: Social sharing URL detection
        if any(pattern in full_url for pattern in SOCIAL_SHARING_PATTERNS):
            return False
        
        # Point 6: Social media hosts
        if SOCIAL_HOSTS.search(url):
            return False
        
        # Point 5: Section page vs article detection
        if any(path == section for section in SECTION_PATHS):
            return False
        
        # Point 4: .gov domain special logic
        if '.gov' in hostname:
            # Allow news articles from city-news directory with additional path segments
            if path.startswith('/city-news/'):
                path_segments = path.split('/')[1:]  # Remove empty first element
                # Allow if it's an actual article (has more than just /city-news/)
                # Reject if it's just "/city-news/" (ends with slash and no content after)
                if len(path_segments) > 1 and path_segments[1] and '?' not in path:
                    # This is likely an article, continue with other checks
                    pass
                else:
                    return False
            else:
                # Check for common navigation page patterns
                if (path == '/' or 
                    path.endswith('/home') or 
                    path.endswith('/index') or
                    any(skip_path.endswith('$') and path == skip_path[:-1] or 
                        not skip_path.endswith('$') and path.startswith(skip_path) 
                        for skip_path in GOV_SKIP_PATHS)):
                    return False
        
        # Point 8: Non-article path patterns
        for pattern in NON_ARTICLE_PATHS:
            if path == pattern or path.startswith(pattern + '/'):
                return False
        
        # Domain validation (existing logic)
        try:
            base_domain = re.search(r'https?://([^/]+)', base_url).group(1)
            url_domain = re.search(r'https?://([^/]+)', url).group(1)
            
            # Strip www. prefix for comparison
            base_domain = base_domain.replace('www.', '')
            url_domain = url_domain.replace('www.', '')
            
            # Check if it's the same domain or a subdomain
            if not (url_domain == base_domain or url_domain.endswith('.' + base_domain)):
                # Enhanced CDN patterns (Point 2)
                enhanced_cdn_patterns = STATIC_MEDIA_PATTERNS + ['cdn.', 'media.', 'assets.', 'img.', 'images.']
                is_cdn = any(cdn in url_domain for cdn in enhanced_cdn_patterns)
                if not is_cdn:
                    return False
        except:
            # If we can't parse the domain, consider it invalid
            return False
        
        # Special cases: Always allow certain patterns
        if 'civicalerts.aspx' in path or 'campaign-archive.com' in hostname:
            return True
        
        return True
        
    except Exception:
        # If URL parsing fails, consider it invalid
        return False 