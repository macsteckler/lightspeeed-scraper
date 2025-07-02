"""Database utility functions for the headline content scraper."""
import logging
from typing import Dict, List, Optional, Any, Union, Callable
from datetime import datetime
import uuid
import time
import asyncio
import json
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2 import sql

import config
from headline_api.models import JobType, JobStatus, Article, JobDetails, ProcessedUrlStatus

logger = logging.getLogger(__name__)

# Initialize PostgreSQL connection pool
_connection_pool: Optional[ThreadedConnectionPool] = None

def get_connection_pool() -> ThreadedConnectionPool:
    """Get or create the connection pool."""
    global _connection_pool
    if _connection_pool is None:
        logger.info("Creating PostgreSQL connection pool...")
        _connection_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=config.DATABASE_URL,
            cursor_factory=RealDictCursor
        )
        logger.info("PostgreSQL connection pool created successfully")
    return _connection_pool

def get_connection():
    """Get a connection from the pool."""
    pool = get_connection_pool()
    return pool.getconn()

def return_connection(conn):
    """Return a connection to the pool."""
    pool = get_connection_pool()
    pool.putconn(conn)

def close_connection_pool():
    """Close the connection pool."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None

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
    Test if the PostgreSQL connection is healthy.
    
    Returns:
        True if connection is healthy, False otherwise
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception as e:
        logger.warning(f"Connection test failed: {str(e)}")
        return False
    finally:
        if conn:
            return_connection(conn)

def refresh_connection():
    """
    Refresh the PostgreSQL connection pool.
    """
    try:
        logger.info("Refreshing PostgreSQL connection...")
        close_connection_pool()
        
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
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO scrape_jobs (job_type, payload, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                job_type,
                json.dumps(payload),
                JobStatus.QUEUED.value,
                datetime.now(),
                datetime.now()
            ))
            job_id = cur.fetchone()['id']
            conn.commit()
            return job_id
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to enqueue job: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_job_details(job_id: int) -> Optional[JobDetails]:
    """
    Get job details by ID.
    
    Args:
        job_id: The ID of the job to get
        
    Returns:
        The job details, or None if the job doesn't exist
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM scrape_jobs WHERE id = %s", (job_id,))
            job_data = cur.fetchone()
            
            if not job_data:
                return None
            
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
    finally:
        if conn:
            return_connection(conn)

@retry_with_backoff(max_retries=3, base_delay=1.0)
def update_job_status(job_id: int, status: JobStatus, error_message: Optional[str] = None) -> None:
    """
    Update job status.
    
    Args:
        job_id: The ID of the job to update
        status: The new status
        error_message: Optional error message
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            if error_message:
                cur.execute("""
                    UPDATE scrape_jobs 
                    SET status = %s, error_message = %s, updated_at = %s
                    WHERE id = %s
                """, (status.value, error_message, datetime.now(), job_id))
            else:
                cur.execute("""
                    UPDATE scrape_jobs 
                    SET status = %s, updated_at = %s
                    WHERE id = %s
                """, (status.value, datetime.now(), job_id))
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to update job status: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

@retry_with_backoff(max_retries=3, base_delay=1.0)
def update_job_counters(job_id: int, counters: Dict[str, int]) -> None:
    """
    Update job counters.
    
    Args:
        job_id: The ID of the job to update
        counters: Dictionary of counters to update
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Build dynamic update query
            update_fields = []
            values = []
            for key, value in counters.items():
                update_fields.append(f"{key} = %s")
                values.append(value)
            
            update_fields.append("updated_at = %s")
            values.append(datetime.now())
            values.append(job_id)
            
            query = f"UPDATE scrape_jobs SET {', '.join(update_fields)} WHERE id = %s"
            cur.execute(query, values)
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to update job counters: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

@retry_with_backoff(max_retries=3, base_delay=1.0)
def save_article(article: Article) -> int:
    """
    Save an article to the news_articles table.
    
    Args:
        article: The article to save
        
    Returns:
        The ID of the created article
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Prepare article data
            article_data = {
                "url": article.url,
                "url_canonical": article.url_canonical,
                "date": datetime.now(),
                "title": article.title,
                "summary": article.summary_short,
                "summary_medium": article.summary_medium,
                "summary_long": article.summary_long,
                "topic": article.topic,
                "main_topic": article.main_topic,
                "topic_2": article.topic_2,
                "topic_3": article.topic_3,
                "grade": article.grade,
                "date_posted": article.date_posted,
                "is_embedded": article.is_embedded,
                "vector_id": article.vector_id,
                "full_content": article.full_content,
                "meta_data": json.dumps(article.meta_data) if article.meta_data else None,
                "city": None  # Default to None, will be overridden if city-specific
            }
            
            # Handle audience scope format [city:seattle], [global], or [industry:fintech]
            if article.audience_scope.startswith("[city:"):
                city = article.audience_scope.replace("[city:", "").replace("]", "")
                article_data["city"] = city
            elif article.audience_scope.startswith("[industry:"):
                industry = article.audience_scope.replace("[industry:", "").replace("]", "")
                article_data["main_topic"] = industry
            
            logger.info(f"Saving article to PostgreSQL with data: {article_data}")
            
            cur.execute("""
                INSERT INTO news_articles (
                    url, url_canonical, date, title, summary, summary_medium, summary_long,
                    topic, main_topic, topic_2, topic_3, grade, date_posted, is_embedded,
                    vector_id, full_content, meta_data, city
                ) VALUES (
                    %(url)s, %(url_canonical)s, %(date)s, %(title)s, %(summary)s, %(summary_medium)s,
                    %(summary_long)s, %(topic)s, %(main_topic)s, %(topic_2)s, %(topic_3)s,
                    %(grade)s, %(date_posted)s, %(is_embedded)s, %(vector_id)s, %(full_content)s,
                    %(meta_data)s, %(city)s
                )
                RETURNING id
            """, article_data)
            
            article_id = cur.fetchone()['id']
            conn.commit()
            return article_id
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to save article: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def update_article_embedding(article_id: int, vector_id: str) -> None:
    """
    Update article embedding status.
    
    Args:
        article_id: The ID of the article to update
        vector_id: The vector ID
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE news_articles 
                SET is_embedded = %s, vector_id = %s
                WHERE id = %s
            """, (True, vector_id, article_id))
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to update article embedding: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

@retry_with_backoff(max_retries=3, base_delay=1.0)
def check_processed_url(url: str) -> Optional[ProcessedUrlStatus]:
    """
    Check if a URL has already been processed using processed_news_urls table.
    
    Args:
        url: The URL to check
        
    Returns:
        The status of the URL if it exists, None otherwise
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT processing_status FROM processed_news_urls WHERE url = %s", (url,))
            result = cur.fetchone()
            
            if not result:
                return None
            
            # Mapping from your table's processing_status to our ProcessedUrlStatus
            status_map = {
                "trash": ProcessedUrlStatus.TRASH,
                "done": ProcessedUrlStatus.PROCESSED,
                "processed": ProcessedUrlStatus.PROCESSED
            }
            
            status = result["processing_status"]
            return status_map.get(status, None)
    except Exception as e:
        logger.error(f"Failed to check processed URL: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def save_processed_url(url: str, status: ProcessedUrlStatus, city: str = "unknown") -> None:
    """
    Save a processed URL to processed_news_urls.
    
    Args:
        url: The URL to save
        status: The status of the URL
        city: The city for the URL (required by your schema)
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Map our status to your table's processing_status
            status_map = {
                ProcessedUrlStatus.TRASH: "trash",
                ProcessedUrlStatus.PROCESSED: "processed"
            }
            
            is_news = status != ProcessedUrlStatus.TRASH
            
            cur.execute("""
                INSERT INTO processed_news_urls (url, city, scrape_date, is_news, processing_status)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                url,
                city,
                datetime.now(),
                is_news,
                status_map.get(status.value, "pending")
            ))
            conn.commit()
    except Exception as e:
        # Handle duplicate key constraint violations gracefully
        error_str = str(e)
        if "duplicate key value violates unique constraint" in error_str and "processed_news_urls_url_key" in error_str:
            logger.info(f"URL {url} already exists in processed_news_urls - this is expected behavior")
            if conn:
                conn.rollback()
            return  # Don't raise error for duplicates, just log and continue
        
        if conn:
            conn.rollback()
        logger.error(f"Failed to save processed URL: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def get_prompt_by_description(description: str) -> Optional[str]:
    """
    Get a prompt by description.
    
    Args:
        description: The description of the prompt
        
    Returns:
        The prompt text if found, None otherwise
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT prompt FROM scraper_prompts WHERE description = %s", (description,))
            result = cur.fetchone()
            
            if not result:
                return None
            
            return result["prompt"]
    except Exception as e:
        logger.error(f"Failed to get prompt: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

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
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Calculate the timestamp for 24 hours ago
            twenty_four_hours_ago = datetime.now()
            
            # Query 1: Sources where last_scraped_at is null
            query1_params = []
            query1_sql = """
                SELECT * FROM bighippo_sources 
                WHERE has_been_processed = %s AND verified = %s AND last_scraped_at IS NULL
            """
            query1_params.extend([True, True])
            
            if query:
                query1_sql += " AND name ILIKE %s"
                query1_params.append(f"%{query}%")
            
            query1_sql += " ORDER BY last_scraped_at ASC NULLS FIRST LIMIT %s"
            query1_params.append(batch_size)
            
            cur.execute(query1_sql, query1_params)
            results1 = cur.fetchall()
            
            # Query 2: Sources where last_scraped_at is older than 24 hours
            query2_params = []
            query2_sql = """
                SELECT * FROM bighippo_sources 
                WHERE has_been_processed = %s AND verified = %s AND last_scraped_at < %s
            """
            query2_params.extend([True, True, twenty_four_hours_ago])
            
            if query:
                query2_sql += " AND name ILIKE %s"
                query2_params.append(f"%{query}%")
            
            query2_sql += " ORDER BY last_scraped_at ASC NULLS FIRST LIMIT %s"
            query2_params.append(batch_size)
            
            cur.execute(query2_sql, query2_params)
            results2 = cur.fetchall()
            
            # Combine results and remove duplicates
            all_sources = []
            seen_ids = set()
            
            for result in list(results1) + list(results2):
                if result["id"] not in seen_ids:
                    all_sources.append(dict(result))
                    seen_ids.add(result["id"])
            
            # Limit to batch_size
            all_sources = all_sources[:batch_size]
            
            logger.info(f"Selected {len(all_sources)} sources for batch processing")
            return all_sources
    except Exception as e:
        logger.error(f"Failed to select sources for batch: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def update_source_scraped_at(source_id: str, table_name: str = "bighippo_sources") -> None:
    """
    Update the last_scraped_at timestamp for a source.
    
    Args:
        source_id: The ID of the source to update
        table_name: The name of the table containing the source
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            query = sql.SQL("UPDATE {} SET last_scraped_at = %s WHERE id = %s").format(
                sql.Identifier(table_name)
            )
            cur.execute(query, (datetime.now(), source_id))
            conn.commit()
            logger.info(f"Updated last_scraped_at for source {source_id}")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to update source scraped timestamp: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def get_source_by_id(source_id: str, table_name: str = "bighippo_sources") -> Optional[Dict[str, Any]]:
    """
    Get source by ID from the specified table.
    
    Args:
        source_id: The ID of the source
        table_name: The name of the table to query
        
    Returns:
        The source data or None if not found
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(
                sql.Identifier(table_name)
            )
            cur.execute(query, (source_id,))
            result = cur.fetchone()
            return dict(result) if result else None
    except Exception as e:
        logger.error(f"Failed to get source by ID: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def claim_job() -> Optional[Dict[str, Any]]:
    """
    Claim a job from the queue using FOR UPDATE SKIP LOCKED.
    
    Returns:
        The claimed job data, or None if no job is available
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE scrape_jobs
                SET status = 'in_progress', updated_at = now()
                WHERE id = (
                    SELECT id FROM scrape_jobs
                    WHERE status = 'queued'
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, job_type, payload
            """)
            result = cur.fetchone()
            conn.commit()
            return dict(result) if result else None
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to claim job: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn) 