"""Module for processing source jobs."""
import logging
import asyncio
from typing import Dict, Any, List, Optional
import traceback
from datetime import datetime

from headline_api.models import JobType, JobStatus
from headline_api.db import (
    supabase, 
    check_processed_url, 
    update_job_counters
)
from headline_worker.modules.article_processor import process_article_job
from headline_worker.modules.content_extractor import extract_content
from headline_worker.modules.url_utils import canonicalize_url
from headline_worker.modules.link_collector import collect_links
from headline_worker.metrics import ARTICLES_PROCESSED, JOBS_PROCESSED

logger = logging.getLogger(__name__)

async def process_source(job_id: str, payload: Dict[str, Any]) -> None:
    """
    Process a source job by extracting articles and creating article jobs.
    
    Args:
        job_id: The job ID
        payload: The job payload containing source data
    """
    source_id = payload.get("source_id")
    source_table = payload.get("source_table", "bighippo_sources")  # Default to bighippo_sources if not specified
    
    if not source_id:
        raise ValueError("Missing source_id in payload")
        
    logger.info(f"Processing source {source_id} from table {source_table}")
    
    try:
        # Get source details from database using the specified table
        source = supabase.table(source_table).select("*").eq("id", source_id).single().execute()
        if not source.data:
            raise ValueError(f"Source {source_id} not found in table {source_table}")
            
        source_data = source.data
        # Try both source_url and url fields
        source_url = source_data.get("source_url") or source_data.get("url")
        if not source_url:
            raise ValueError(f"Source {source_id} has no URL (checked both source_url and url fields)")
            
        # Use URL from payload if provided, otherwise use source URL
        source_url = payload.get("url", source_url)
        limit = payload.get("limit", 15)  # Get limit from payload, default to 15
            
        logger.info(f"Processing source URL: {source_url}")
            
        # Collect article links from source
        try:
            article_urls = await collect_links(source_url, limit=limit * 2)  # Collect extra links to allow for skipped links
            if not article_urls:
                logger.warning(f"No article links found in source {source_id}")
                JOBS_PROCESSED.labels(job_type="source", status="no_articles").inc()
                return
                
            logger.info(f"Found {len(article_urls)} article links in source {source_id}")
            
            # Process each article URL, limiting to specified link count
            processed_count = 0
            skipped_count = 0
            error_count = 0
            
            for article_url in article_urls:
                # Check if we've reached our limit of successfully processed + skipped links
                if processed_count + skipped_count >= limit:
                    logger.info(f"Reached limit of {limit} links for source {source_id}")
                    break
                    
                try:
                    # Canonicalize URL for checking if already processed
                    canonical_url = canonicalize_url(article_url)
                    
                    # Check if URL has already been processed
                    processed_status = check_processed_url(canonical_url)
                    if processed_status:
                        logger.info(f"URL {canonical_url} already processed, skipping")
                        skipped_count += 1
                        ARTICLES_PROCESSED.labels(status="already_processed").inc()
                        continue
                    
                    # Extract content from article URL
                    article = await extract_content(article_url)
                    if not article:
                        logger.warning(f"No content extracted from article {article_url}")
                        ARTICLES_PROCESSED.labels(status="no_content").inc()
                        continue
                    
                    # Create article job
                    article_payload = {
                        "url": article_url,
                        "source_id": source_id,
                        "title": article.get("title", ""),
                        "text": article.get("text", ""),
                        "html": article.get("html", ""),
                        "markdown": article.get("markdown", ""),
                        "metadata": article.get("metadata", {})
                    }
                    
                    # Create job
                    job_data = {
                        "job_type": JobType.ARTICLE.value,
                        "status": JobStatus.QUEUED.value,
                        "payload": article_payload
                    }
                    
                    job = supabase.table("scrape_jobs").insert(job_data).execute()
                    if not job.data:
                        logger.error(f"Failed to create article job for {article_url}")
                        ARTICLES_PROCESSED.labels(status="job_creation_failed").inc()
                        continue
                        
                    article_job_id = job.data[0]["id"]
                    logger.info(f"Created article job {article_job_id} for {article_url}")
                    
                    # Process article immediately
                    await process_article_job(article_job_id, article_payload)
                    processed_count += 1
                    ARTICLES_PROCESSED.labels(status="success").inc()
                    
                except Exception as e:
                    logger.error(f"Error processing article {article_url}: {str(e)}\n{traceback.format_exc()}")
                    error_count += 1
                    ARTICLES_PROCESSED.labels(status="error").inc()
                    continue
            
            # Log summary
            logger.info(f"Source {source_id} processing summary: {processed_count} processed, {skipped_count} skipped, {error_count} errors")
            
            # Update job counters if this is a job
            if job_id.isdigit():
                update_job_counters(int(job_id), {
                    "articles_saved": processed_count,
                    "links_skipped": skipped_count,
                    "errors": error_count
                })
                    
        except Exception as e:
            logger.error(f"Failed to collect links from source {source_url}: {str(e)}\n{traceback.format_exc()}")
            JOBS_PROCESSED.labels(job_type="source", status="link_collection_failed").inc()
            raise
                
        # Update the source's last_scraped_at timestamp
        if source_table == "bighippo_sources":
            update_data = {"last_scraped_at": datetime.now().isoformat()}
            supabase.table(source_table).update(update_data).eq("id", source_id).execute()
            logger.info(f"Updated last_scraped_at for source {source_id}")
                
    except Exception as e:
        JOBS_PROCESSED.labels(job_type="source", status="error").inc()
        raise Exception(f"Error processing source {source_id}: {str(e)}")

# ... rest of the existing code ... 