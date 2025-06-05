"""Data models for the headline content scraper API."""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl, validator


class JobStatus(str, Enum):
    """Job status enum."""
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Job type enum."""
    ARTICLE = "article"
    SOURCE = "source"
    BATCH = "batch"
    MULTIPLE_SOURCES = "multiple_sources"


class ProcessedUrlStatus(str, Enum):
    """Processed URL status enum."""
    TRASH = "trash"
    PROCESSED = "processed"


class SourceTable(str, Enum):
    """Source table enum."""
    BIGHIPPO = "bighippo_sources"
    CITY = "city_sources"


class ScrapeArticleRequest(BaseModel):
    """Request model for article scraping."""
    url: str
    source_id: Optional[UUID] = None


class ScrapeSourceRequest(BaseModel):
    """Request model for source scraping."""
    url: str
    source_id: Optional[UUID] = None
    source_table: Optional[SourceTable] = None
    limit: int = 100

    @validator('source_table')
    def validate_source_table(cls, v, values):
        """Validate that source_table is provided if source_id is provided."""
        if values.get('source_id') and not v:
            raise ValueError("source_table must be provided when source_id is provided")
        return v


class ProcessSourcesRequest(BaseModel):
    """Request model for batch source processing."""
    batch_size: int = 50
    query: Optional[str] = None
    dry_run: bool = False


class SourceToScrape(BaseModel):
    """Model for a single source to scrape."""
    source_id: UUID
    source_table: SourceTable
    limit: int = 100


class ScrapeMultipleSourcesRequest(BaseModel):
    """Request model for scraping multiple specific sources."""
    sources: List[SourceToScrape] = Field(..., min_items=1, max_items=50)
    dry_run: bool = False

    @validator('sources')
    def validate_sources(cls, v):
        """Validate that we don't have duplicate sources."""
        seen = set()
        for source in v:
            key = (source.source_id, source.source_table)
            if key in seen:
                raise ValueError(f"Duplicate source: {source.source_id} in {source.source_table}")
            seen.add(key)
        return v


class JobResponse(BaseModel):
    """Response model for job creation."""
    job_id: int


class JobDetails(BaseModel):
    """Job details model."""
    id: int
    job_type: JobType
    payload: Dict[str, Any]
    status: JobStatus
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # For live counters in job status
    links_found: Optional[int] = 0
    links_skipped: Optional[int] = 0  
    articles_saved: Optional[int] = 0
    errors: Optional[int] = 0


class ArticleClassification(BaseModel):
    """Model for article classification results."""
    label: str  # 'city', 'global', 'industry', 'trash'
    city_slug: Optional[str] = None
    industry_slug: Optional[str] = None


class Article(BaseModel):
    """Model for article data."""
    id: Optional[UUID] = None
    url: str
    url_canonical: str
    title: Optional[str] = None
    summary_short: Optional[str] = None
    summary_medium: Optional[str] = None
    summary_long: Optional[str] = None
    topic: Optional[str] = None  # Government | Finance | Sports | Local News
    main_topic: Optional[str] = None  # Politics, Business, Technology, etc.
    topic_2: Optional[str] = None  # First subtopic
    topic_3: Optional[str] = None  # Second subtopic
    grade: Optional[int] = None  # Same as score
    audience_scope: str  # '[city:seattle]', '[global]', '[industry:fintech]'
    date_posted: Optional[datetime] = None
    is_embedded: bool = False
    vector_id: Optional[str] = None
    created_at: Optional[datetime] = None
    full_content: Optional[str] = None  # Original article content
    meta_data: Optional[Dict[str, Any]] = None  # Article metadata 