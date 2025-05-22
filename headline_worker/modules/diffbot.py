"""Diffbot API client for the headline content scraper."""
import logging
import itertools
import time
import requests
from typing import Dict, Any, Optional
import asyncio
import aiohttp

import config
from headline_worker.metrics import DIFFBOT_REQUESTS, DIFFBOT_RATE_LIMITS
from headline_worker.modules.link_collector import diffbot_key_manager

logger = logging.getLogger(__name__)

async def fetch_via_diffbot_async(url: str) -> Dict[str, Any]:
    """
    Fetch article data via Diffbot API using async.
    
    Args:
        url: The URL to fetch
        
    Returns:
        The article data from Diffbot
        
    Raises:
        RuntimeError: If the request fails
    """
    # Get a key from the key manager (respects rate limits)
    token = await diffbot_key_manager.get_key()
    
    try:
        DIFFBOT_REQUESTS.inc()
        logger.info(f"Fetching {url} via Diffbot (key: {token[:5]}...)")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.diffbot.com/v3/article",
                params={"token": token, "url": url},
                timeout=15
            ) as resp:
                if resp.status == 429:  # quota exceeded
                    logger.warning(f"Diffbot key {token[:5]}... quota exceeded")
                    DIFFBOT_RATE_LIMITS.inc()
                    raise RuntimeError(f"Diffbot key {token[:5]}... quota exceeded")
                    
                if resp.status == 403:  # forbidden
                    logger.warning(f"Diffbot key {token[:5]}... forbidden")
                    raise RuntimeError(f"Diffbot key {token[:5]}... forbidden")
                    
                if resp.status != 200:
                    raise RuntimeError(f"Diffbot returned status {resp.status}")
                
                data = await resp.json()
                
                if data.get("objects"):
                    return data["objects"][0]  # title, text, date
                    
                logger.warning(f"Diffbot returned no objects for {url}")
                raise RuntimeError(f"Diffbot returned no objects for {url}")
    except asyncio.TimeoutError:
        logger.warning(f"Diffbot request timed out for {url}")
        raise RuntimeError(f"Diffbot request timed out for {url}")
    except Exception as e:
        logger.warning(f"Diffbot request failed for {url}: {str(e)}")
        raise RuntimeError(f"Diffbot request failed: {str(e)}")

def fetch_via_diffbot(url: str) -> Dict[str, Any]:
    """
    Synchronous wrapper around async Diffbot fetching.
    Maintains backwards compatibility with existing code.
    
    Args:
        url: The URL to fetch
        
    Returns:
        The article data from Diffbot
    """
    return asyncio.run(fetch_via_diffbot_async(url)) 