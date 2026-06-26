FROM python:3.11-slim

# Cài system deps cho dlib (BẮT BUỘC)
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Cài dlib trước (build lâu nhất)
RUN pip install --no-cache-dir cmake dlib

# Cài face_recognition và các deps
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Tạo thư mục upload
RUN mkdir -p /app/uploads/faces

EXPOSE 8000

# Dùng sh -c để Railway có thể expand $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]