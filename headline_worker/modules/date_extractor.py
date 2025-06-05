"""Date extraction module with priority hierarchy for different scraper types."""
import logging
import json
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import openai
import traceback
from dateutil import parser

import config

logger = logging.getLogger(__name__)

def parse_diffbot_date(date_str: str) -> Optional[datetime]:
    """
    Parse Diffbot's date format: "Thu, 29 May 2025 11:15:17 GMT"
    
    Args:
        date_str: Date string from Diffbot API
        
    Returns:
        Parsed datetime object or None if parsing fails
    """
    try:
        # Handle Diffbot's specific GMT format
        if date_str:
            # Use dateutil parser which is more flexible
            parsed_date = parser.parse(date_str)
            
            # Validate date is reasonable (not too far in future or past)
            now = datetime.now(parsed_date.tzinfo if parsed_date.tzinfo else None)
            
            # Allow dates up to 1 day in future (for timezone differences)
            max_future = now + timedelta(days=1)
            # Allow dates up to 10 years in past
            min_past = now - timedelta(days=3650)
            
            if min_past <= parsed_date <= max_future:
                return parsed_date
            else:
                logger.warning(f"Date {parsed_date} is outside reasonable range")
                return None
                
    except Exception as e:
        logger.warning(f"Failed to parse Diffbot date '{date_str}': {str(e)}")
        return None

def extract_date_from_metadata(metadata: Dict[str, Any]) -> Optional[datetime]:
    """
    Extract date from metadata using algorithmic approach.
    
    Args:
        metadata: Metadata dictionary from scraping
        
    Returns:
        Parsed datetime object or None if not found
    """
    # Common date fields to check in order of preference
    date_fields = [
        'article:published_time',
        'og:published_time', 
        'date',
        'pubdate',
        'published',
        'publication_date',
        'datePublished',
        'article:modified_time',
        'og:updated_time',
        'last-modified',
        'modified'
    ]
    
    for field in date_fields:
        if field in metadata and metadata[field]:
            try:
                parsed_date = parser.parse(metadata[field])
                
                # Validate date is reasonable
                now = datetime.now(parsed_date.tzinfo if parsed_date.tzinfo else None)
                max_future = now + timedelta(days=1)
                min_past = now - timedelta(days=3650)
                
                if min_past <= parsed_date <= max_future:
                    logger.info(f"Extracted date from metadata field '{field}': {parsed_date}")
                    return parsed_date
                    
            except Exception as e:
                logger.debug(f"Failed to parse date from metadata field '{field}': {str(e)}")
                continue
    
    return None

async def extract_date_with_ai(content: str, metadata: Dict[str, Any], full_html: str = None) -> Optional[str]:
    """
    Extract date using AI analysis of content and metadata.
    
    Args:
        content: Article content (markdown)
        metadata: Article metadata
        full_html: Full HTML content of the article (clean, no header/footer)
        
    Returns:
        Date string as found in content or None if not found
    """
    try:
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        
        # Format metadata as string
        metadata_str = "\n".join(f"{k}: {v}" for k, v in metadata.items())
        
        # Prepare content for AI analysis - use HTML if available, otherwise markdown
        content_for_analysis = full_html if full_html else content
        # Limit content size to avoid token limits
        content_for_analysis = content_for_analysis[:8000]
        
        prompt = f"""Extract the publication date from this news article. Look for the exact date when this article was published.

METADATA:
{metadata_str}

ARTICLE CONTENT:
{content_for_analysis}

INSTRUCTIONS:
1. First check the metadata for date fields like 'date', 'article:published_time', 'pubdate', etc.
2. If not in metadata, search the article content for publication date indicators:
   - Look in bylines (author lines) for dates
   - Look for "Published on", "Posted on", "Date:", etc.
   - Look for timestamps near the article title or author
   - Check for relative dates like "2 hours ago", "yesterday" and convert them
   - Look for datelines at the start of articles (city, date format)
3. Prioritize publication dates over event dates mentioned in the article
4. If you find multiple dates, choose the one that appears to be the publication date

Return ONLY the date string exactly as you find it in the content. Do not reformat it.
If no publication date can be found after thorough search, return "Date not found".

Examples of good responses:
- "June 15, 2024"
- "2024-06-15T10:30:00Z"
- "Published: Dec 1, 2023"
- "Date not found"

Date found:"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert at extracting publication dates from news articles. You analyze both metadata and content to find when an article was published."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=100
        )
        
        result = response.choices[0].message.content.strip()
        logger.debug(f"AI date extraction result: {result}")
        
        if result == "Date not found" or not result:
            return None
            
        return result
        
    except Exception as e:
        logger.error(f"AI date extraction failed: {str(e)}")
        return None

def parse_ai_extracted_date(date_str: str) -> Optional[datetime]:
    """
    Parse date string extracted by AI into datetime object.
    
    Args:
        date_str: Date string from AI extraction
        
    Returns:
        Parsed datetime object or None if parsing fails
    """
    try:
        # Clean up the date string
        date_str = date_str.strip()
        
        # Handle relative dates like "2 hours ago", "yesterday"
        now = datetime.now()
        lower_str = date_str.lower()
        
        if "hour" in lower_str and "ago" in lower_str:
            # Extract hours from "2 hours ago"
            hours_match = re.search(r'(\d+)\s*hours?\s*ago', lower_str)
            if hours_match:
                hours = int(hours_match.group(1))
                return now - timedelta(hours=hours)
                
        elif "day" in lower_str and "ago" in lower_str:
            # Extract days from "2 days ago"
            days_match = re.search(r'(\d+)\s*days?\s*ago', lower_str)
            if days_match:
                days = int(days_match.group(1))
                return now - timedelta(days=days)
                
        elif "yesterday" in lower_str:
            return now - timedelta(days=1)
            
        elif "today" in lower_str:
            return now.replace(hour=12, minute=0, second=0, microsecond=0)
        
        # Try to parse with dateutil
        parsed_date = parser.parse(date_str, fuzzy=True)
        
        # Validate date is reasonable
        max_future = now + timedelta(days=1)
        min_past = now - timedelta(days=3650)
        
        if min_past <= parsed_date <= max_future:
            return parsed_date
        else:
            logger.warning(f"AI extracted date {parsed_date} is outside reasonable range")
            return None
            
    except Exception as e:
        logger.warning(f"Failed to parse AI extracted date '{date_str}': {str(e)}")
        return None

async def extract_date_priority_system(
    scraper_type: str,
    diffbot_data: Dict[str, Any] = None,
    content: str = None,
    metadata: Dict[str, Any] = None,
    full_html: str = None
) -> Tuple[Optional[datetime], str]:
    """
    Extract date using priority system based on scraper type.
    
    Args:
        scraper_type: "diffbot" or "playwright"
        diffbot_data: Data from Diffbot API (if using Diffbot)
        content: Article content in markdown
        metadata: Article metadata
        full_html: Clean HTML content (no header/footer)
        
    Returns:
        Tuple of (datetime object, method used) or (None, "failed")
    """
    
    if scraper_type == "diffbot":
        # DIFFBOT PRIORITY SYSTEM
        # Primary: Extract from Diffbot JSON date field
        if diffbot_data and diffbot_data.get("date"):
            parsed_date = parse_diffbot_date(diffbot_data["date"])
            if parsed_date:
                logger.info(f"Successfully extracted date from Diffbot: {parsed_date}")
                return parsed_date, "diffbot_primary"
        
        # Fallback: AI extraction with metadata + content
        if content and metadata:
            ai_date_str = await extract_date_with_ai(content, metadata, full_html)
            if ai_date_str:
                parsed_date = parse_ai_extracted_date(ai_date_str)
                if parsed_date:
                    logger.info(f"Successfully extracted date with AI fallback: {parsed_date}")
                    return parsed_date, "diffbot_ai_fallback"
    
    elif scraper_type == "playwright":
        # PLAYWRIGHT PRIORITY SYSTEM
        # Primary: AI extraction with metadata + content
        if content and metadata:
            ai_date_str = await extract_date_with_ai(content, metadata, full_html)
            if ai_date_str:
                parsed_date = parse_ai_extracted_date(ai_date_str)
                if parsed_date:
                    logger.info(f"Successfully extracted date with AI primary: {parsed_date}")
                    return parsed_date, "playwright_ai_primary"
        
        # Fallback: Algorithmic metadata extraction
        if metadata:
            parsed_date = extract_date_from_metadata(metadata)
            if parsed_date:
                logger.info(f"Successfully extracted date with algorithmic fallback: {parsed_date}")
                return parsed_date, "playwright_algorithmic_fallback"
    
    logger.warning(f"Failed to extract date using {scraper_type} priority system - this may be expected for non-news content")
    return None, "failed" 