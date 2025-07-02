"""Module for processing source jobs."""
import logging
import asyncio
from typing import Dict, Any, List, Optional
import traceback
from datetime import datetime

from headline_api.models import JobType, JobStatus, ProcessedUrlStatus
from headline_api.db import (
    check_processed_url, 
    save_processed_url,
    update_job_counters,
    get_source_by_id,
    update_source_scraped_at,
    enqueue_job
)
from headline_worker.modules.article_processor import process_article_job
from headline_worker.modules.content_extractor import extract_content, is_meaningful_content
from headline_worker.modules.content_classifier import classify_content
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
        source = get_source_by_id(source_id, source_table)
        if not source:
            raise ValueError(f"Source {source_id} not found in table {source_table}")
            
        source_data = source
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
                    
                    # Early URL validation - filter out obvious non-news URLs before extraction
                    if not is_meaningful_content({}, article_url):  # Pass empty dict since we only check URL
                        logger.info(f"URL matches obvious non-news pattern, skipping: {article_url}")
                        ARTICLES_PROCESSED.labels(status="obvious_non_news").inc()
                        # Save as processed but don't create article job
                        save_processed_url(canonical_url, ProcessedUrlStatus.TRASH)
                        skipped_count += 1
                        continue
                    
                    # Extract content from article URL
                    try:
                        article = await extract_content(article_url)
                        if not article:
                            logger.warning(f"No content extracted from article {article_url}")
                            ARTICLES_PROCESSED.labels(status="no_content").inc()
                            continue
                    except Exception as extraction_error:
                        logger.warning(f"Content extraction failed for {article_url}: {str(extraction_error)}")
                        ARTICLES_PROCESSED.labels(status="extraction_failed").inc()
                        error_count += 1
                        continue
                    
                    # AI classification - let AI decide what's news vs non-news
                    try:
                        classification = await classify_content(
                            article.get("title", ""), 
                            article.get("text", ""), 
                            article_url
                        )
                        
                        if classification.label == "trash":
                            logger.info(f"AI classified article as trash: {article_url}")
                            ARTICLES_PROCESSED.labels(status="ai_classified_trash").inc()
                            save_processed_url(canonical_url, ProcessedUrlStatus.TRASH)
                            skipped_count += 1
                            continue
                            
                        logger.info(f"AI classified article as {classification.label}, proceeding: {article_url}")
                        
                    except Exception as e:
                        logger.warning(f"AI classification failed for {article_url}: {str(e)}, proceeding anyway")
                        # If classification fails, proceed with processing but log it
                        classification = None
                    
                    # Create article job only for meaningful, news content
                    article_payload = {
                        "url": article_url,
                        "source_id": source_id,
                        "title": article.get("title", ""),
                        "text": article.get("text", ""),
                        "html": article.get("html", ""),
                        "markdown": article.get("markdown", ""),
                        "metadata": article.get("metadata", {}),
                        "date": article.get("date"),
                        "date_extraction_method": article.get("date_extraction_method"),
                        "scraper_type": article.get("scraper_type"),
                        "clean_html": article.get("clean_html"),
                        "classification": classification.model_dump() if classification else None  # Pass classification to avoid re-classifying
                    }
                    
                    # Create job using the new PostgreSQL function
                    article_job_id = enqueue_job(JobType.ARTICLE, article_payload)
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
            if job_id is not None:
                try:
                    job_id_int = int(job_id) if isinstance(job_id, str) else job_id
                    update_job_counters(job_id_int, {
                        "articles_saved": processed_count,
                        "links_skipped": skipped_count,
                        "errors": error_count
                    })
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not update job counters for job_id {job_id}: {str(e)}")
                    # Don't fail the entire process for counter update issues
                    
        except Exception as e:
            logger.error(f"Failed to collect links from source {source_url}: {str(e)}\n{traceback.format_exc()}")
            JOBS_PROCESSED.labels(job_type="source", status="link_collection_failed").inc()
            raise
                
        # Update last_scraped_at timestamp if it's a bighippo_sources table
        if source_table == "bighippo_sources":
            update_source_scraped_at(source_id, source_table)
            logger.info(f"Updated last_scraped_at for source {source_id}")
                
    except Exception as e:
        JOBS_PROCESSED.labels(job_type="source", status="error").inc()
        raise Exception(f"Error processing source {source_id}: {str(e)}")

# ... rest of the existing code ... 