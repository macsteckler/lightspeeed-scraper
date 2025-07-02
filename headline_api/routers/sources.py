"""Router for source scraping endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Body
from headline_api.models import ScrapeSourceRequest, ProcessSourcesRequest, ScrapeMultipleSourcesRequest, JobResponse
from headline_api.models import JobType
import headline_api.db as db

router = APIRouter()
batch_router = APIRouter()
multiple_router = APIRouter()

@router.post(
    "", 
    response_model=JobResponse, 
    status_code=202,
    summary="Scrape All Articles from a Source",
    description="""
    Enqueue a job to scrape all articles from a source page URL.
    
    This will:
    1. Fetch the source page and extract all links
    2. Filter for links that appear to be articles
    3. Create individual article scraping jobs for each link
    4. Process all articles according to their classification
    
    You can optionally provide a source_id and source_table to link articles to a source.
    Source table can be either 'bighippo_sources' or 'city_sources'.
    
    Returns a job ID that can be used to check the status of the scraping process.
    """
)
async def scrape_source(
    request: ScrapeSourceRequest = Body(
        ...,
        example={
            "url": "https://www.geekwire.com/",
            "source_id": "123e4567-e89b-12d3-a456-426614174000",
            "source_table": "bighippo_sources",
            "limit": 50
        },
        description="URL to scrape, optional source ID and table, and limit"
    )
):
    """
    Harvest, classify & process every outbound link from one source page.
    
    This endpoint enqueues a job to scrape links from a source page and
    process them in separate article jobs.
    """
    try:
        # Create job in the queue
        payload = {
            "url": request.url,
            "limit": request.limit
        }
        
        # Add source info if provided
        if request.source_id:
            payload["source_id"] = str(request.source_id)
            payload["source_table"] = request.source_table
        
        job_id = db.enqueue_job(
            job_type=JobType.SOURCE,
            payload=payload
        )
        
        return JobResponse(job_id=job_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue source scraping job: {str(e)}"
        )

@batch_router.post(
    "", 
    response_model=JobResponse, 
    status_code=202,
    summary="Process Multiple Sources in Batch",
    description="""
    Enqueue a job to process multiple sources in batch mode.
    
    This endpoint will:
    1. Query the database for sources matching criteria
    2. Take up to `batch_size` sources to process
    3. Create individual source scraping jobs for each
    
    You can optionally perform a dry run to see what would be processed.
    
    Returns a job ID that can be used to check the status of the batch process.
    """
)
async def process_sources(
    request: ProcessSourcesRequest = Body(
        ...,
        example={
            "batch_size": 10,
            "query": None,
            "dry_run": False
        },
        description="Batch size, optional query filter, and dry run flag"
    )
):
    """
    Orchestrate batch scraping for N sources stored in Supabase.
    
    This endpoint enqueues a job to select N sources and create
    source scraping jobs for each.
    """
    try:
        # Create job in the queue
        job_id = db.enqueue_job(
            job_type=JobType.BATCH,
            payload={
                "batch_size": request.batch_size,
                "query": request.query,
                "dry_run": request.dry_run
            }
        )
        
        return JobResponse(job_id=job_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue batch processing job: {str(e)}"
        )

@multiple_router.post(
    "", 
    response_model=JobResponse, 
    status_code=202,
    summary="Scrape Multiple Specific Sources",
    description="""
    Enqueue a job to scrape multiple specific sources by their IDs.
    
    This endpoint will:
    1. Take a list of source IDs and their corresponding tables
    2. Create individual source scraping jobs for each specified source
    3. Process all articles from those sources according to their classification
    
    You can specify sources from either 'bighippo_sources' or 'city_sources' tables.
    Each source can have its own limit for the number of articles to scrape.
    
    You can optionally perform a dry run to see what would be processed.
    
    Returns a job ID that can be used to check the status of the scraping process.
    """
)
async def scrape_multiple_sources(
    request: ScrapeMultipleSourcesRequest = Body(
        ...,
        example={
            "sources": [
                {
                    "source_id": "123e4567-e89b-12d3-a456-426614174000",
                    "source_table": "bighippo_sources",
                    "limit": 50
                },
                {
                    "source_id": 701,
                    "source_table": "city_sources", 
                    "limit": 25
                }
            ],
            "dry_run": False
        },
        description="List of sources to scrape with their table and limits (supports both integer IDs for city_sources and UUID strings for bighippo_sources)"
    )
):
    """
    Scrape multiple specific sources by their IDs from either table.
    
    This endpoint enqueues a job to process the specified sources and
    create individual source scraping jobs for each.
    """
    try:
        # Create job in the queue
        job_id = db.enqueue_job(
            job_type=JobType.MULTIPLE_SOURCES,
            payload={
                "sources": [
                    {
                        "source_id": str(source.source_id),
                        "source_table": source.source_table.value,
                        "limit": source.limit
                    }
                    for source in request.sources
                ],
                "dry_run": request.dry_run
            }
        )
        
        return JobResponse(job_id=job_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue multiple sources scraping job: {str(e)}"
        ) 