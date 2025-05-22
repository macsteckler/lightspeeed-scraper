"""Router for job monitoring endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Path
from headline_api.models import JobDetails
import headline_api.db as db

router = APIRouter()

@router.get(
    "/{job_id}", 
    response_model=JobDetails,
    summary="Get Job Status",
    description="""
    Retrieve the current status of a job by its ID.
    
    Job statuses include:
    - **queued**: Job is waiting to be processed
    - **in_progress**: Job is currently being processed
    - **done**: Job has completed successfully
    - **error**: Job failed with an error
    
    For batch jobs, this endpoint also returns progress counters:
    - **links_found**: Number of links discovered
    - **links_skipped**: Number of links skipped (already processed)
    - **articles_saved**: Number of articles successfully saved
    - **errors**: Number of errors encountered
    """
)
async def get_job_status(
    job_id: int = Path(
        ..., 
        title="Job ID",
        description="The ID of the job to check",
        example=123
    )
):
    """
    Get the status of a job.
    
    This endpoint returns the current status of a job, including
    progress counters for batch jobs.
    """
    try:
        job = db.get_job_details(job_id)
        
        if not job:
            raise HTTPException(
                status_code=404,
                detail=f"Job with ID {job_id} not found"
            )
        
        return job
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job status: {str(e)}"
        ) 