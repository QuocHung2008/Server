# Sử dụng Python 3.9 bản nhẹ (slim) để tiết kiệm dung lượng
FROM python:3.9-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# 1. Cài đặt các công cụ hệ thống (Đây là bước fix lỗi apt-get bạn gặp phải)
# - build-essential & cmake: Cần để biên dịch dlib
# - libgl1 & libglib2.0: Cần cho OpenCV xử lý ảnh
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy file requirements trước để tận dụng cache (giúp build nhanh hơn các lần sau)
COPY requirements.txt .

# 3. Cài dlib và cmake riêng (vì dlib compile rất lâu)
# Lưu ý: Quá trình cài dlib có thể mất 10-20 phút ở lần build đầu tiên
RUN pip install --no-cache-dir cmake
RUN pip install --no-cache-dir dlib==19.24.0

# 4. Cài các thư viện còn lại
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy toàn bộ code vào container
COPY . .

# 6. Mở port (Render sẽ dùng port này)
EXPOSE 10000

# 7. Lệnh chạy server
CMD ["python", "server.py"]