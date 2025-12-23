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
ENV MQTT_BROKER=6575a30783c5453485012d4094a0db47.s1.eu.hivemq.cloud \
    MQTT_PORT=8883 \
    MQTT_USE_TLS=1 \
    MQTT_TLS_INSECURE=1 \
    MQTT_USERNAME=bill_cipher \
    MQTT_PASSWORD=nohter-cuttih-1suNva \
    MQTT_CA_CERT_PATH= \
    SUPABASE_URL=https://nfepanxnybnuodwgzrrv.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mZXBhbnhueWJudW9kd2d6cnJ2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NjQxNTUzMSwiZXhwIjoyMDgxOTkxNTMxfQ.yPRwxdXwkfTpysP6m4EXeeUncNE4ogi2LI7Kv5CBxFc \
    SUPABASE_STORAGE_BUCKET=attendance-images \
    SUPABASE_STORAGE_PREFIX=attendance-system/ \
    SUPABASE_STORAGE_PUBLIC=1 \
    SUPABASE_SIGNED_URL_EXPIRES_SECONDS=3600 \
    CLOUD_DELETE_LOCAL_AFTER_UPLOAD=0 \
    DATABASE_URL=postgresql://postgres:AIpSImkjjSgxVPNftBYcImlnhbZnpqah@postgres.railway.internal:5432/railway \
    SECRET_KEY=attendance-system-2025-secret-xyz \
    ADMIN_PASSWORD=admin \
    BASE_DIR=/app/classes \
    DS_DIR=/app/classes/DS \
    SYSTEM_DIR=/app/classes/_system \
    MAX_UPLOAD_MB=10 \
    MAX_IMAGES_PER_STUDENT=10 \
    SESSION_COOKIE_SAMESITE=Lax \
    SESSION_COOKIE_SECURE=0 \
    RECOGNITION_WORKERS=4 \
    PG_POOL_MAX=10 \
    MAX_MQTT_BASE64_BYTES=6000000 \
    MAX_MQTT_CHUNKS=8000 \
    RECOGNITION_MAX_WIDTH=800 \
    DEBUG=False
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,requests; requests.get(f'http://localhost:{os.environ.get(\"PORT\",10000)}/health', timeout=5)" || exit 1

# Run as root to handle Railway volume permissions
# Init databases then start server
CMD ["sh", "-c", "python init_databases.py && gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120"]
