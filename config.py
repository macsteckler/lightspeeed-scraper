"""Configuration management for the headline content scraper."""
import os
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DIFFBOT_KEYS = os.getenv("DIFFBOT_KEYS", "").split(",") if os.getenv("DIFFBOT_KEYS") else []
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV = os.getenv("PINECONE_ENV")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "headline-articles")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# API settings
API_PORT = int(os.getenv("API_PORT", "8000"))
API_HOST = os.getenv("API_HOST", "0.0.0.0")

# Worker settings
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "2"))  # seconds
MAX_CONCURRENT_EMBEDDINGS = int(os.getenv("MAX_CONCURRENT_EMBEDDINGS", "5"))

# Feature flags
ENABLE_EMBEDDINGS = os.getenv("ENABLE_EMBEDDINGS", "true").lower() in ("true", "1", "yes", "y")

# Validate required configuration
def validate_config() -> List[str]:
    """Validate that all required configuration values are present."""
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not DIFFBOT_KEYS:
        missing.append("DIFFBOT_KEYS")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_SERVICE_KEY:
        missing.append("SUPABASE_SERVICE_KEY")
    
    # Only check Pinecone if embeddings are enabled
    if ENABLE_EMBEDDINGS:
        if not PINECONE_API_KEY:
            missing.append("PINECONE_API_KEY (or set ENABLE_EMBEDDINGS=false)")
        if not PINECONE_ENV:
            missing.append("PINECONE_ENV (or set ENABLE_EMBEDDINGS=false)")
    
    return missing 