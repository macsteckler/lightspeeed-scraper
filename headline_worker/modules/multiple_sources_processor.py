"""Multiple sources processor module for processing specific sources by ID."""
import logging
import asyncio
from typing import Dict, Any, List

import config
from headline_api.db import enqueue_job, update_job_status, update_job_counters, supabase
from headline_api.models import JobType, JobStatus

logger = logging.getLogger(__name__)

async def process_multiple_sources(job_id: int, payload: Dict[str, Any]) -> None:
    """
    Process multiple specific sources by their IDs.
    
    Args:
        job_id: The job ID
        payload: The job payload containing sources list and dry_run flag
        
    Raises:
        RuntimeError: If multiple sources processing fails
    """
    sources = payload.get("sources", [])
    dry_run = payload.get("dry_run", False)
    
    logger.info(f"Processing {len(sources)} specific sources")
    
    # Update job counters
    update_job_counters(job_id, {"links_found": len(sources)})
    
    if dry_run:
        logger.info("Dry run, not processing sources")
        update_job_status(job_id, JobStatus.DONE)
        return
    
    # Process each source
    sources_processed = 0
    errors = 0
    
    for source_info in sources:
        try:
            source_id = source_info["source_id"]
            source_table = source_info["source_table"]
            limit = source_info.get("limit", 100)
            
            logger.info(f"Processing source {source_id} from {source_table} with limit {limit}")
            
            # Get source details from database
            response = supabase.table(source_table).select("*").eq("id", source_id).execute()
            
            if not response.data:
                logger.warning(f"Source {source_id} not found in table {source_table}")
                errors += 1
                continue
                
            source_data = response.data[0]
            
            # Try both source_url and url fields
            source_url = source_data.get("source_url") or source_data.get("url")
            if not source_url:
                logger.warning(f"Source {source_id} has no URL (checked both source_url and url fields)")
                errors += 1
                continue
            
            # Create individual source scraping job
            source_job_payload = {
                "url": source_url,
                "source_id": source_id,
                "source_table": source_table,
                "limit": limit
            }
            
            source_job_id = enqueue_job(
                job_type=JobType.SOURCE,
                payload=source_job_payload
            )
            
            logger.info(f"Created source job {source_job_id} for source {source_id}")
            sources_processed += 1
            
        except Exception as e:
            logger.error(f"Error processing source {source_info}: {str(e)}")
            errors += 1
    
    # Update final job counters
    update_job_counters(job_id, {
        "articles_saved": sources_processed,  # Using this field to track sources processed
        "errors": errors
    })
    
    logger.info(f"Multiple sources processing complete: {sources_processed} sources processed, {errors} errors") 