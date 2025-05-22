"""Link collector module for source pages."""
import logging
import re
import asyncio
import aiohttp
import random
import time
from datetime import datetime, timedelta
from typing import List, Set
from urllib.parse import urljoin, quote_plus
from playwright.async_api import async_playwright, Error as PlaywrightError

import config
from headline_worker.modules.url_utils import canonicalize_url, is_valid_article_url, NON_CONTENT_EXTENSIONS, SOCIAL_HOSTS

logger = logging.getLogger(__name__)

class DiffbotKeyManager:
    """
    Smart Diffbot API key manager that tracks usage and respects rate limits.
    
    Diffbot has a limit of 5 calls per minute per key, so this manager 
    tracks usage and ensures keys are not overused.
    """
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        """Singleton pattern to ensure only one key manager exists"""
        if cls._instance is None:
            cls._instance = super(DiffbotKeyManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    async def __init_if_needed(self):
        """Initialize the manager if needed (with lock to ensure thread safety)"""
        if self._initialized:
            return
            
        async with self._lock:
            if self._initialized:  # Double-check inside lock
                return
                
            logger.info(f"Initializing Diffbot key manager with {len(config.DIFFBOT_KEYS)} keys")
            self.keys = config.DIFFBOT_KEYS.copy()
            # Initialize usage tracking - a list of timestamps for each key
            self.usage = {key: [] for key in self.keys}
            self._initialized = True
    
    async def get_key(self):
        """
        Get an available key that respects rate limits.
        
        Returns:
            A Diffbot API key that has capacity for a new request.
        
        Raises:
            RuntimeError: If no keys are available within rate limits.
        """
        await self.__init_if_needed()
        
        async with self._lock:
            now = datetime.now()
            one_minute_ago = now - timedelta(minutes=1)
            
            # Update all key usage lists to remove entries older than 1 minute
            for key in self.keys:
                self.usage[key] = [t for t in self.usage[key] if t > one_minute_ago]
            
            # Find keys with fewer than 5 calls in the last minute
            available_keys = [
                key for key in self.keys 
                if len(self.usage[key]) < 5
            ]
            
            if not available_keys:
                # Calculate the earliest time a key will be available
                earliest_available = now
                for key in self.keys:
                    if self.usage[key]:  # If key has been used
                        earliest = min(self.usage[key]) + timedelta(minutes=1)
                        if earliest < earliest_available:
                            earliest_available = earliest
                
                wait_seconds = (earliest_available - now).total_seconds()
                if wait_seconds > 0:
                    logger.warning(f"All Diffbot keys at rate limit, waiting {wait_seconds:.1f} seconds for a key to become available")
                    # Release the lock during waiting
                    await asyncio.sleep(wait_seconds)
                    # Try again after waiting
                    return await self.get_key()
                
            # Sort available keys by usage count (least used first)
            available_keys.sort(key=lambda k: len(self.usage[k]))
            
            # Select one of the least used keys (randomly from keys with the same usage count)
            least_usage = len(self.usage[available_keys[0]])
            least_used_keys = [k for k in available_keys if len(self.usage[k]) == least_usage]
            selected_key = random.choice(least_used_keys)
            
            # Record this usage
            self.usage[selected_key].append(now)
            
            logger.debug(f"Selected Diffbot key with {len(self.usage[selected_key])} recent uses")
            return selected_key
    
    async def record_usage(self, key):
        """Record usage of a key"""
        await self.__init_if_needed()
        
        async with self._lock:
            self.usage[key].append(datetime.now())

# Global Diffbot key manager instance
diffbot_key_manager = DiffbotKeyManager()

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

async def collect_links_with_diffbot(url: str, limit: int = 100) -> List[str]:
    """
    Collect links using Diffbot's List API.
    
    Args:
        url: The URL of the source page
        limit: Maximum number of links to collect
        
    Returns:
        List of unique, canonicalized links
    """
    logger.info(f"Collecting links from {url} using Diffbot")
    
    if not config.DIFFBOT_KEYS:
        raise RuntimeError("No Diffbot API keys configured")
    
    # Get a key respecting rate limits
    api_key = await diffbot_key_manager.get_key()
    
    try:
        # Set up the API request
        base_url = "https://api.diffbot.com/v3/list"
        params = {
            "token": api_key,
            "url": url
        }
        
        logger.info(f"Collecting links from {url} using Diffbot List API")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params, timeout=30) as response:
                if response.status != 200:
                    logger.error(f"Diffbot API error: {response.status} - {await response.text()}")
                    raise RuntimeError(f"Failed to collect links: Diffbot API returned status {response.status}")
                
                data = await response.json()
                
                # Log the response for debugging
                logger.debug(f"Diffbot response: {data}")
                
                if not data.get("objects"):
                    logger.warning(f"No objects found in Diffbot response for {url}")
                    return []
                
                # Extract links from the response
                links = []
                for item in data.get("objects", []):
                    link = item.get("link")
                    if link and is_valid_article_url(link, url):
                        canonical_link = canonicalize_url(link)
                        if canonical_link not in links:
                            links.append(canonical_link)
                            logger.debug(f"Added link from Diffbot: {canonical_link}")
                
                # Look for pagination links
                if data.get("nextPages"):
                    for next_link in data.get("nextPages"):
                        if len(links) >= limit:
                            break
                        if next_link and is_valid_article_url(next_link, url):
                            canonical_link = canonicalize_url(next_link)
                            if canonical_link not in links:
                                links.append(canonical_link)
                                logger.debug(f"Added pagination link from Diffbot: {canonical_link}")
                
                logger.info(f"Found {len(links)} links using Diffbot")
                return links[:limit]  # Respect the link limit
    
    except Exception as e:
        logger.error(f"Error collecting links with Diffbot: {str(e)}")
        raise RuntimeError(f"Failed to collect links with Diffbot: {str(e)}")

async def collect_links_with_playwright(url: str, limit: int = 100) -> List[str]:
    """
    Collect links using Playwright.
    
    Args:
        url: The URL of the source page
        limit: Maximum number of links to collect
        
    Returns:
        List of unique, canonicalized links
        
    Raises:
        RuntimeError: If link collection fails
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        try:
            logger.info(f"Collecting links from {url} using Playwright")
            await page.goto(url, timeout=10000)  # 10 second timeout
            
            # Collect links from a elements
            link_elements = await page.query_selector_all('a[href]')
            raw_links = []
            
            for link_element in link_elements:
                href = await link_element.get_attribute('href')
                if href:
                    # Convert to absolute URL
                    abs_url = urljoin(url, href)
                    raw_links.append(abs_url)
            
            # Also check for og:url meta tags
            og_url_elements = await page.query_selector_all('meta[property="og:url"]')
            for og_element in og_url_elements:
                og_url = await og_element.get_attribute('content')
                if og_url:
                    raw_links.append(og_url)
            
            await browser.close()
            
            # Process and filter links
            processed_links = set()
            
            for link in raw_links:
                try:
                    # Skip invalid URLs
                    if not link or not link.startswith(('http://', 'https://')):
                        continue
                    
                    # Skip non-content URLs
                    if NON_CONTENT_EXTENSIONS.search(link) or SOCIAL_HOSTS.search(link):
                        continue
                    
                    # Canonicalize the URL
                    canonical_link = canonicalize_url(link)
                    processed_links.add(canonical_link)
                    
                    # Stop if we've reached the limit
                    if len(processed_links) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Error processing link {link}: {str(e)}")
            
            return list(processed_links)
            
        except Exception as e:
            await browser.close()
            raise e

async def collect_links(url: str, limit: int = 100) -> List[str]:
    """
    Collect links from a page using either Playwright or Diffbot.
    
    Args:
        url: URL to collect links from
        limit: Maximum number of links to collect
        
    Returns:
        list: List of links
        
    Raises:
        RuntimeError: If failed to collect links with both methods
    """
    links = []
    
    # Try with Playwright first - it's cheaper but sometimes fails
    try:
        logger.info(f"Attempting to collect links from {url} using Playwright")
        links = await collect_links_with_playwright(url, limit=limit)
        logger.info(f"Successfully collected {len(links)} links with Playwright")
        return links
    except Exception as e:
        logger.warning(f"Failed to collect links with Playwright: {str(e)}")
    
    # Fall back to Diffbot if Playwright failed
    try:
        logger.info(f"Falling back to Diffbot for {url}")
        links = await collect_links_with_diffbot(url, limit=limit)
        logger.info(f"Successfully collected {len(links)} links with Diffbot")
        return links
    except Exception as e:
        logger.error(f"Failed to collect links with Diffbot: {str(e)}")
        
    # If we get here, both methods failed
    if not links:
        error_msg = f"Failed to collect any links from {url} with both Playwright and Diffbot"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
        
    return links 