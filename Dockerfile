FROM python:3.11-slim

# System deps for sentence-transformers and psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl ca-certificates supervisor && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install requirements first (for better Docker layer caching)
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Pre-download the sentence transformer model to warm the image cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Copy application code
COPY . /app

# Expose port commonly used by Uvicorn/ASGI
EXPOSE 8000

# Default env
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Supervisord allows optionally running both the API and worker in one container.
# By default the container will run the API. To run supervisord (both), set RUN_MODE=supervised
ENV RUN_MODE=api

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import sys,requests; r=requests.get('http://127.0.0.1:8000/health'); sys.exit(0 if r.status_code==200 else 1)" || exit 0

CMD ["/bin/sh", "-c", "if [ \"$RUN_MODE\" = \"supervised\" ]; then exec supervisord -n; else exec uvicorn simplified_api:app --host 0.0.0.0 --port 8000; fi"]
