"""Prometheus metrics for the headline worker."""
from prometheus_client import Counter, start_http_server
import logging

logger = logging.getLogger(__name__)

# Initialize Prometheus metrics
JOBS_PROCESSED = Counter(
    "scrape_jobs_total", 
    "Total scrape jobs processed", 
    ["job_type", "status"]
)

DIFFBOT_REQUESTS = Counter(
    "diffbot_requests_total",
    "Total Diffbot API requests"
)

DIFFBOT_RATE_LIMITS = Counter(
    "diffbot_429_total",
    "Total Diffbot API rate limit errors"
)

ARTICLES_EMBEDDED = Counter(
    "articles_embedded_total",
    "Total articles embedded"
)

ARTICLES_PROCESSED = Counter(
    "articles_processed_total",
    "Total articles processed",
    ["status"]
)

def start_metrics_server(port=8001):
    """Start the Prometheus metrics server."""
    start_http_server(port)
    logger.info(f"Prometheus metrics server started on port {port}") 