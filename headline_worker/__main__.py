"""Main worker module for headline content scraper."""
import logging
import time
import asyncio
import signal
import sys
from typing import Dict, Any, Optional
import traceback

import config
from headline_api.models import JobType, JobStatus
from headline_api.db import supabase
from headline_worker.metrics import (
    JOBS_PROCESSED, 
    DIFFBOT_REQUESTS, 
    DIFFBOT_RATE_LIMITS, 
    ARTICLES_EMBEDDED,
    start_metrics_server
)
from headline_worker.modules.article_processor import process_article_job
from headline_worker.modules.source_processor import process_source
from headline_worker.modules.batch_processor import process_batch

# Initialize logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Start Prometheus metrics server
start_metrics_server(8001)

# Running flag for graceful shutdown
running = True

# Keep track of the main task for cancellation
main_task = None

def handle_signal(sig, frame):
    """Handle signals for graceful shutdown."""
    global running
    logger.info(f"Received signal {sig}. Shutting down...")
    running = False
    
    # Cancel the main task if it exists
    if main_task and not main_task.done():
        main_task.cancel()
        logger.info("Canceled running tasks")
    
    # Force exit after a short delay if still running
    def force_exit():
        logger.warning("Force exiting after timeout...")
        sys.exit(1)
    
    # Schedule force exit after 5 seconds
    signal.signal(signal.SIGALRM, lambda s, f: force_exit())
    signal.alarm(5)

# Set up signal handlers
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

async def claim_job() -> Optional[Dict[str, Any]]:
    """
    Claim a job from the queue.
    
    Returns:
        The claimed job data, or None if no job is available
    """
    try:
        # Use the FOR UPDATE SKIP LOCKED pattern as described in the PRD
        response = supabase.rpc("claim_job").execute()
        
        if not response.data:
            return None
            
        return response.data[0]
    except Exception as e:
        logger.error(f"Failed to claim job: {str(e)}")
        return None

async def mark_job_done(job_id: int) -> None:
    """
    Mark a job as done.
    
    Args:
        job_id: The ID of the job to mark as done
    """
    try:
        supabase.table("scrape_jobs").update({
            "status": JobStatus.DONE.value,
            "updated_at": "now()"  # This is a PostgreSQL function
        }).eq("id", job_id).execute()
        
        JOBS_PROCESSED.labels(job_type="unknown", status="done").inc()
    except Exception as e:
        logger.error(f"Failed to mark job as done: {str(e)}")

async def mark_job_error(job_id: int, error: str) -> None:
    """
    Mark a job as errored.
    
    Args:
        job_id: The ID of the job to mark as errored
        error: The error message
    """
    try:
        supabase.table("scrape_jobs").update({
            "status": JobStatus.ERROR.value,
            "error_message": error,
            "updated_at": "now()"  # This is a PostgreSQL function
        }).eq("id", job_id).execute()
        
        JOBS_PROCESSED.labels(job_type="unknown", status="error").inc()
    except Exception as e:
        logger.error(f"Failed to mark job as errored: {str(e)}")

async def process_job(job: Dict[str, Any]) -> None:
    """
    Process a job based on its type.
    
    Args:
        job: The job data
    """
    job_id = job["id"]
    job_type = job["job_type"]
    payload = job["payload"]
    
    try:
        if job_type == JobType.ARTICLE.value:
            await process_article_job(job_id, payload)
            JOBS_PROCESSED.labels(job_type="article", status="done").inc()
        elif job_type == JobType.SOURCE.value:
            await process_source(job_id, payload)
            JOBS_PROCESSED.labels(job_type="source", status="done").inc()
        elif job_type == JobType.BATCH.value:
            await process_batch(job_id, payload)
            JOBS_PROCESSED.labels(job_type="batch", status="done").inc()
        else:
            logger.warning(f"Unknown job type: {job_type}")
            await mark_job_error(job_id, f"Unknown job type: {job_type}")
            return
            
        await mark_job_done(job_id)
    except Exception as e:
        error_msg = f"Error processing job {job_id}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        await mark_job_error(job_id, str(e))
        JOBS_PROCESSED.labels(job_type=job_type, status="error").inc()

async def main() -> None:
    """Main worker loop."""
    global running
    
    logger.info("Worker starting...")
    
    # Validate configuration
    missing_config = config.validate_config()
    if missing_config:
        logger.error(f"Missing required configuration: {', '.join(missing_config)}")
        sys.exit(1)
    
    logger.info("Worker polling for jobs...")
    
    while running:
        try:
            job = await claim_job()
            
            if job:
                logger.info(f"Processing job {job['id']} of type {job['job_type']}")
                await process_job(job)
            else:
                # No job available, wait before polling again
                await asyncio.sleep(config.WORKER_POLL_INTERVAL)
                
            # Check if we should stop
            if not running:
                break
                
        except asyncio.CancelledError:
            logger.info("Worker task was cancelled")
            break
        except Exception as e:
            logger.error(f"Unhandled error in worker loop: {str(e)}\n{traceback.format_exc()}")
                
            # Wait before trying again
            await asyncio.sleep(config.WORKER_POLL_INTERVAL)
    
    logger.info("Worker shutting down...")

if __name__ == "__main__":
    try:
        main_task = asyncio.ensure_future(main())
        asyncio.get_event_loop().run_until_complete(main_task)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
        running = False
        if main_task and not main_task.done():
            main_task.cancel()
    finally:
        logger.info("Worker stopped") 