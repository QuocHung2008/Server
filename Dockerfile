# ==================== STAGE 1: BUILD ====================
FROM python:3.9-slim-bullseye AS builder

# Build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    libopenblas-dev \
    liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy requirements
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==================== STAGE 2: RUNTIME ====================
FROM python:3.9-slim-bullseye

# Runtime dependencies
RUN apt-get update && apt-get install -y \
    libopenblas0 \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/classes/DS && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY --chown=appuser:appuser . .

USER appuser

# Railway provides PORT dynamically
ENV PORT=10000
EXPOSE 10000

# Healthcheck (KHÔNG redirect, KHÔNG auth)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,requests; requests.get(f'http://localhost:{os.environ.get(\"PORT\",10000)}/health', timeout=5)" || exit 1

# Production server
CMD ["sh", "-c", "python init_databases.py && gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --preload"]