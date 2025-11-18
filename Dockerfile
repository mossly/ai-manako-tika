FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies for pdf2image and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium && \
    playwright install-deps chromium

# Copy application code
COPY app /app/app
COPY backfill_metadata.py /app/
COPY find_download_ids.py /app/
COPY download_legislation.py /app/
COPY fix_failed_downloads.sh /app/
COPY fix_pdf_location.sh /app/
COPY verify_indexed_pdfs.py /app/
COPY sync_all_pdfs.py /app/
COPY rebuild_metadata.py /app/

# Make scripts executable
RUN chmod +x /app/fix_failed_downloads.sh /app/fix_pdf_location.sh

# Create data directories
RUN mkdir -p /data/rag_storage \
    /data/legislation \
    /data/markdown \
    /data/logs

# Create __init__.py files for Python package structure
RUN touch /app/app/__init__.py \
    /app/app/rag/__init__.py \
    /app/app/tools/__init__.py

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
