"""Main FastAPI application for headline content scraper."""
import logging
import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from prometheus_client import make_asgi_app
from fastapi.staticfiles import StaticFiles

from headline_api.routers import articles, sources, jobs
from headline_api.auth import verify_token
import config

# Initialize logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Check if we're in development mode
DEV_MODE = os.getenv("ENVIRONMENT", "development") == "development"
if DEV_MODE:
    logger.info("Running in DEVELOPMENT mode - authentication is disabled")

# Validate configuration
missing_config = config.validate_config()
if missing_config:
    logger.error(f"Missing required configuration: {', '.join(missing_config)}")
    raise ValueError(f"Missing required configuration: {', '.join(missing_config)}")

# Create FastAPI app
app = FastAPI(
    title="Headline Content Scraper API",
    description="""
    API for scraping, processing, and storing news articles.
    
    ## Features
    
    * Scrape individual articles by URL
    * Process all articles from a source website
    * Batch process multiple sources
    * Check job status and results
    
    ## Authentication
    
    In production, all endpoints require authentication with a JWT token in the Authorization header.
    In development mode (current mode: """ + ("DEVELOPMENT" if DEV_MODE else "PRODUCTION") + """), authentication is optional.
    
    Example: `Authorization: Bearer your_jwt_token`
    """,
    version="2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Include routers
app.include_router(articles.router, prefix="/scrape-article", tags=["articles"])
app.include_router(sources.router, prefix="/scrape-source", tags=["sources"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(sources.batch_router, prefix="/process-sources", tags=["sources"])
app.include_router(sources.multiple_router, prefix="/scrape-multiple-sources", tags=["sources"])

@app.get("/health", tags=["system"], summary="Health Check", description="Check if the API is up and running")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "mode": "development" if DEV_MODE else "production"}

@app.get("/test-ui", response_class=HTMLResponse, tags=["system"], include_in_schema=False)
async def test_ui():
    """Serve a simple HTML page for testing the API."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Headline Scraper Test UI</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }
            h1 {
                color: #333;
            }
            .endpoint {
                background-color: #f5f5f5;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            input[type="text"], input[type="number"] {
                width: 100%;
                padding: 8px;
                margin-bottom: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            button {
                background-color: #4CAF50;
                color: white;
                padding: 10px 15px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            button:hover {
                background-color: #45a049;
            }
            .result {
                margin-top: 10px;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #f9f9f9;
                min-height: 100px;
            }
            .tabs {
                display: flex;
                margin-bottom: 20px;
            }
            .tab {
                padding: 10px 20px;
                cursor: pointer;
                background-color: #eee;
            }
            .tab.active {
                background-color: #ddd;
                font-weight: bold;
            }
            .tab-content {
                display: none;
            }
            .tab-content.active {
                display: block;
            }
        </style>
    </head>
    <body>
        <h1>Headline Scraper Test UI</h1>
        
        <div class="tabs">
            <div class="tab active" onclick="openTab(event, 'tab-article')">Scrape Article</div>
            <div class="tab" onclick="openTab(event, 'tab-source')">Scrape Source</div>
            <div class="tab" onclick="openTab(event, 'tab-batch')">Batch Process</div>
            <div class="tab" onclick="openTab(event, 'tab-job')">Check Job</div>
        </div>
        
        <div id="tab-article" class="tab-content active">
            <div class="endpoint">
                <h2>Scrape Article</h2>
                <label for="article-url">Article URL:</label>
                <input type="text" id="article-url" placeholder="e.g., https://www.geekwire.com/2023/seattle-startup-funding/">
                
                <button onclick="scrapeArticle()">Submit</button>
                <div class="result" id="article-result">
                    <!-- Results will be displayed here -->
                </div>
            </div>
        </div>
        
        <div id="tab-source" class="tab-content">
            <div class="endpoint">
                <h2>Scrape Source</h2>
                <label for="source-id">Source ID (UUID):</label>
                <input type="text" id="source-id" placeholder="e.g., 123e4567-e89b-12d3-a456-426614174000">
                
                <label for="source-url">Source URL:</label>
                <input type="text" id="source-url" placeholder="e.g., https://www.geekwire.com/">
                
                <label for="source-limit">Limit (optional):</label>
                <input type="number" id="source-limit" placeholder="e.g., 50" value="50">
                
                <button onclick="scrapeSource()">Submit</button>
                <div class="result" id="source-result">
                    <!-- Results will be displayed here -->
                </div>
            </div>
        </div>
        
        <div id="tab-batch" class="tab-content">
            <div class="endpoint">
                <h2>Batch Process Sources</h2>
                <label for="batch-size">Batch Size:</label>
                <input type="number" id="batch-size" placeholder="e.g., 10" value="10">
                
                <label for="batch-query">Query (optional):</label>
                <input type="text" id="batch-query" placeholder="e.g., category=news">
                
                <label>
                    <input type="checkbox" id="dry-run"> Dry Run (don't actually process)
                </label>
                
                <button onclick="batchProcess()">Submit</button>
                <div class="result" id="batch-result">
                    <!-- Results will be displayed here -->
                </div>
            </div>
        </div>
        
        <div id="tab-job" class="tab-content">
            <div class="endpoint">
                <h2>Check Job Status</h2>
                <label for="job-id">Job ID:</label>
                <input type="number" id="job-id" placeholder="e.g., 123">
                
                <button onclick="checkJob()">Check</button>
                <div class="result" id="job-result">
                    <!-- Results will be displayed here -->
                </div>
            </div>
        </div>
        
        <script>
            function openTab(evt, tabName) {
                const tabContents = document.getElementsByClassName('tab-content');
                for (let i = 0; i < tabContents.length; i++) {
                    tabContents[i].className = tabContents[i].className.replace(" active", "");
                }
                
                const tabs = document.getElementsByClassName('tab');
                for (let i = 0; i < tabs.length; i++) {
                    tabs[i].className = tabs[i].className.replace(" active", "");
                }
                
                document.getElementById(tabName).className += " active";
                evt.currentTarget.className += " active";
            }
            
            async function scrapeArticle() {
                const resultDiv = document.getElementById('article-result');
                resultDiv.innerHTML = "Processing...";
                
                const url = document.getElementById('article-url').value;
                
                try {
                    const response = await fetch('/scrape-article', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            url: url
                        })
                    });
                    
                    const data = await response.json();
                    resultDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                    
                    if (data.job_id) {
                        document.getElementById('job-id').value = data.job_id;
                        // Auto-switch to job tab
                        openTab({currentTarget: document.querySelector('.tab:nth-child(4)')}, 'tab-job');
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<pre>Error: ${error.message}</pre>`;
                }
            }
            
            async function scrapeSource() {
                const resultDiv = document.getElementById('source-result');
                resultDiv.innerHTML = "Processing...";
                
                const sourceId = document.getElementById('source-id').value;
                const sourceUrl = document.getElementById('source-url').value;
                const limit = document.getElementById('source-limit').value;
                
                try {
                    const response = await fetch('/scrape-source', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            source_id: sourceId,
                            query: sourceUrl,
                            limit: parseInt(limit)
                        })
                    });
                    
                    const data = await response.json();
                    resultDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                    
                    if (data.job_id) {
                        document.getElementById('job-id').value = data.job_id;
                        // Auto-switch to job tab
                        openTab({currentTarget: document.querySelector('.tab:nth-child(4)')}, 'tab-job');
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<pre>Error: ${error.message}</pre>`;
                }
            }
            
            async function batchProcess() {
                const resultDiv = document.getElementById('batch-result');
                resultDiv.innerHTML = "Processing...";
                
                const batchSize = document.getElementById('batch-size').value;
                const query = document.getElementById('batch-query').value;
                const dryRun = document.getElementById('dry-run').checked;
                
                try {
                    const response = await fetch('/process-sources', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            batch_size: parseInt(batchSize),
                            query: query || undefined,
                            dry_run: dryRun
                        })
                    });
                    
                    const data = await response.json();
                    resultDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                    
                    if (data.job_id) {
                        document.getElementById('job-id').value = data.job_id;
                        // Auto-switch to job tab
                        openTab({currentTarget: document.querySelector('.tab:nth-child(4)')}, 'tab-job');
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<pre>Error: ${error.message}</pre>`;
                }
            }
            
            async function checkJob() {
                const resultDiv = document.getElementById('job-result');
                resultDiv.innerHTML = "Checking...";
                
                const jobId = document.getElementById('job-id').value;
                
                try {
                    const response = await fetch(`/jobs/${jobId}`);
                    const data = await response.json();
                    resultDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                } catch (error) {
                    resultDiv.innerHTML = `<pre>Error: ${error.message}</pre>`;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Middleware to handle authentication."""
    # Skip auth for health check, metrics, docs, and test UI
    if request.url.path in ["/health", "/metrics", "/docs", "/redoc", "/openapi.json", "/test-ui"]:
        return await call_next(request)
    
    # In development mode, make auth optional
    if DEV_MODE:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.info("No authentication provided, but running in development mode")
            return await call_next(request)
    
    # Verify token for all other endpoints in production
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        if DEV_MODE:
            # In dev mode, allow requests without auth
            return await call_next(request)
        else:
            return JSONResponse(
                status_code=401, 
                content={"detail": "Missing or invalid Authorization header"}
            )
    
    token = auth_header.split("Bearer ")[1]
    try:
        verify_token(token)
    except Exception as e:
        logger.warning(f"Authentication failed: {str(e)}")
        if DEV_MODE:
            # In dev mode, log but allow the request
            logger.warning("Continuing despite auth failure (development mode)")
            return await call_next(request)
        else:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Authentication failed: {str(e)}"}
            )
    
    return await call_next(request) 