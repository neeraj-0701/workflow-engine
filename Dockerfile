# ─────────────────────────────────────────────────────────────────
# Configurable Workflow Decision Platform
# Multi-stage Dockerfile
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: Build dependencies ──────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt


# ── Stage 2: Production image ─────────────────────────────────────
FROM python:3.12-slim AS production

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application source
COPY app/ ./app/
COPY configs/ ./configs/

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV DATABASE_URL=sqlite+aiosqlite:///./workflow_engine.db
ENV CONFIGS_DIR=configs
ENV LOG_LEVEL=info

# Create volume for SQLite persistence
VOLUME ["/app/data"]

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
