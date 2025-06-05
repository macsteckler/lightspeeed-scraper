"""Main worker module for headline content scraper."""
import logging
import time
import asyncio
import signal
import sys
import argparse
from typing import Dict, Any, Optional
import traceback

import config
from headline_api.models import JobType, JobStatus
from headline_api.db import supabase, refresh_connection, test_connection
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
from headline_worker.modules.multiple_sources_processor import process_multiple_sources

# Initialize logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Start Prometheus metrics server
start_metrics_server(8001)

# Global flag to control worker shutdown
running = True

# Connection health tracking
last_connection_check = 0
connection_check_interval = 300  # Check connection every 5 minutes
consecutive_failures = 0
max_consecutive_failures = 5

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

def test_connection() -> bool:
    """
    Test if the Supabase connection is healthy with timeout.
    
    Returns:
        True if connection is healthy, False otherwise
    """
    try:
        # Simple query to test connection with timeout
        supabase.table("scrape_jobs").select("id").limit(1).execute()
        return True
    except Exception as e:
        logger.warning(f"Connection test failed: {str(e)}")
        return False

async def claim_job() -> Optional[Dict[str, Any]]:
    """
    Claim a job from the queue with robust error handling.
    
    Returns:
        The claimed job data, or None if no job is available
    """
    global consecutive_failures, last_connection_check
    
    try:
        # Periodic connection health check (non-blocking)
        current_time = time.time()
        if current_time - last_connection_check > connection_check_interval:
            logger.debug("Performing periodic connection health check...")
            try:
                # Run health check with timeout in a separate thread to avoid blocking
                loop = asyncio.get_event_loop()
                health_ok = await asyncio.wait_for(
                    loop.run_in_executor(None, test_connection), 
                    timeout=10.0  # 10 second timeout
                )
                if not health_ok:
                    logger.warning("Connection health check failed, refreshing connection...")
                    await asyncio.wait_for(
                        loop.run_in_executor(None, refresh_connection),
                        timeout=15.0  # 15 second timeout
                    )
            except asyncio.TimeoutError:
                logger.warning("Health check timed out, continuing anyway...")
            except Exception as e:
                logger.warning(f"Health check error: {str(e)}, continuing anyway...")
            
            last_connection_check = current_time
        
        # Use the FOR UPDATE SKIP LOCKED pattern as described in the PRD
        response = supabase.rpc("claim_job", {}).execute()
        
        if not response.data:
            consecutive_failures = 0  # Reset failure counter on success
            return None
            
        consecutive_failures = 0  # Reset failure counter on success
        return response.data[0]
        
    except Exception as e:
        consecutive_failures += 1
        error_str = str(e).lower()
        
        # Handle different types of errors
        if any(term in error_str for term in ["timeout", "connection", "reset", "network"]):
            logger.warning(f"Connection-related error claiming job (failure {consecutive_failures}/{max_consecutive_failures}): {str(e)}")
            
            # Try to refresh connection after multiple failures
            if consecutive_failures >= 3:
                logger.info("Multiple connection failures, refreshing connection...")
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, refresh_connection),
                        timeout=15.0
                    )
                except (asyncio.TimeoutError, Exception) as refresh_error:
                    logger.error(f"Failed to refresh connection: {str(refresh_error)}")
            
            # Don't stop the worker for connection issues, just return None
            return None
        else:
            logger.error(f"Non-connection error claiming job: {str(e)}")
            return None

async def mark_job_done(job_id: int) -> None:
    """
    Mark a job as done with retry logic.
    
    Args:
        job_id: The ID of the job to mark as done
    """
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries + 1):
        try:
            supabase.table("scrape_jobs").update({
                "status": JobStatus.DONE.value,
                "updated_at": "now()"  # This is a PostgreSQL function
            }).eq("id", job_id).execute()
            
            JOBS_PROCESSED.labels(job_type="unknown", status="done").inc()
            return  # Success, exit retry loop
            
        except Exception as e:
            error_str = str(e).lower()
            
            if attempt == max_retries:
                logger.error(f"Failed to mark job {job_id} as done after {max_retries} retries: {str(e)}")
                return  # Don't raise, just log and continue
            
            if any(term in error_str for term in ["timeout", "connection", "reset", "network"]):
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Failed to mark job {job_id} as done (attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Non-retryable error marking job {job_id} as done: {str(e)}")
                return

async def mark_job_error(job_id: int, error: str) -> None:
    """
    Mark a job as errored with retry logic.
    
    Args:
        job_id: The ID of the job to mark as errored
        error: The error message
    """
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries + 1):
        try:
            supabase.table("scrape_jobs").update({
                "status": JobStatus.ERROR.value,
                "error_message": error,
                "updated_at": "now()"  # This is a PostgreSQL function
            }).eq("id", job_id).execute()
            
            JOBS_PROCESSED.labels(job_type="unknown", status="error").inc()
            return  # Success, exit retry loop
            
        except Exception as e:
            error_str = str(e).lower()
            
            if attempt == max_retries:
                logger.error(f"Failed to mark job {job_id} as error after {max_retries} retries: {str(e)}")
                return  # Don't raise, just log and continue
            
            if any(term in error_str for term in ["timeout", "connection", "reset", "network"]):
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Failed to mark job {job_id} as error (attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Non-retryable error marking job {job_id} as error: {str(e)}")
                return

async def cleanup_old_jobs() -> None:
    """
    Clean up old queued jobs on startup.
    
    This prevents the worker from processing stale jobs from previous sessions.
    Jobs that are QUEUED or IN_PROGRESS will be marked as CANCELLED.
    """
    try:
        logger.info("Cleaning up old jobs from previous sessions...")
        
        # Find all jobs that are still queued or in progress
        response = supabase.table("scrape_jobs").select("id, job_type").in_(
            "status", [JobStatus.QUEUED.value, JobStatus.IN_PROGRESS.value]
        ).execute()
        
        if response.data:
            job_ids = [job["id"] for job in response.data]
            job_count = len(job_ids)
            
            logger.info(f"Found {job_count} old jobs to clean up: {job_ids}")
            
            # Mark them as cancelled
            supabase.table("scrape_jobs").update({
                "status": "cancelled",
                "error_message": "Job cancelled due to worker restart",
                "updated_at": "now()"
            }).in_("status", [JobStatus.QUEUED.value, JobStatus.IN_PROGRESS.value]).execute()
            
            logger.info(f"Successfully cancelled {job_count} old jobs")
        else:
            logger.info("No old jobs found to clean up")
            
    except Exception as e:
        logger.error(f"Failed to clean up old jobs: {str(e)}")
        # Don't fail startup if cleanup fails
        logger.warning("Continuing startup despite cleanup failure")

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
        elif job_type == JobType.MULTIPLE_SOURCES.value:
            await process_multiple_sources(job_id, payload)
            JOBS_PROCESSED.labels(job_type="multiple_sources", status="done").inc()
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
    global running, consecutive_failures
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Headline Content Scraper Worker")
    parser.add_argument(
        "--resume-jobs", 
        action="store_true", 
        help="Resume processing jobs from previous sessions (default: cancel old jobs)"
    )
    args = parser.parse_args()
    
    logger.info("Worker starting...")
    
    # Validate configuration
    missing_config = config.validate_config()
    if missing_config:
        logger.error(f"Missing required configuration: {', '.join(missing_config)}")
        sys.exit(1)
    
    # Clean up old jobs from previous sessions unless --resume-jobs is specified
    if not args.resume_jobs:
        await cleanup_old_jobs()
    else:
        logger.info("Resuming jobs from previous sessions (--resume-jobs flag specified)")
    
    logger.info("Worker polling for jobs...")
    
    # Health monitoring
    start_time = time.time()
    jobs_processed = 0
    last_health_log = start_time
    health_log_interval = 900  # Log health every 15 minutes
    
    while running:
        try:
            job = await claim_job()
            
            if job:
                logger.info(f"Processing job {job['id']} of type {job['job_type']}")
                await process_job(job)
                consecutive_failures = 0  # Reset on successful job processing
                jobs_processed += 1
            else:
                # No job available, wait before polling again
                # Increase wait time if we've had consecutive failures
                wait_time = min(config.WORKER_POLL_INTERVAL * (1 + consecutive_failures), 60)
                await asyncio.sleep(wait_time)
            
            # Periodic health logging
            current_time = time.time()
            if current_time - last_health_log > health_log_interval:
                runtime_hours = (current_time - start_time) / 3600
                logger.info(f"Worker health check - Runtime: {runtime_hours:.1f}h, Jobs processed: {jobs_processed}, Consecutive failures: {consecutive_failures}")
                last_health_log = current_time
                
            # Check if we should stop
            if not running:
                break
                
        except asyncio.CancelledError:
            logger.info("Worker task was cancelled")
            break
        except Exception as e:
            consecutive_failures += 1
            error_str = str(e).lower()
            
            # Handle connection-related errors gracefully
            if any(term in error_str for term in ["timeout", "connection", "reset", "network"]):
                logger.warning(f"Connection error in worker loop (failure {consecutive_failures}/{max_consecutive_failures}): {str(e)}")
                
                # Try to refresh connection
                if consecutive_failures >= 3:
                    logger.info("Multiple failures, attempting connection refresh...")
                    try:
                        await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(None, refresh_connection),
                            timeout=15.0
                        )
                    except (asyncio.TimeoutError, Exception) as refresh_error:
                        logger.error(f"Connection refresh failed: {str(refresh_error)}")
                
                # Wait longer after connection errors
                wait_time = min(config.WORKER_POLL_INTERVAL * (2 ** min(consecutive_failures, 4)), 120)
                logger.info(f"Waiting {wait_time} seconds before retrying...")
                await asyncio.sleep(wait_time)
            else:
                # Non-connection error
                logger.error(f"Unhandled error in worker loop: {str(e)}\n{traceback.format_exc()}")
                
                # Still wait before trying again, but not as long
                await asyncio.sleep(config.WORKER_POLL_INTERVAL)
            
            # Safety check: if too many consecutive failures, try full connection refresh
            if consecutive_failures >= max_consecutive_failures:
                logger.warning(f"Too many consecutive failures ({consecutive_failures}), performing full connection refresh...")
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, refresh_connection),
                        timeout=15.0
                    )
                    consecutive_failures = 0  # Reset after refresh attempt
                except (asyncio.TimeoutError, Exception) as refresh_error:
                    logger.error(f"Full connection refresh failed: {str(refresh_error)}")
                    # Continue anyway, don't stop the worker
    
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