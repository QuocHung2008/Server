# ==================== STAGE 1: BUILD ====================
FROM python:3.9-slim-bullseye AS builder

# Cài đặt dependencies build
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    libboost-python-dev \
    libboost-thread-dev \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /build

# Copy requirements và build dlib trước
COPY requirements.txt .

# Build dlib từ source (stable hơn pip)
RUN pip install --no-cache-dir cmake numpy && \
    git clone -b 'v19.24' --single-branch https://github.com/davisking/dlib.git && \
    cd dlib && \
    mkdir build && cd build && \
    cmake .. -DDLIB_USE_CUDA=OFF -DUSE_AVX_INSTRUCTIONS=ON && \
    cmake --build . --config Release && \
    cd .. && python setup.py install && \
    cd .. && rm -rf dlib

# Cài các packages khác
RUN pip install --no-cache-dir -r requirements.txt

# ==================== STAGE 2: RUNTIME ====================
FROM python:3.9-slim-bullseye

# Cài runtime dependencies (chỉ cần runtime, không cần build tools)
RUN apt-get update && apt-get install -y \
    libopenblas0 \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Tạo user non-root để bảo mật
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/classes/DS && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy Python packages từ builder stage
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:10000/', timeout=5)" || exit 1

# Start command
CMD ["python", "server.py"]