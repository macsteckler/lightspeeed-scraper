"""Content extraction module using Playwright and Readability."""
import logging
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import re
from urllib.parse import urlparse, urlunparse, parse_qs
from playwright.async_api import async_playwright, Error as PlaywrightError
from readability import Document

from headline_worker.modules.diffbot import fetch_via_diffbot, fetch_via_diffbot_async
from headline_worker.modules.url_utils import canonicalize_url

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

async def extract_content_with_playwright(url: str) -> Dict[str, Any]:
    """
    Extract content from a URL using Playwright and Readability.
    
    Args:
        url: The URL to extract content from
        
    Returns:
        Dictionary with extracted title, text, markdown, metadata and date
        
    Raises:
        RuntimeError: If content extraction fails
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
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
            
            # Try to find publication date
            date_posted = None
            for date_selector in [
                'meta[property="article:published_time"]',
                'meta[property="og:published_time"]',
                'time[datetime]',
                'meta[name="date"]',
                'meta[name="pubdate"]'
            ]:
                try:
                    date_element = await page.query_selector(date_selector)
                    if date_element:
                        if date_selector.startswith('meta'):
                            date_str = await date_element.get_attribute('content')
                        else:
                            date_str = await date_element.get_attribute('datetime')
                            
                        if date_str:
                            try:
                                date_posted = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                break
                            except ValueError:
                                pass
                except Exception as e:
                    logger.debug(f"Error extracting date: {str(e)}")
            
            # Get HTML content for Readability
            html_content = await page.content()
            doc = Document(html_content)
            
            # Extract main content
            content = doc.summary()
            
            # Convert to both plain text and markdown
            text = re.sub('<[^<]+?>', ' ', content).strip()
            text = re.sub(r'\s+', ' ', text)
            
            markdown = convert_to_markdown(content)
            
            await browser.close()
            
            return {
                "title": title,
                "text": text,
                "markdown": markdown,
                "metadata": metadata,
                "date": date_posted.isoformat() if date_posted else None
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
        Dictionary with extracted title, text, markdown, metadata and date
        
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
            markdown = convert_to_markdown(diffbot_data.get("html", ""))
            
            return {
                "title": diffbot_data.get("title"),
                "text": diffbot_data.get("text"),
                "markdown": markdown,
                "metadata": diffbot_data.get("meta", {}),
                "date": diffbot_data.get("date")
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