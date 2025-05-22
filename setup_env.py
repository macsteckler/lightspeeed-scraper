#!/usr/bin/env python
"""
Setup script for creating a .env file with required environment variables.
This script will prompt for API keys and other configuration values.
"""

import os

def main():
    """
    Main function to create .env file with user input.
    """
    print("Setting up environment variables for Headline Scraper")
    print("====================================================")
    print("Enter the following information (press Enter to skip optional ones)")
    
    # Required variables
    openai_key = input("OpenAI API Key: ").strip()
    diffbot_keys = input("Diffbot API Key(s) (comma-separated if multiple): ").strip()
    supabase_url = input("Supabase URL: ").strip()
    supabase_key = input("Supabase Service Key: ").strip()
    
    # Optional variables with defaults
    pinecone_key = input("Pinecone API Key (optional): ").strip()
    pinecone_env = input("Pinecone Environment (optional): ").strip()
    pinecone_index = input("Pinecone Index (optional, default: headline-articles): ").strip() or "headline-articles"
    jwt_secret = input("JWT Secret (optional, will generate if empty): ").strip() or "supersecret"
    log_level = input("Log Level (optional, default: INFO): ").strip() or "INFO"
    
    # Ask about enabling embeddings
    enable_embeddings = input("Enable embeddings? (yes/no, default: no): ").strip().lower()
    enable_embeddings = "true" if enable_embeddings in ["yes", "y", "true"] else "false"
    
    # Create .env file
    with open(".env", "w") as f:
        f.write(f"OPENAI_API_KEY={openai_key}\n")
        f.write(f"DIFFBOT_KEYS={diffbot_keys}\n")
        f.write(f"SUPABASE_URL={supabase_url}\n")
        f.write(f"SUPABASE_SERVICE_KEY={supabase_key}\n")
        
        if pinecone_key:
            f.write(f"PINECONE_API_KEY={pinecone_key}\n")
        if pinecone_env:
            f.write(f"PINECONE_ENV={pinecone_env}\n")
        f.write(f"PINECONE_INDEX={pinecone_index}\n")
        
        f.write(f"JWT_SECRET={jwt_secret}\n")
        f.write(f"LOG_LEVEL={log_level}\n")
        f.write(f"ENABLE_EMBEDDINGS={enable_embeddings}\n")
    
    print("\nEnvironment variables saved to .env file")
    print("\nTo run the application:")
    print("1. API server: uvicorn headline_api.main:app --host 0.0.0.0 --port 8000")
    print("2. Worker: python -m headline_worker")
    print("Or use the start.sh script if available")

if __name__ == "__main__":
    main() 