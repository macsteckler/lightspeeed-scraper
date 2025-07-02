"""Content extraction module using Playwright and Readability."""
import re
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse, urlunparse, parse_qs
from playwright.async_api import async_playwright, Error as PlaywrightError
from readability import Document
from bs4 import BeautifulSoup

from headline_worker.modules.diffbot import fetch_via_diffbot, fetch_via_diffbot_async
from headline_worker.modules.url_utils import canonicalize_url, is_valid_article_url
from headline_worker.modules.date_extractor import extract_date_priority_system

logger = logging.getLogger(__name__)

def convert_to_markdown(html_content: str) -> str:
    """
    Convert HTML content to markdown format.
    Preserves basic structure while removing unnecessary HTML.
    """
    # Remove script and style elements
    html_content = re.sub(r'<script.*?</script>', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<style.*?</style>', '', html_content, flags=re.DOTALL)
    
    # Convert common HTML elements to markdown
    conversions = [
        (r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'## \1\n'),  # Headers to ##
        (r'<p[^>]*>(.*?)</p>', r'\1\n\n'),  # Paragraphs
        (r'<br[^>]*>', r'\n'),  # Line breaks
        (r'<li[^>]*>(.*?)</li>', r'* \1\n'),  # List items
        (r'<strong[^>]*>(.*?)</strong>', r'**\1**'),  # Bold
        (r'<b[^>]*>(.*?)</b>', r'**\1**'),  # Bold
        (r'<em[^>]*>(.*?)</em>', r'*\1*'),  # Italic
        (r'<i[^>]*>(.*?)</i>', r'*\1*'),  # Italic
        (r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1\n'),  # Quotes
    ]
    
    for pattern, replacement in conversions:
        html_content = re.sub(pattern, replacement, html_content, flags=re.DOTALL|re.IGNORECASE)
    
    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', '', html_content)
    
    # Clean up whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    text = text.strip()
    
    return text

def clean_html_for_ai(html_content: str) -> str:
    """
    Clean HTML content for AI analysis by removing headers, footers, navigation, ads, etc.
    Keep only the main article content.
    """
    # Remove script and style elements
    html_content = re.sub(r'<script.*?</script>', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<style.*?</style>', '', html_content, flags=re.DOTALL)
    
    # Remove common non-content elements
    patterns_to_remove = [
        r'<nav.*?</nav>',  # Navigation
        r'<header.*?</header>',  # Headers
        r'<footer.*?</footer>',  # Footers
        r'<aside.*?</aside>',  # Sidebars
        r'<div[^>]*class="[^"]*(?:ad|advertisement|banner|sidebar|footer|header|nav|menu|social|related|comment)[^"]*".*?</div>',  # Ad/nav divs
        r'<div[^>]*id="[^"]*(?:ad|advertisement|banner|sidebar|footer|header|nav|menu|social|related|comment)[^"]*".*?</div>',  # Ad/nav divs by ID
    ]
    
    for pattern in patterns_to_remove:
        html_content = re.sub(pattern, '', html_content, flags=re.DOTALL|re.IGNORECASE)
    
    # Clean up excessive whitespace
    html_content = re.sub(r'\n\s*\n\s*\n', '\n\n', html_content)
    html_content = html_content.strip()
    
    return html_content

async def extract_content_with_playwright(url: str) -> Dict[str, Any]:
    """
    Extract content from a URL using Playwright and Readability.
    
    Args:
        url: The URL to extract content from
        
    Returns:
        Dictionary with extracted title, text, markdown, metadata, clean_html and date
        
    Raises:
        RuntimeError: If content extraction fails
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(ignore_https_errors=True)  # Ignore SSL certificate errors
        page = await context.new_page()
        
        try:
            logger.info(f"Navigating to {url} with Playwright")
            await page.goto(url, timeout=3000)  # 3 second timeout
            
            # Extract metadata
            title = await page.title()
            metadata = {}
            
            # Extract all meta tags
            meta_elements = await page.query_selector_all('meta')
            for meta in meta_elements:
                name = await meta.get_attribute('name') 
                property = await meta.get_attribute('property')
                content = await meta.get_attribute('content')
                
                if content:
                    key = name or property
                    if key:
                        metadata[key] = content
            
            # Get HTML content for Readability and AI analysis
            html_content = await page.content()
            doc = Document(html_content)
            
            # Extract main content
            content = doc.summary()
            
            # Convert to both plain text and markdown
            text = re.sub('<[^<]+?>', ' ', content).strip()
            text = re.sub(r'\s+', ' ', text)
            
            markdown = convert_to_markdown(content)
            
            # Clean HTML for AI analysis (remove header/footer/nav elements)
            clean_html = clean_html_for_ai(content)
            
            await browser.close()
            
            # Use the new date extraction priority system
            extracted_date, extraction_method = await extract_date_priority_system(
                scraper_type="playwright",
                content=markdown,
                metadata=metadata,
                full_html=clean_html
            )
            
            logger.info(f"Date extraction method used: {extraction_method}")
            
            return {
                "title": title,
                "text": text,
                "markdown": markdown,
                "metadata": metadata,
                "clean_html": clean_html,
                "date": extracted_date.isoformat() if extracted_date else None,
                "scraper_type": "playwright",
                "date_extraction_method": extraction_method
            }
        except PlaywrightError as e:
            await browser.close()
            logger.warning(f"Playwright extraction failed for {url}: {str(e)}")
            raise RuntimeError(f"Playwright extraction failed: {str(e)}")
        except Exception as e:
            await browser.close()
            logger.warning(f"Content extraction failed for {url}: {str(e)}")
            raise RuntimeError(f"Content extraction failed: {str(e)}")

async def extract_content(url: str) -> Dict[str, Any]:
    """
    Extract content from a URL, with fallback to Diffbot.
    
    Args:
        url: The URL to extract content from
        
    Returns:
        Dictionary with extracted title, text, markdown, metadata, clean_html and date
        
    Raises:
        RuntimeError: If content extraction fails with both methods
    """
    try:
        return await extract_content_with_playwright(url)
    except Exception as e:
        logger.info(f"Falling back to Diffbot for {url}")
        try:
            diffbot_data = await fetch_via_diffbot_async(url)
            
            # Convert Diffbot's HTML to markdown
            html_content = diffbot_data.get("html", "")
            markdown = convert_to_markdown(html_content)
            
            # Convert to plain text
            text = re.sub('<[^<]+?>', ' ', html_content).strip()
            text = re.sub(r'\s+', ' ', text)
            
            # Clean HTML for AI analysis
            clean_html = clean_html_for_ai(html_content)
            
            # Use the new date extraction priority system for Diffbot
            extracted_date, extraction_method = await extract_date_priority_system(
                scraper_type="diffbot",
                diffbot_data=diffbot_data,
                content=markdown,
                metadata=diffbot_data.get("meta", {}),
                full_html=clean_html
            )
            
            logger.info(f"Date extraction method used: {extraction_method}")
            
            return {
                "title": diffbot_data.get("title"),
                "text": text,
                "markdown": markdown,
                "metadata": diffbot_data.get("meta", {}),
                "clean_html": clean_html,
                "date": extracted_date.isoformat() if extracted_date else None,
                "scraper_type": "diffbot",
                "date_extraction_method": extraction_method
            }
        except Exception as diffbot_error:
            logger.error(f"Both extraction methods failed for {url}: {str(e)}, Diffbot: {str(diffbot_error)}")
            raise RuntimeError(f"Content extraction failed with both methods: {str(diffbot_error)}")

def canonicalize_url(url: str) -> str:
    """Canonicalize a URL by normalizing various components."""
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

def is_meaningful_content(content: Dict[str, Any], url: str) -> bool:
    """
    Check if content should be processed based on URL patterns only.
    Rely on AI classification for content quality decisions.
    
    Args:
        content: Extracted content dictionary
        url: The source URL
        
    Returns:
        True if content should be sent to AI classification, False for obvious non-news URLs
    """
    # Use enhanced URL validation from url_utils
    from headline_worker.modules.url_utils import is_valid_article_url
    
    # For content filtering, we create a dummy base_url from the url itself
    # since we're checking if this single URL should be processed
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Use the enhanced URL validation logic
        if not is_valid_article_url(url, base_url):
            logger.debug(f"URL filtered by enhanced validation: {url}")
            return False
            
    except Exception as e:
        logger.debug(f"Error in enhanced URL validation for {url}: {str(e)}")
        # Fall back to basic filtering if enhanced validation fails
        pass
    
    # Only filter out obvious non-news URL patterns that are never articles
    url_lower = url.lower()
    
    # Domain-level filtering for obvious non-news sites
    from urllib.parse import urlparse
    domain = urlparse(url_lower).netloc.replace('www.', '')
    
    non_news_domains = [
        'apps.apple.com', 'play.google.com', 'chrome.google.com',
        'itunes.apple.com', 'music.apple.com',
        'github.com', 'gitlab.com', 'bitbucket.org',
        'linkedin.com', 'instagram.com', 'pinterest.com',
        'youtube.com', 'youtu.be', 'vimeo.com',
        'amazon.com', 'ebay.com', 'etsy.com',
        'wikipedia.org', 'wikimedia.org'
    ]
    
    if any(domain.endswith(non_domain) or domain == non_domain for non_domain in non_news_domains):
        logger.debug(f"Domain matches obvious non-news site: {domain}")
        return False
    
    # URL path patterns for obvious non-news content and RSS feeds
    non_news_patterns = [
        '/privacy-policy', '/privacy', '/terms-of-service', '/terms', 
        '/contact-us', '/contact', '/about-us', '/about',
        '/advertise-with-us', '/advertise',
        '/sitemap', '/robots.txt', '.xml', '.json',
        '/feed', '/rss', '/feeds/', '.rss', '.atom',  # RSS/Atom feeds
        '/api/', '/wp-json/', '/xmlrpc.php'  # API endpoints
    ]
    
    if any(pattern in url_lower for pattern in non_news_patterns):
        logger.debug(f"URL matches obvious non-news pattern (including feeds): {url}")
        return False
    
    # Everything else goes to AI classification - let AI decide what's news
    logger.debug(f"Content will be sent to extraction and AI classification: {url}")
    return True 