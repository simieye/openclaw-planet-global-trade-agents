FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY orchestration/ /app/orchestration/
COPY agents/ /app/agents/
COPY taskflows/ /app/taskflows/
COPY webhooks/ /app/webhooks/
COPY knowledge/ /app/knowledge/
COPY deploy/cluster.toml /app/deploy/cluster.toml

# Create data directory
RUN mkdir -p /app/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health')" || exit 1

EXPOSE 8080

CMD ["python", "orchestration/engine.py", "start"]
