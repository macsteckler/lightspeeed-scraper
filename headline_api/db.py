"""Database utility functions for the headline content scraper."""
import logging
from typing import Dict, List, Optional, Any, Union, Callable
from datetime import datetime
import uuid
import time
import asyncio
from supabase import create_client, Client
from postgrest.exceptions import APIError

import config
from headline_api.models import JobType, JobStatus, Article, JobDetails, ProcessedUrlStatus

logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator to add retry logic with exponential backoff for database operations.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds, doubles with each retry
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    
                    # Don't retry certain errors
                    if "duplicate key value violates unique constraint" in error_str:
                        raise e  # Let duplicate handling deal with this
                    
                    if attempt == max_retries:
                        logger.error(f"Failed after {max_retries} retries: {str(e)}")
                        raise e
                    
                    # Check if it's a connection-related error
                    if any(term in error_str for term in ["timeout", "connection", "reset", "network"]):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Database operation failed (attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                        
                        # Try to refresh connection on connection errors
                        try:
                            test_connection()
                        except:
                            logger.warning("Connection test failed, but continuing with retry...")
                    else:
                        # Non-connection error, fail immediately
                        raise e
            return None
        return wrapper
    return decorator

def test_connection() -> bool:
    """
    Test if the Supabase connection is healthy.
    
    Returns:
        True if connection is healthy, False otherwise
    """
    try:
        # Simple query to test connection
        supabase.table("scrape_jobs").select("id").limit(1).execute()
        return True
    except Exception as e:
        logger.warning(f"Connection test failed: {str(e)}")
        return False

def refresh_connection():
    """
    Refresh the Supabase connection.
    """
    global supabase
    try:
        logger.info("Refreshing Supabase connection...")
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        
        # Test the new connection
        if test_connection():
            logger.info("Connection refreshed successfully")
        else:
            logger.warning("Connection refresh may not have worked properly")
    except Exception as e:
        logger.error(f"Failed to refresh connection: {str(e)}")

@retry_with_backoff(max_retries=3, base_delay=1.0)
def enqueue_job(job_type: JobType, payload: Dict[str, Any]) -> int:
    """
    Enqueue a job in the scrape_jobs table.
    
    Args:
        job_type: The type of job to enqueue
        payload: The job payload
        
    Returns:
        The ID of the created job
    """
    try:
        response = supabase.table("scrape_jobs").insert({
            "job_type": job_type,
            "payload": payload,
            "status": JobStatus.QUEUED.value,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }).execute()
        
        if not response.data:
            raise ValueError("Failed to create job")
        
        return response.data[0]["id"]
    except Exception as e:
        logger.error(f"Failed to enqueue job: {str(e)}")
        raise

@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_job_details(job_id: int) -> Optional[JobDetails]:
    """
    Get job details by ID.
    
    Args:
        job_id: The ID of the job to get
        
    Returns:
        The job details, or None if the job doesn't exist
    """
    try:
        response = supabase.table("scrape_jobs").select("*").eq("id", job_id).execute()
        
        if not response.data:
            return None
        
        job_data = response.data[0]
        return JobDetails(
            id=job_data["id"],
            job_type=job_data["job_type"],
            payload=job_data["payload"],
            status=job_data["status"],
            error_message=job_data.get("error_message"),
            created_at=job_data["created_at"],
            updated_at=job_data["updated_at"],
            links_found=job_data.get("links_found", 0),
            links_skipped=job_data.get("links_skipped", 0),
            articles_saved=job_data.get("articles_saved", 0),
            errors=job_data.get("errors", 0)
        )
    except Exception as e:
        logger.error(f"Failed to get job details: {str(e)}")
        raise

@retry_with_backoff(max_retries=3, base_delay=1.0)
def update_job_status(job_id: int, status: JobStatus, error_message: Optional[str] = None) -> None:
    """
    Update job status.
    
    Args:
        job_id: The ID of the job to update
        status: The new status
        error_message: Optional error message
    """
    try:
        update_data = {
            "status": status.value,
            "updated_at": datetime.now().isoformat()
        }
        
        if error_message:
            update_data["error_message"] = error_message
            
        supabase.table("scrape_jobs").update(update_data).eq("id", job_id).execute()
    except Exception as e:
        logger.error(f"Failed to update job status: {str(e)}")
        raise

@retry_with_backoff(max_retries=3, base_delay=1.0)
def update_job_counters(job_id: int, counters: Dict[str, int]) -> None:
    """
    Update job counters.
    
    Args:
        job_id: The ID of the job to update
        counters: Dictionary of counters to update
    """
    try:
        update_data = {
            "updated_at": datetime.now().isoformat(),
            **counters
        }
            
        supabase.table("scrape_jobs").update(update_data).eq("id", job_id).execute()
    except Exception as e:
        logger.error(f"Failed to update job counters: {str(e)}")
        raise

@retry_with_backoff(max_retries=3, base_delay=1.0)
def save_article(article: Article) -> int:
    """
    Save an article to the news_articles table.
    
    Args:
        article: The article to save
        
    Returns:
        The ID of the created article
    """
    try:
        # Adapting to the existing table structure
        article_data = {
            "url": article.url,
            "url_canonical": article.url_canonical,
            "date": datetime.now().isoformat(),  # Current timestamp
            "title": article.title,
            "summary": article.summary_short,
            "summary_medium": article.summary_medium,
            "summary_long": article.summary_long,
            "topic": article.topic,
            "main_topic": article.main_topic,
            "topic_2": article.topic_2,
            "topic_3": article.topic_3,
            "grade": article.grade,
            "date_posted": article.date_posted.isoformat() if article.date_posted else None,
            "is_embedded": article.is_embedded,
            "vector_id": article.vector_id,
            "full_content": article.full_content,
            "meta_data": article.meta_data
        }
        
        # Handle audience scope format [city:seattle], [global], or [industry:fintech]
        if article.audience_scope.startswith("[city:"):
            city = article.audience_scope.replace("[city:", "").replace("]", "")
            article_data["city"] = city
        elif article.audience_scope.startswith("[industry:"):
            industry = article.audience_scope.replace("[industry:", "").replace("]", "")
            article_data["main_topic"] = industry
        
        logger.info(f"Saving article to Supabase with data: {article_data}")
        response = supabase.table("news_articles").insert(article_data).execute()
        
        if not response.data:
            raise ValueError("Failed to save article")
        
        return response.data[0]["id"]
    except Exception as e:
        logger.error(f"Failed to save article: {str(e)}")
        logger.error(f"Article data: {article}")
        raise

def update_article_embedding(article_id: int, vector_id: str) -> None:
    """
    Update article embedding status.
    
    Args:
        article_id: The ID of the article to update
        vector_id: The vector ID
    """
    try:
        supabase.table("news_articles").update({
            "is_embedded": True,
            "vector_id": vector_id
        }).eq("id", article_id).execute()
    except Exception as e:
        logger.error(f"Failed to update article embedding: {str(e)}")
        raise

@retry_with_backoff(max_retries=3, base_delay=1.0)
def check_processed_url(url: str) -> Optional[ProcessedUrlStatus]:
    """
    Check if a URL has already been processed using processed_news_urls table.
    
    Args:
        url: The URL to check
        
    Returns:
        The status of the URL if it exists, None otherwise
    """
    try:
        response = supabase.table("processed_news_urls").select("processing_status").eq("url", url).execute()
        
        if not response.data:
            return None
        
        # Mapping from your table's processing_status to our ProcessedUrlStatus
        status_map = {
            "trash": ProcessedUrlStatus.TRASH,
            "done": ProcessedUrlStatus.PROCESSED,
            "processed": ProcessedUrlStatus.PROCESSED
        }
        
        status = response.data[0]["processing_status"]
        return status_map.get(status, None)
    except Exception as e:
        logger.error(f"Failed to check processed URL: {str(e)}")
        raise

def save_processed_url(url: str, status: ProcessedUrlStatus, city: str = "unknown") -> None:
    """
    Save a processed URL to processed_news_urls.
    
    Args:
        url: The URL to save
        status: The status of the URL
        city: The city for the URL (required by your schema)
    """
    try:
        # Map our status to your table's processing_status
        status_map = {
            ProcessedUrlStatus.TRASH: "trash",
            ProcessedUrlStatus.PROCESSED: "processed"
        }
        
        is_news = status != ProcessedUrlStatus.TRASH
        
        supabase.table("processed_news_urls").insert({
            "url": url,
            "city": city,
            "scrape_date": datetime.now().isoformat(),
            "is_news": is_news,
            "processing_status": status_map.get(status.value, "pending")
        }).execute()
    except Exception as e:
        # Handle duplicate key constraint violations gracefully
        error_str = str(e)
        if "duplicate key value violates unique constraint" in error_str and "processed_news_urls_url_key" in error_str:
            logger.info(f"URL {url} already exists in processed_news_urls - this is expected behavior")
            return  # Don't raise error for duplicates, just log and continue
        
        logger.error(f"Failed to save processed URL: {str(e)}")
        raise

def get_prompt_by_description(description: str) -> Optional[str]:
    """
    Get a prompt by description.
    
    Args:
        description: The description of the prompt
        
    Returns:
        The prompt text if found, None otherwise
    """
    try:
        response = supabase.table("scraper_prompts").select("prompt").eq("description", description).execute()
        
        if not response.data:
            return None
        
        return response.data[0]["prompt"]
    except Exception as e:
        logger.error(f"Failed to get prompt: {str(e)}")
        raise

@retry_with_backoff(max_retries=3, base_delay=1.0)
def select_sources_for_batch(batch_size: int, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Select sources for batch processing.
    
    Args:
        batch_size: The number of sources to select
        query: Optional query filter
        
    Returns:
        List of sources
    """
    try:
        # Calculate the timestamp for 24 hours ago
        twenty_four_hours_ago = (datetime.now()).isoformat()
        
        # Since .or_() method doesn't exist in Supabase client 1.0.3,
        # we'll use two separate queries and combine results
        
        # Query 1: Sources where last_scraped_at is null
        request1 = supabase.table("bighippo_sources").select("*")
        request1 = request1.eq("has_been_processed", True).eq("verified", True)
        request1 = request1.is_("last_scraped_at", "null")
        
        if query:
            request1 = request1.ilike("name", f"%{query}%")
        
        request1 = request1.order("last_scraped_at.asc.nullsfirst").limit(batch_size)
        
        # Query 2: Sources where last_scraped_at is older than 24 hours
        request2 = supabase.table("bighippo_sources").select("*")
        request2 = request2.eq("has_been_processed", True).eq("verified", True)
        request2 = request2.lt("last_scraped_at", twenty_four_hours_ago)
        
        if query:
            request2 = request2.ilike("name", f"%{query}%")
        
        request2 = request2.order("last_scraped_at.asc.nullsfirst").limit(batch_size)
        
        # Execute both queries
        logger.info(f"Executing source selection queries with batch size {batch_size}")
        
        response1 = request1.execute()
        response2 = request2.execute()
        
        # Combine results and remove duplicates
        all_sources = []
        seen_ids = set()
        
        # Add sources from both queries, avoiding duplicates
        for source_list in [response1.data or [], response2.data or []]:
            for source in source_list:
                if source["id"] not in seen_ids:
                    all_sources.append(source)
                    seen_ids.add(source["id"])
                    
                # Stop when we reach the batch size
                if len(all_sources) >= batch_size:
                    break
            
            if len(all_sources) >= batch_size:
                break
        
        # Limit to batch size
        final_sources = all_sources[:batch_size]
        
        if final_sources:
            logger.info(f"Found {len(final_sources)} sources to process")
        else:
            logger.warning("No sources found matching the criteria")
            
        return final_sources
    except Exception as e:
        logger.error(f"Failed to select sources: {str(e)}")
        # Return empty list instead of raising to avoid disrupting batch processing
        return [] 