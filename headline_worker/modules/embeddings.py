"""Module for handling article embedding operations."""
import logging
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
try:
    # Try importing using new syntax
    from pinecone import Pinecone
except (ImportError, Exception) as e:
    # Fall back to older pinecone-client way
    try:
        from pinecone import Pinecone, Index
        logger = logging.getLogger(__name__)
        logger.info("Using pinecone-client with Pinecone() constructor")
    except ImportError:
        # If that fails too, re-raise original error
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to import pinecone: {str(e)}")
        raise e

import openai

import config
from headline_worker.metrics import ARTICLES_EMBEDDED

logger = logging.getLogger(__name__)

# Semaphore to limit concurrent embedding requests
embedding_semaphore = asyncio.Semaphore(5)

# Global Pinecone client instance
pinecone_client = None

def prepare_embedding_text(
    title: str, 
    city: Optional[str] = None, 
    state: Optional[str] = None,
    main_topic: Optional[str] = None,
    topic: Optional[str] = None,
    topic_2: Optional[str] = None,
    topic_3: Optional[str] = None,
    summary: Optional[str] = None
) -> str:
    """
    Prepare text for embedding.
    
    Args:
        title: The article title
        city: Optional city
        state: Optional state
        main_topic: Optional main topic
        topic: Optional topic
        topic_2: Optional second topic
        topic_3: Optional third topic
        summary: Optional summary
    
    Returns:
        The prepared text for embedding
    """
    parts = []
    
    # Add title
    parts.append(f"[TITLE]: {title}")
    
    # Add location if available
    if city or state:
        location_parts = []
        if city:
            location_parts.append(city)
        if state:
            location_parts.append(state)
        parts.append(f"[LOCATION]: {', '.join(location_parts)}")
    
    # Add topics if available
    topic_parts = []
    for t in [main_topic, topic, topic_2, topic_3]:
        if t and t not in topic_parts:  # Avoid duplicates
            topic_parts.append(t)
    
    if topic_parts:
        parts.append(f"[TOPICS]: {', '.join(topic_parts)}")
    
    # Add summary if available
    if summary:
        parts.append(f"[SUMMARY]: {summary}")
    
    return "\n".join(parts)

def init_pinecone() -> None:
    """Initialize Pinecone client."""
    global pinecone_client
    
    # Only initialize once
    if pinecone_client is not None:
        return
        
    try:
        # Initialize with new API
        pinecone_client = Pinecone(
            api_key=config.PINECONE_API_KEY,
            environment=config.PINECONE_ENV
        )
        
        # Create index if it doesn't exist
        if config.PINECONE_INDEX not in pinecone_client.list_indexes().names():
            pinecone_client.create_index(
                name=config.PINECONE_INDEX,
                dimension=1536,  # OpenAI embedding dimension
                metric="cosine"
            )
            logger.info(f"Created Pinecone index: {config.PINECONE_INDEX}")
    except Exception as e:
        logger.error(f"Failed to check/create Pinecone index: {str(e)}")
        raise

async def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding for text.
    
    Args:
        text: The text to embed
        
    Returns:
        The embedding vector
        
    Raises:
        RuntimeError: If embedding generation fails
    """
    try:
        async with embedding_semaphore:
            client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            
            return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate embedding: {str(e)}")
        raise RuntimeError(f"Failed to generate embedding: {str(e)}")

async def upsert_to_pinecone(
    article_id: int,
    vector: List[float],
    metadata: Dict[str, Any]
) -> str:
    """
    Upsert a vector to Pinecone.
    
    Args:
        article_id: The article ID
        vector: The embedding vector
        metadata: The metadata to store with the vector
        
    Returns:
        The vector ID
        
    Raises:
        RuntimeError: If upserting to Pinecone fails
    """
    try:
        # Initialize Pinecone
        init_pinecone()
        
        # Get index using the correct pattern
        index = pinecone_client.Index(config.PINECONE_INDEX)
        
        # Create vector ID using article_id
        vector_id = f"article_{article_id}"
        
        # Upsert vector
        index.upsert(
            vectors=[(vector_id, vector, metadata)],
            namespace="articles"  # Use the same namespace as other codebase
        )
        
        # Increment metric
        ARTICLES_EMBEDDED.inc()
        
        logger.info(f"Upserted vector for article ID: {article_id}")
        
        return vector_id
    except Exception as e:
        logger.error(f"Failed to upsert to Pinecone: {str(e)}")
        raise RuntimeError(f"Failed to upsert to Pinecone: {str(e)}")

async def embed_article(
    article_id: int,
    url: str,
    title: str,
    summary: str,
    date_posted: Optional[datetime] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    topics: Optional[List[str]] = None
) -> None:
    """
    Embed article and store in Pinecone.
    
    Args:
        article_id: The article ID
        url: The article URL
        title: The article title
        summary: The article summary
        date_posted: Optional date posted
        city: Optional city
        state: Optional state
        topics: Optional list of topics
        
    Raises:
        RuntimeError: If embedding fails
    """
    try:
        # Prepare topics
        main_topic = None
        topic = None
        topic_2 = None
        topic_3 = None
        
        if topics:
            if len(topics) > 0:
                main_topic = topics[0]
            if len(topics) > 1:
                topic = topics[1]
            if len(topics) > 2:
                topic_2 = topics[2]
            if len(topics) > 3:
                topic_3 = topics[3]
        
        # Prepare embedding text
        text = prepare_embedding_text(
            title=title,
            city=city,
            state=state,
            main_topic=main_topic,
            topic=topic,
            topic_2=topic_2,
            topic_3=topic_3,
            summary=summary
        )
        
        # Generate embedding
        vector = await generate_embedding(text)
        
        # Prepare metadata
        metadata = {
            "article_id": str(article_id),
            "url": url,
            "title": title,
            "summary": summary,
            "date_posted": date_posted.isoformat() if date_posted else None,
            "location": f"{city},{state}" if city and state else (city or ""),
            "topics": [t for t in [main_topic, topic, topic_2, topic_3] if t],
            "last_updated": datetime.utcnow().isoformat()
        }
        
        # Upsert to Pinecone
        vector_id = await upsert_to_pinecone(article_id, vector, metadata)
        
        # Return vector ID
        return vector_id
    except Exception as e:
        logger.error(f"Failed to embed article: {str(e)}")
        raise RuntimeError(f"Failed to embed article: {str(e)}") 