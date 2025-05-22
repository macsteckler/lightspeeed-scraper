"""Batch processor module for processing multiple sources."""
import logging
import asyncio
from typing import Dict, Any, List, Set

import config
from headline_api.db import enqueue_job, update_job_status, update_job_counters, select_sources_for_batch
from headline_api.models import JobType, JobStatus
from headline_worker.modules.source_processor import process_source

logger = logging.getLogger(__name__)

# Maximum concurrent sources to process
# This should be slightly less than (number of Diffbot keys × 5 calls per minute)
# to stay within rate limits
MAX_CONCURRENT_SOURCES = max(1, min(8, len(config.DIFFBOT_KEYS) - 1))

async def process_batch(job_id: int, payload: Dict[str, Any]) -> None:
    """
    Process a batch of sources in parallel.
    
    Args:
        job_id: The job ID
        payload: The job payload
        
    Raises:
        RuntimeError: If batch processing fails
    """
    batch_size = int(payload.get("batch_size", 50))
    query = payload.get("query")
    dry_run = payload.get("dry_run", False)
    
    logger.info(f"Processing batch of size {batch_size} with max concurrency {MAX_CONCURRENT_SOURCES}")
    
    # Select sources from database
    sources = select_sources_for_batch(batch_size, query)
    logger.info(f"Selected {len(sources)} sources")
    
    # Update job counters
    update_job_counters(job_id, {"links_found": len(sources)})
    
    if dry_run:
        logger.info("Dry run, not processing sources")
        update_job_status(job_id, JobStatus.DONE)
        return
    
    # Process sources in parallel with controlled concurrency
    sources_processed = 0
    errors = 0
    
    # Use a semaphore to control concurrency
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SOURCES)
    
    async def process_source_with_semaphore(source):
        """Process a single source using a semaphore for concurrency control"""
        nonlocal sources_processed, errors
        async with semaphore:
            source_id = source["id"]
            
            # Create payload for the source
            source_payload = {
                "source_id": str(source_id),
                "url": source.get("source_url") or source.get("url"),
                "limit": 15  # Limit to 15 links per source
            }
            
            try:
                logger.info(f"Processing source {source_id}")
                # Process source directly without enqueuing a separate job
                await process_source(str(source_id), source_payload)
                sources_processed += 1
                logger.info(f"Completed source {source_id} ({sources_processed}/{len(sources)})")
            except Exception as e:
                errors += 1
                logger.error(f"Error processing source {source_id}: {str(e)}")
            
            # Update job counters
            update_job_counters(job_id, {
                "articles_saved": sources_processed,
                "errors": errors
            })
    
    # Create tasks for all sources
    tasks = [process_source_with_semaphore(source) for source in sources]
    
    # Wait for all tasks to complete
    await asyncio.gather(*tasks)
    
    # Update job status
    update_job_status(job_id, JobStatus.DONE)
    logger.info(f"Batch processing complete: {sources_processed} sources processed, {errors} errors") 