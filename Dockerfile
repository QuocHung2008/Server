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

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY . .

# Copy ESP32 config generation script
COPY generate_esp32_config.py /app/generate_esp32_config.py

# Railway provides PORT dynamically
ENV PORT=10000
ENV MQTT_BROKER=broker.hivemq.com \
    MQTT_PORT=1883 \
    MQTT_USE_TLS=0 \
    MQTT_TLS_INSECURE=0 \
    MQTT_USERNAME= \
    MQTT_PASSWORD= \
    MQTT_CA_CERT_PATH= \
    DATABASE_URL= \
    SECRET_KEY=change-me \
    ADMIN_PASSWORD=admin \
    BASE_DIR=/app/classes \
    DS_DIR=/app/classes/DS \
    SYSTEM_DIR=/app/classes/_system \
    MAX_UPLOAD_MB=10 \
    MAX_IMAGES_PER_STUDENT=10 \
    SESSION_COOKIE_SAMESITE=Lax \
    SESSION_COOKIE_SECURE=0 \
    RECOGNITION_WORKERS=2 \
    PG_POOL_MAX=10 \
    MAX_MQTT_BASE64_BYTES=6000000 \
    MAX_MQTT_CHUNKS=8000 \
    DEBUG=False
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,requests; requests.get(f'http://localhost:{os.environ.get(\"PORT\",10000)}/health', timeout=5)" || exit 1

# Run as root to handle Railway volume permissions
# Init databases then start server
CMD ["sh", "-c", "python init_databases.py && gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120"]
