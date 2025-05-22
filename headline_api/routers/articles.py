"""Router for article scraping endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Body
from headline_api.models import ScrapeArticleRequest, JobResponse
from headline_api.models import JobType
import headline_api.db as db

router = APIRouter()

@router.post(
    "", 
    response_model=JobResponse, 
    status_code=202,
    summary="Scrape a single article",
    description="""
    Enqueue a job to scrape and process a single article by URL.
    
    The article will be:
    1. Extracted using Diffbot
    2. Classified by topic and audience
    3. Summarized with different levels of detail
    4. Embedded for vector search
    
    Returns a job ID that can be used to check the status of the scraping process.
    """
)
async def scrape_article(
    request: ScrapeArticleRequest = Body(
        ...,
        example={
            "url": "https://www.geekwire.com/2023/seattle-startup-funding/",
            "source_id": None
        },
        description="URL to scrape and optional source identifier"
    )
):
    """
    Scrape and process a single URL immediately.
    
    This endpoint enqueues a job to scrape and process the provided URL.
    """
    try:
        # Create job in the queue
        job_id = db.enqueue_job(
            job_type=JobType.ARTICLE,
            payload={
                "url": request.url,
                "source_id": str(request.source_id) if request.source_id else None
            }
        )
        
        return JobResponse(job_id=job_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue article scraping job: {str(e)}"
        ) 