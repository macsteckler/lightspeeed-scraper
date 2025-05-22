"""Article processor module for processing individual articles."""
import logging
import asyncio
import json
from typing import Dict, Any
from datetime import datetime

import config
from headline_api.db import check_processed_url, save_processed_url, save_article, update_job_status
from headline_api.models import Article, JobStatus, ProcessedUrlStatus
from headline_worker.modules.content_extractor import extract_content, canonicalize_url
from headline_worker.modules.content_classifier import classify_content, get_audience_scope
from headline_worker.modules.summary_generator import process_article

# Import embeddings module only if enabled
if config.ENABLE_EMBEDDINGS:
    from headline_worker.modules.embeddings import embed_article

logger = logging.getLogger(__name__)

async def process_article_job(job_id: int, payload: Dict[str, Any]) -> None:
    """
    Process an article scraping job.
    
    Args:
        job_id: The job ID
        payload: The job payload
        
    Raises:
        RuntimeError: If article processing fails
    """
    url = payload.get("url")
    source_id = payload.get("source_id")
    
    if not url:
        raise ValueError("Missing URL in job payload")
    
    logger.info(f"Processing article: {url}")
    
    # Canonicalize URL
    canonical_url = canonicalize_url(url)
    logger.info(f"Canonical URL: {canonical_url}")
    
    # Check if URL has already been processed
    processed_status = check_processed_url(canonical_url)
    if processed_status:
        logger.info(f"URL {canonical_url} already processed with status: {processed_status}")
        
        # Update job status
        update_job_status(job_id, JobStatus.DONE)
        return
    
    # Extract content
    content = await extract_content(url)
    
    # Classify content
    classification = await classify_content(content["title"], content["text"])
    logger.info(f"Classification: {classification}")
    
    if classification.label == "trash":
        logger.info(f"Article {url} classified as trash, skipping")
        
        # Save in processed_urls
        save_processed_url(canonical_url, ProcessedUrlStatus.TRASH)
        
        # Update job status
        update_job_status(job_id, JobStatus.DONE)
        return
    
    # Process article with appropriate prompt
    result = await process_article(
        classification=classification,
        title=content["title"],
        text=content["text"],
        markdown=content["markdown"],
        metadata=content["metadata"]
    )
    
    # Log the full result for debugging
    logger.info(f"Summary generator result: {json.dumps(result, indent=2)}")
    
    # Parse date
    date_posted = None
    if content.get("date"):
        try:
            date_posted = datetime.fromisoformat(content["date"])
        except (ValueError, TypeError):
            logger.warning(f"Could not parse date: {content.get('date')}")
    
    # Extract complete city for processed_url table (for deduplication purposes)
    city_for_dedupe = "unknown"
    if classification.label == "city" and classification.city_slug:
        # Just get the first part of the city slug for deduplication purposes
        city_parts = classification.city_slug.split(",")
        city_for_dedupe = city_parts[0].strip()
    
    # Get audience scope from classification
    audience_scope = get_audience_scope(classification)
    
    # Handle summaries based on article type
    summary_medium = None
    summary_long = None
    if classification.label == "city":
        summary_medium = result.get("medium_summary")
        summary_long = result.get("long_summary")
    
    # Create article
    article = Article(
        url=url,
        url_canonical=canonical_url,
        title=result.get("title", content["title"]),  # Use result title with fallback to content title
        summary_short=result.get("short_summary"),
        summary_medium=summary_medium,
        summary_long=summary_long,
        topic=result.get("topic"),  # Topic field from prompt (e.g., Government | Finance | Sports | Local News)
        main_topic=result.get("main_topic"),  # New Main Topic field from prompt (e.g., Politics, Business, Technology, etc.)
        topic_2=result.get("subtopics", [])[0] if result.get("subtopics") and len(result.get("subtopics", [])) > 0 else None,  # First subtopic
        topic_3=result.get("subtopics", [])[1] if result.get("subtopics") and len(result.get("subtopics", [])) > 1 else None,  # Second subtopic
        grade=int(result.get("score", 0)),  # Same score for grade
        date_posted=date_posted,
        is_embedded=False,
        audience_scope=audience_scope,
        full_content=content.get("text", ""),  # Original scraped content
        meta_data=content.get("metadata", {})  # Original metadata
    )
    
    # Save article
    article_id = save_article(article)
    logger.info(f"Saved article with ID: {article_id}")
    
    # Mark URL as processed - use just the city name for deduplication
    save_processed_url(canonical_url, ProcessedUrlStatus.PROCESSED, city_for_dedupe)
    
    # Only do embedding if enabled
    if config.ENABLE_EMBEDDINGS:
        # Extract city and topics for embedding
        city = None
        state = None
        topics = []
        
        if classification.label == "city" and classification.city_slug:
            # Keep the full city slug for embedding (including state)
            full_city = classification.city_slug.strip()
            city_parts = full_city.split(",")
            
            # Set city to the full city, state string
            city = full_city
            
            # Extract state separately if present
            if len(city_parts) > 1:
                state = city_parts[1].strip()
        
        if classification.label == "industry" and classification.industry_slug:
            topics.append(classification.industry_slug)
        
        try:
            # Embed article
            await embed_article(
                article_id=article_id,
                url=canonical_url,
                title=content["title"],
                summary=result["short_summary"],
                date_posted=date_posted,
                city=city,
                state=state,
                topics=topics
            )
        except Exception as e:
            # Log error but don't fail the job
            logger.error(f"Failed to embed article {article_id}: {str(e)}")
    else:
        logger.info(f"Embeddings disabled, skipping for article {article_id}")
    
    # Update job status
    update_job_status(job_id, JobStatus.DONE)
    logger.info(f"Article {url} processed successfully") 