"""Content classifier module using GPT-4o-mini."""
import logging
import json
from typing import Dict, Any, Optional
import openai
import re
import traceback

import config
from headline_api.models import ArticleClassification
from headline_worker.prompts import CLASSIFIER_PROMPT

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

async def classify_content(title: str, text: str) -> ArticleClassification:
    """
    Classify article content using GPT-4o-mini.
    
    Args:
        title: The article title
        text: The article text
        
    Returns:
        The classification result
        
    Raises:
        ValueError: If classification fails
    """
    try:
        # Format the prompt with article content - catch format errors
        try:
            formatted_prompt = CLASSIFIER_PROMPT.format(
                title=title,
                text=text[:1000]  # Use first 1000 chars to save tokens
            )
        except KeyError as e:
            logger.error(f"Prompt formatting error: {str(e)} - Using fallback prompt")
            # Use a simpler fallback prompt with properly escaped JSON braces
            formatted_prompt = f"""
            Classify this article as city, global, industry, or trash. 
            Respond in JSON format with "label" field.
            
            Title: {title}
            Content: {text[:1000]}
            """
        
        # Call OpenAI API with detailed error handling
        try:
            client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a content classifier assistant that responds with valid JSON only."},
                    {"role": "user", "content": formatted_prompt}
                ],
                temperature=0.1,  # Low temperature for consistent results
                response_format={"type": "json_object"}
            )
            
            # Log the full response structure for debugging
            logger.debug(f"OpenAI response structure: {type(response)}")
            
            # Check if response has the expected structure
            if not hasattr(response, 'choices') or not response.choices:
                logger.error("Invalid response structure from OpenAI API")
                raise ValueError("Invalid response from OpenAI API")
                
            # Parse the response
            result_text = response.choices[0].message.content
            logger.debug(f"Raw classifier response content: {result_text}")
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise ValueError(f"OpenAI API call failed: {str(e)}")
        
        # Clean and extract valid JSON
        cleaned_text = extract_json_from_text(result_text)
        logger.debug(f"Cleaned JSON text: {cleaned_text}")
        
        # Parse JSON with dedicated error handling
        try:
            result = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {str(e)} in text: {cleaned_text}")
            # Try a more aggressive approach
            try:
                # Find the first { and last }
                start = cleaned_text.find('{')
                end = cleaned_text.rfind('}')
                if start >= 0 and end > start:
                    possible_json = cleaned_text[start:end+1]
                    logger.debug(f"Extracted JSON subset: {possible_json}")
                    result = json.loads(possible_json)
                    logger.info(f"Successfully parsed JSON after manual extraction")
                else:
                    raise ValueError("Could not find valid JSON structure in response")
            except Exception as inner_e:
                logger.error(f"Failed to extract valid JSON: {str(inner_e)}")
                # Create a default classification as fallback
                return ArticleClassification(
                    label="trash",
                    city_slug=None,
                    industry_slug=None
                )
        
        # Validate the result
        if "label" not in result:
            logger.warning("Classification result missing 'label' field, defaulting to 'trash'")
            result["label"] = "trash"
        
        if result["label"] not in ["city", "global", "industry", "trash"]:
            logger.warning(f"Invalid label: {result['label']}, defaulting to 'trash'")
            result["label"] = "trash"
        
        # Check required fields based on label
        if result["label"] == "city" and "city_slug" not in result:
            logger.warning("City classification missing 'city_slug' field, defaulting to 'trash'")
            result["label"] = "trash"
            
        if result["label"] == "industry" and "industry_slug" not in result:
            logger.warning("Industry classification missing 'industry_slug' field, defaulting to 'trash'")
            result["label"] = "trash"
        
        # Ensure city_slug includes state
        if result["label"] == "city" and "city_slug" in result:
            city_slug = result["city_slug"]
            if "," not in city_slug:
                logger.warning(f"City slug '{city_slug}' is missing state information, adding 'Unknown State'")
                result["city_slug"] = f"{city_slug}, Unknown State"
        
        logger.info(f"Successfully classified content as: {result['label']}")
        return ArticleClassification(
            label=result["label"],
            city_slug=result.get("city_slug"),
            industry_slug=result.get("industry_slug")
        )
    except Exception as e:
        # Catch-all exception handler
        logger.error(f"Content classification failed: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        # Fallback to a safe default
        logger.warning("Using fallback classification: trash")
        return ArticleClassification(
            label="trash",
            city_slug=None,
            industry_slug=None
        )

def get_audience_scope(classification: ArticleClassification) -> str:
    """
    Convert classification to audience_scope format.
    
    Args:
        classification: The article classification
        
    Returns:
        The audience_scope string in format '[city:seattle]', '[global]', or '[industry:fintech]'
    """
    if classification.label == "city":
        return f"[city:{classification.city_slug}]"
    elif classification.label == "global":
        return "[global]"
    elif classification.label == "industry":
        return f"[industry:{classification.industry_slug}]"
    else:
        return "[trash]"  # Return a valid format instead of raising an error