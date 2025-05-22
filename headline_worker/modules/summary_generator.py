"""Content summary generator module."""
import logging
import json
import re
from typing import Dict, Any, Optional, Tuple
import openai
import traceback

import config
from headline_api.models import ArticleClassification
from headline_worker.prompts import GLOBAL_INDUSTRY_PROMPT, CITY_PROMPT

logger = logging.getLogger(__name__)

def extract_json_from_text(text: str) -> str:
    """
    Extract valid JSON from text, handling potential formatting issues.
    
    Args:
        text: Text that may contain JSON
        
    Returns:
        Cleaned JSON string
    """
    # Remove code block markers
    text = text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()
    
    # Try to find JSON-like structure using regex
    json_pattern = r'(?:\s*\{\s*.*?\s*\}\s*)'
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return matches[0]
    
    # If no pattern match, return the original text 
    return text

async def process_article(
    classification: ArticleClassification, 
    title: str, 
    text: str,
    markdown: str,
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process an article based on its classification using the appropriate prompt.
    
    Args:
        classification: The article classification
        title: The article title
        text: The article text
        markdown: The article content in markdown format
        metadata: The article metadata
        
    Returns:
        Dictionary containing processed article data including summaries and metadata
        
    Raises:
        ValueError: If processing fails
    """
    try:
        # Select the appropriate prompt based on classification
        if classification.label == "city":
            prompt_template = CITY_PROMPT
        elif classification.label in ["global", "industry"]:
            prompt_template = GLOBAL_INDUSTRY_PROMPT
        else:
            raise ValueError(f"Invalid classification label: {classification.label}")
            
        # Format metadata as string
        metadata_str = "\n".join(f"{k}: {v}" for k, v in metadata.items())
            
        # Format the prompt with article content
        formatted_prompt = prompt_template.replace(
            "${markdown.substring(0, 4000)}", 
            markdown[:4000]  # Use first 4000 chars as specified in prompt
        ).replace(
            "${metadataString}",
            metadata_str
        )
        
        # Call OpenAI API with JSON response format
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        
        # Log the prompt we're sending
        logger.debug(f"Sending prompt to OpenAI:\n{formatted_prompt}")
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You analyze news articles and provide structured summaries and metadata. Always respond with valid JSON."},
                {"role": "user", "content": formatted_prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}  # Request JSON output
        )
        
        # Get the response text
        result_text = response.choices[0].message.content.strip()
        logger.debug(f"Raw GPT response:\n{result_text}")
        
        # Parse JSON response
        try:
            result = json.loads(result_text)
            logger.debug(f"Parsed JSON result:\n{json.dumps(result, indent=2)}")
        except json.JSONDecodeError as e:
            # Try to extract JSON from text if direct parsing fails
            logger.warning(f"Initial JSON parse failed: {str(e)}")
            cleaned_text = extract_json_from_text(result_text)
            logger.debug(f"Cleaned text for parsing:\n{cleaned_text}")
            try:
                result = json.loads(cleaned_text)
                logger.debug(f"Parsed JSON from cleaned text:\n{json.dumps(result, indent=2)}")
            except json.JSONDecodeError as e2:
                logger.error(f"Failed to parse JSON response: {str(e2)}")
                raise ValueError(f"Failed to parse response as JSON: {str(e2)}")
        
        # Add classification info
        result["classification"] = {
            "label": classification.label,
            "city_slug": classification.city_slug,
            "industry_slug": classification.industry_slug
        }
        
        logger.info(f"Successfully processed article with classification {classification.label}")
        return result
            
    except Exception as e:
        logger.error(f"Article processing failed: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise ValueError(f"Article processing failed: {str(e)}") 