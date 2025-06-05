#!/bin/bash
# Start Headline Scraper - API and Worker
#
# Usage: ./start.sh [--resume-jobs]
#
# By default, any queued jobs from previous sessions will be cancelled on startup.
# Use --resume-jobs to continue processing jobs from previous sessions.

# Parse command line arguments
RESUME_JOBS=""
if [ "$1" = "--resume-jobs" ]; then
    RESUME_JOBS="--resume-jobs"
    echo "Will resume processing jobs from previous sessions"
else
    echo "Will cancel any queued jobs from previous sessions (use --resume-jobs to change this)"
fi

# Set up trap to kill worker when script exits
trap 'kill $WORKER_PID 2>/dev/null; kill $API_PID 2>/dev/null; echo "Stopping all processes..."; exit 0' INT TERM EXIT

# Check if virtual environment exists and activate it
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
    PYTHON_CMD="python"
else
    echo "Virtual environment not found. Using system Python..."
# Determine which Python command to use
PYTHON_CMD="python"
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
    fi
fi

# Function to check if required packages are installed
check_dependencies() {
    local missing_deps=()
    local all_deps=("fastapi" "uvicorn" "jinja2" "openai" "requests" "prometheus_client" "playwright" "aiohttp")
    
    echo "Checking dependencies..."
    for dep in "${all_deps[@]}"; do
        if ! $PYTHON_CMD -c "import $dep" 2>/dev/null; then
            missing_deps+=("$dep")
        fi
    done
    
    # Check for packages with different import names
    if ! $PYTHON_CMD -c "import jose" 2>/dev/null; then
        missing_deps+=("python-jose")
    fi
    
    # Pinecone is optional and only needed if ENABLE_EMBEDDINGS=true
    # if ! $PYTHON_CMD -c "import pinecone" 2>/dev/null; then
    #     missing_deps+=("pinecone")
    # fi
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo "The following dependencies are missing: ${missing_deps[*]}"
        echo "Please install them using: pip install ${missing_deps[*]}"
        return 1
    fi
    
    # Check if Playwright browsers are installed
    if ! $PYTHON_CMD -c "from playwright.sync_api import sync_playwright; sync_playwright().__enter__()" 2>/dev/null; then
        echo "Playwright browsers are not installed. Installing them now..."
        $PYTHON_CMD -m playwright install
        if [ $? -ne 0 ]; then
            echo "Failed to install Playwright browsers."
            return 1
        fi
    fi
    
    return 0
}

# Check Python and dependencies
if ! command -v $PYTHON_CMD &>/dev/null; then
    echo "Python is not installed. Please install Python 3.9 or higher."
    exit 1
fi

# Check dependencies
check_dependencies
if [ $? -ne 0 ]; then
    echo "Some dependencies are missing. Please install them and try again."
    exit 1
fi

# Start the worker in background
echo "Starting worker..."
$PYTHON_CMD -m headline_worker $RESUME_JOBS &
WORKER_PID=$!

# Verify worker started
if [ $? -ne 0 ]; then
    echo "Failed to start worker."
    exit 1
fi

# Sleep to ensure worker is running
sleep 1

# Check if worker is still running
if ! kill -0 $WORKER_PID 2>/dev/null; then
    echo "Worker failed to start properly. Check logs for details."
    exit 1
fi

echo "Worker started with PID $WORKER_PID"

# Start the API server
echo "Starting API server..."
uvicorn headline_api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Sleep to ensure API server is running
sleep 2

# Check if API server is running
if ! kill -0 $API_PID 2>/dev/null; then
    echo "API server failed to start properly. Check logs for details."
    kill $WORKER_PID 2>/dev/null
    exit 1
fi

echo "API server started with PID $API_PID"
echo "Headline Content Scraper is running!"
echo "API server is available at http://localhost:8000"
echo "Test UI is available at http://localhost:8000/test-ui"
echo "Press Ctrl+C to stop all processes"

# Wait for either process to exit
wait $API_PID
API_EXIT_CODE=$?

echo "API server stopped with exit code $API_EXIT_CODE"
echo "Stopping worker..."
kill $WORKER_PID 2>/dev/null

# Exit with the API exit code
exit $API_EXIT_CODE 