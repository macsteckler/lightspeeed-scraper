FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY . .
RUN apt-get update && apt-get install -y curl gnupg && \
    pip install -r requirements.txt && \
    playwright install chromium
# Start both FastAPI and worker via supervisord
CMD ["./start.sh"] 