# CODEX PROMPT — Tái cấu trúc hệ thống điểm danh ESP32-CAM lên Railway (Real-time, Light Mode)

---

## 🎯 MỤC TIÊU TỔNG QUAN

Tái cấu trúc toàn bộ dự án **Smart Face Recognition Attendance System** từ kiến trúc cũ (Flask + SQLite + MQTT + dark mode) sang kiến trúc mới tối ưu cho **Railway deployment**:

- **Backend**: FastAPI (thay Flask) + WebSocket native (thay MQTT hoàn toàn)
- **Database**: PostgreSQL Railway (thay SQLite)
- **Frontend**: Light mode Tailwind CSS (bỏ toàn bộ dark/glassmorphism)
- **ESP32**: WebSocket binary client (thay HTTP POST + MQTT)
- **Real-time**: Socket.IO broadcast cho browser, WebSocket cho ESP32
- **Platform**: Chỉ Railway — không dùng HiveMQ, không dùng dịch vụ ngoài

---

## 📐 KIẾN TRÚC MỚI (PHẢI TUÂN THỦ CHÍNH XÁC)

```
ESP32-CAM
  │
  ├──[ws:// binary]──► FastAPI Server (Railway)
  │                         │
  │◄──[JSON result]──────────┤
                             │
                     ┌───────┼────────┐
                     │       │        │
               Face Engine  PostgreSQL  Socket.IO
               (dlib/128D)  (Railway)   │
                                        │
                                    Web Dashboard
                                    (Light mode, Tailwind)
```

**Luồng xử lý (phải đảm bảo < 500ms end-to-end):**
1. ESP32 chụp ảnh JPEG → gửi qua WebSocket binary frame → server
2. Server nhận binary → decode → face_recognition → trả JSON ngay lập tức qua cùng WebSocket connection
3. Server lưu record vào PostgreSQL → broadcast Socket.IO event `attendance_update` → dashboard cập nhật tức thì
4. ESP32 nhận JSON → hiển thị LED/Serial kết quả

---

## 🗂️ CẤU TRÚC THƯ MỤC MỚI (phải tạo đủ)

```
project/
├── Dockerfile                    # Railway deployment
├── railway.toml                  # Railway config
├── pyproject.toml                # Dependencies (uv/pip)
├── requirements.txt              # Python deps
├── .env.example                  # Biến môi trường mẫu
│
├── app/
│   ├── main.py                   # FastAPI app entrypoint
│   ├── config.py                 # Cấu hình từ ENV vars
│   ├── database.py               # PostgreSQL async connection (asyncpg)
│   ├── models.py                 # SQLAlchemy async models
│   ├── schemas.py                # Pydantic schemas
│   │
│   ├── routers/
│   │   ├── ws_camera.py          # WebSocket endpoint cho ESP32-CAM
│   │   ├── api_keys.py           # CRUD API keys (REST)
│   │   ├── classes.py            # Quản lý lớp học (REST)
│   │   ├── students.py           # Quản lý sinh viên + upload ảnh (REST)
│   │   └── attendance.py         # Lịch sử điểm danh + export Excel (REST)
│   │
│   ├── services/
│   │   ├── face_service.py       # face_recognition wrapper, encode + match
│   │   ├── socketio_service.py   # Socket.IO server instance + emit helpers
│   │   └── auth_service.py       # API key validation (in-memory cache)
│   │
│   └── templates/
│       ├── base.html             # Layout chung, light mode
│       ├── index.html            # Dashboard tổng quan
│       ├── attendance.html       # Bảng điểm danh real-time
│       ├── students.html         # Quản lý sinh viên
│       └── api_keys.html         # Quản lý API keys
│
├── esp32/
│   ├── esp32_cam_websocket.ino   # Code Arduino ESP32 (WebSocket binary)
│   └── config.h                  # Cấu hình WiFi, server URL, API key
│
└── scripts/
    ├── init_db.py                # Khởi tạo schema PostgreSQL
    └── migrate_sqlite.py         # Script migrate dữ liệu cũ (nếu có)
```

---

## ⚙️ YÊU CẦU BACKEND (FastAPI)

### `app/main.py`

```python
# Phải có đầy đủ:
# 1. FastAPI app với lifespan context (startup/shutdown)
# 2. socketio.AsyncServer gắn vào FastAPI qua ASGIApp
# 3. Mount static files
# 4. Include tất cả routers
# 5. Startup: khởi tạo DB pool, load face encodings, load API keys vào cache
# 6. Middleware: CORS (cho phép tất cả origins khi dev, restrict khi prod)
# 7. Health check endpoint: GET /health → {"status": "ok", "timestamp": ...}

# QUAN TRỌNG: Dùng uvicorn với workers=1 trên Railway
# (face encodings in-memory không share được qua multiprocess)
```

### `app/routers/ws_camera.py` — QUAN TRỌNG NHẤT

```python
# WebSocket endpoint: ws://your-app.railway.app/ws/camera?api_key=xxx
#
# FLOW CHÍNH XÁC:
# 1. Validate api_key từ query param (in-memory cache, KHÔNG query DB mỗi frame)
# 2. Vòng lặp nhận binary frames:
#    - websocket.receive_bytes() → raw JPEG bytes
#    - Decode bằng cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
#    - face_recognition.face_locations() + face_encodings()
#    - So sánh với known_encodings (in-memory, đã load lúc startup)
#    - Lấy kết quả match tốt nhất (tolerance=0.5)
#    - await websocket.send_json({...}) ngay lập tức
# 3. Sau khi match thành công:
#    - Lưu record vào PostgreSQL (async, KHÔNG block websocket)
#    - Emit Socket.IO event 'attendance_update' (async)
# 4. Xử lý disconnect sạch sẽ
#
# RESPONSE JSON FORMAT (gửi về ESP32):
# {
#   "status": "recognized" | "unknown" | "no_face",
#   "name": "Nguyen Van A",        # null nếu không nhận ra
#   "student_id": "ST001",         # null nếu không nhận ra
#   "class_name": "12T1",
#   "confidence": 0.87,            # 1 - distance
#   "timestamp": "2024-01-15T08:30:15.123Z",
#   "device_id": "ESP32_01"        # từ query param
# }
#
# ANTI-PATTERN CẦN TRÁNH:
# - KHÔNG dùng asyncio.run() trong async function
# - KHÔNG block event loop bằng face_recognition sync (dùng run_in_executor)
# - KHÔNG query DB để validate API key mỗi frame
```

### `app/services/face_service.py`

```python
# KIẾN TRÚC IN-MEMORY:
# known_encodings: dict[class_name, list[tuple[encoding, student_id, name]]]
# Được load lúc startup từ PostgreSQL (encode ảnh từ file system)
#
# HÀM BẮT BUỘC:
# - async def load_all_encodings() → load từ DB vào RAM
# - def encode_face(image_path: str) → np.array (128D)
# - def match_face(unknown_encoding, class_name=None) → MatchResult
# - async def add_student_encoding(student_id, image_bytes) → bool
#   (encode + lưu vào DB + update RAM dict ngay lập tức)
#
# PERFORMANCE:
# - Dùng face_recognition.compare_faces() với batch, KHÔNG loop từng face
# - Cache encoding kết quả 5 giây cho cùng 1 face hash
# - Run face_recognition trong ThreadPoolExecutor (CPU-bound)
```

### `app/database.py`

```python
# Dùng asyncpg (KHÔNG dùng psycopg2 sync)
# Connection pool: min=2, max=10
# DATABASE_URL từ Railway env var (format: postgresql://...)
#
# Schema PostgreSQL (PHẢI TẠO ĐỦ):
#
# CREATE TABLE classes (
#   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#   name VARCHAR(100) UNIQUE NOT NULL,
#   created_at TIMESTAMP DEFAULT NOW()
# );
#
# CREATE TABLE students (
#   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#   student_code VARCHAR(50) UNIQUE NOT NULL,
#   full_name VARCHAR(200) NOT NULL,
#   class_id UUID REFERENCES classes(id),
#   image_path TEXT,
#   face_encoding BYTEA,            -- numpy array serialized (pickle)
#   created_at TIMESTAMP DEFAULT NOW()
# );
#
# CREATE TABLE attendance_records (
#   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#   student_id UUID REFERENCES students(id),
#   class_id UUID REFERENCES classes(id),
#   device_id VARCHAR(100),
#   confidence FLOAT,
#   status VARCHAR(20) DEFAULT 'present',
#   recorded_at TIMESTAMP DEFAULT NOW()
# );
#
# CREATE TABLE api_keys (
#   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#   key_hash VARCHAR(64) UNIQUE NOT NULL,  -- SHA256 hash
#   label VARCHAR(100),
#   class_id UUID REFERENCES classes(id),
#   device_id VARCHAR(100),
#   is_active BOOLEAN DEFAULT TRUE,
#   created_at TIMESTAMP DEFAULT NOW(),
#   last_used_at TIMESTAMP
# );
#
# CREATE INDEX ON attendance_records(recorded_at DESC);
# CREATE INDEX ON attendance_records(class_id, recorded_at DESC);
```

---

## 🔌 CODE ESP32-CAM (esp32/esp32_cam_websocket.ino)

### Yêu cầu thư viện

```cpp
// PHẢI dùng các thư viện sau (Arduino IDE / PlatformIO):
// - ArduinoWebsockets by Gil Maimon (WebSockets cho ESP32, nhẹ, ổn định)
// - ArduinoJson v6
// - esp_camera (built-in ESP32 core)
// KHÔNG dùng: PubSubClient, MQTT, EspMQTTClient
```

### `esp32/config.h`

```cpp
#pragma once

// WiFi
#define WIFI_SSID       "your_wifi_ssid"
#define WIFI_PASSWORD   "your_wifi_password"

// Railway Server
#define SERVER_HOST     "your-app.railway.app"
#define SERVER_PORT     443                    // HTTPS/WSS trên Railway
#define WS_PATH         "/ws/camera"

// Device
#define API_KEY         "your_api_key_here"
#define DEVICE_ID       "ESP32_CAM_01"

// Camera (CHỌN ĐÚNG BOARD)
#define CAMERA_MODEL_AI_THINKER   // hoặc WROVER_KIT, M5STACK_WIDE...

// Capture settings
#define CAPTURE_INTERVAL_MS  1500  // ms giữa các lần chụp
#define JPEG_QUALITY         12    // 0-63, thấp hơn = chất lượng cao hơn
#define FRAME_SIZE           FRAMESIZE_VGA  // 640x480
```

### `esp32/esp32_cam_websocket.ino` — LOGIC CHÍNH XÁC

```cpp
/*
 * FLOW HOẠT ĐỘNG:
 * 
 * setup():
 *   1. Khởi tạo Serial (115200 baud)
 *   2. Khởi tạo camera với cấu hình từ config.h
 *   3. Kết nối WiFi (retry tối đa 20 lần, LED blink)
 *   4. Kết nối WebSocket WSS đến server
 *   5. Đăng ký onMessage callback để nhận JSON result
 *   6. Đăng ký onEvent callback (connected/disconnected)
 * 
 * loop():
 *   1. client.poll() — PHẢI gọi mỗi loop để duy trì connection
 *   2. Nếu WebSocket connected VÀ (millis() - lastCapture > INTERVAL):
 *      a. Chụp ảnh: esp_camera_fb_get()
 *      b. Gửi binary: client.sendBinary((char*)fb->buf, fb->len)
 *      c. esp_camera_fb_return(fb)
 *      d. lastCapture = millis()
 *   3. Nếu WebSocket disconnected: reconnect tự động sau 3 giây
 * 
 * onMessage callback (JSON parsing):
 *   - Parse JSON từ server
 *   - Nếu status == "recognized": Serial.printf("[HIT] %s - %s\n", name, student_id)
 *     + Bật LED xanh 1 giây
 *   - Nếu status == "unknown": Serial.println("[MISS] Unknown face")
 *     + Bật LED đỏ 0.5 giây
 *   - Nếu status == "no_face": (silent, không làm gì)
 * 
 * QUAN TRỌNG:
 * - Dùng WSS (TLS) vì Railway chỉ expose HTTPS/WSS
 * - client.setInsecure() nếu không có CA cert (chấp nhận self-signed)
 * - KHÔNG dùng delay() trong loop chính — block WiFi stack
 * - Camera frame buffer PHẢI được return ngay sau khi gửi
 * - Nếu heap free < 50000 bytes: restart ESP32 (esp_restart())
 */

// CODE ĐẦY ĐỦ PHẢI IMPLEMENT:
#include <Arduino.h>
#include "config.h"
#include "esp_camera.h"
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

using namespace websockets;

WebsocketsClient client;
unsigned long lastCapture = 0;
bool wsConnected = false;

// Callback khi nhận message từ server
void onMessageCallback(WebsocketsMessage message) {
  if (message.isText()) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, message.data());
    if (err) return;
    
    const char* status = doc["status"];
    if (strcmp(status, "recognized") == 0) {
      Serial.printf("[OK] %s (%s) - conf: %.2f\n",
        doc["name"].as<const char*>(),
        doc["student_id"].as<const char*>(),
        doc["confidence"].as<float>());
      // Bật LED GPIO 4 (flash LED trên AI Thinker) hoặc GPIO33 (built-in LED)
      digitalWrite(33, LOW);  // LOW = ON cho LED active-low
      delay(800);             // Delay ngắn ở đây OK vì chỉ sau khi nhận result
      digitalWrite(33, HIGH);
    } else if (strcmp(status, "unknown") == 0) {
      Serial.println("[--] Unknown face detected");
    }
    // "no_face": bỏ qua
  }
}

void onEventsCallback(WebsocketsEvent event, String data) {
  if (event == WebsocketsEvent::ConnectionOpened) {
    wsConnected = true;
    Serial.println("[WS] Connected to server");
  } else if (event == WebsocketsEvent::ConnectionClosed) {
    wsConnected = false;
    Serial.println("[WS] Disconnected - will reconnect...");
  }
}

bool connectWebSocket() {
  String url = String("wss://") + SERVER_HOST + WS_PATH 
             + "?api_key=" + API_KEY 
             + "&device_id=" + DEVICE_ID;
  client.setInsecure();  // Bỏ qua verify TLS cert (Railway dùng valid cert nhưng khó load CA)
  client.onMessage(onMessageCallback);
  client.onEvent(onEventsCallback);
  return client.connect(url);
}

void setup() {
  Serial.begin(115200);
  pinMode(33, OUTPUT);
  digitalWrite(33, HIGH);  // LED off
  
  // Khởi tạo camera (config tùy board, xem examples/camera_pins.h)
  camera_config_t config = { /* ... full camera config ... */ };
  config.frame_size = FRAME_SIZE;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count = 1;
  esp_err_t camErr = esp_camera_init(&config);
  if (camErr != ESP_OK) {
    Serial.printf("[CAM] Init failed: 0x%x\n", camErr);
    esp_restart();
  }
  
  // Kết nối WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    Serial.print(".");
    retries++;
  }
  if (WiFi.status() != WL_CONNECTED) esp_restart();
  Serial.printf("\n[WIFI] Connected: %s\n", WiFi.localIP().toString().c_str());
  
  // Kết nối WebSocket
  if (!connectWebSocket()) {
    Serial.println("[WS] Initial connection failed - will retry in loop");
  }
}

void loop() {
  client.poll();  // BẮT BUỘC gọi mỗi loop
  
  if (!wsConnected) {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > 3000) {
      Serial.println("[WS] Reconnecting...");
      connectWebSocket();
      lastRetry = millis();
    }
    return;
  }
  
  if (millis() - lastCapture < CAPTURE_INTERVAL_MS) return;
  lastCapture = millis();
  
  // Kiểm tra heap trước khi chụp
  if (esp_get_free_heap_size() < 50000) {
    Serial.println("[MEM] Low heap - restarting");
    esp_restart();
  }
  
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] Capture failed");
    return;
  }
  
  // Gửi binary frame qua WebSocket
  bool sent = client.sendBinary((char*)fb->buf, fb->len);
  if (!sent) {
    Serial.println("[WS] Send failed");
    wsConnected = false;
  }
  
  esp_camera_fb_return(fb);  // PHẢI return ngay
}
```

---

## 🎨 YÊU CẦU FRONTEND (Light Mode)

### Phong cách bắt buộc

```
- Nền: trắng (#FFFFFF) hoặc xám nhạt (#F8FAFC)
- Card: trắng với shadow-sm, border border-slate-200
- Text chính: slate-800 (#1E293B)
- Text phụ: slate-500 (#64748B)
- Accent: blue-600 (#2563EB) cho buttons và links
- Success/Present: green-500
- Error/Absent: red-500
- Font: Inter (Google Fonts) hoặc system-ui
- Border radius: rounded-xl cho cards, rounded-lg cho buttons
- TUYỆT ĐỐI KHÔNG: backdrop-blur, glassmorphism, bg-slate-900, text-white trên nền tối
```

### `app/templates/attendance.html` — Real-time table

```html
<!--
PHẢI CÓ:
1. <script src="/socket.io/socket.io.js"></script>
2. Kết nối Socket.IO: const socket = io()
3. Lắng nghe event:
   socket.on('attendance_update', (data) => {
     // Thêm row MỚI vào ĐẦU bảng (không reload page)
     // Format: | Thời gian | Họ tên | Mã SV | Lớp | Thiết bị | Trạng thái |
     // Highlight row mới bằng bg-blue-50 rồi fade sau 3 giây
     // Cập nhật counter "Tổng hôm nay" realtime
   })
4. Bảng có phân trang (client-side, 50 records/page)
5. Nút "Export Excel" → GET /api/attendance/export?class_id=...&date=...
6. Filter theo lớp và ngày (dropdown + date picker)
-->
```

### Socket.IO Event Payload (server phải emit đúng format này)

```json
{
  "event": "attendance_update",
  "data": {
    "id": "uuid",
    "student_name": "Nguyen Van A",
    "student_code": "ST001",
    "class_name": "12T1",
    "device_id": "ESP32_CAM_01",
    "confidence": 0.92,
    "status": "present",
    "recorded_at": "2024-01-15T08:30:15.123Z"
  }
}
```

---

## 🚂 RAILWAY DEPLOYMENT

### `Dockerfile`

```dockerfile
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

# Dùng 1 worker (quan trọng! face encodings in-memory)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### `railway.toml`

```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"
healthcheckPath = "/health"
healthcheckTimeout = 300    # dlib build lâu

[env]
PORT = "8000"
```

### `requirements.txt`

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
python-socketio>=5.11.0
asyncpg>=0.29.0
sqlalchemy[asyncio]>=2.0.0
python-multipart>=0.0.6
face-recognition>=1.3.0
numpy>=1.24.0
opencv-python-headless>=4.8.0
Pillow>=10.0.0
python-jose[cryptography]>=3.3.0
openpyxl>=3.1.0
aiofiles>=23.2.0
pydantic-settings>=2.1.0
```

### Biến môi trường Railway (phải set trong Dashboard)

```
DATABASE_URL=postgresql://...    # Tự động set bởi Railway PostgreSQL plugin
SECRET_KEY=<random 32 chars>
ADMIN_PASSWORD=<your password>
UPLOAD_DIR=/app/uploads
MAX_UPLOAD_SIZE_MB=10
FACE_RECOGNITION_TOLERANCE=0.5
CORS_ORIGINS=*
```

---

## ✅ CHECKLIST KIỂM TRA KHI CODEX HOÀN THÀNH

### Backend
- [ ] `GET /health` trả về 200 OK
- [ ] `ws://host/ws/camera?api_key=xxx` nhận binary, trả JSON < 500ms
- [ ] Socket.IO event `attendance_update` broadcast khi có recognition
- [ ] CORS enabled cho tất cả origins
- [ ] Face encodings load từ DB khi startup
- [ ] API key validate từ in-memory cache (không query DB mỗi request)
- [ ] File upload ảnh sinh viên hoạt động, encoding cập nhật RAM ngay

### Database
- [ ] Schema tạo đủ 4 bảng với indexes
- [ ] Migration script từ SQLite cũ sang PostgreSQL mới

### ESP32
- [ ] Connect WiFi → WebSocket WSS trong `setup()`
- [ ] Gửi binary JPEG trong `loop()` mỗi `CAPTURE_INTERVAL_MS`
- [ ] Nhận JSON, parse, in Serial, bật LED
- [ ] Tự reconnect khi mất kết nối
- [ ] Kiểm tra heap, restart nếu low memory

### Frontend
- [ ] Không có màu tối (bg-slate-900, bg-gray-800...) ở bất kỳ đâu
- [ ] Real-time table cập nhật không reload
- [ ] Export Excel hoạt động
- [ ] Filter lớp và ngày hoạt động

### Railway
- [ ] Dockerfile build thành công với dlib
- [ ] `railway.toml` đúng cấu hình
- [ ] Health check pass
- [ ] WebSocket không bị timeout (Railway cho phép 30s idle)

---

## ⚠️ CÁC LỖI PHỔ BIẾN CẦN TRÁNH

1. **Đừng dùng `threading` với asyncpg** — dùng `asyncio` xuyên suốt
2. **Đừng gọi `face_recognition` trực tiếp trong async function** — wrap bằng `loop.run_in_executor(executor, ...)`
3. **Đừng dùng `flask-socketio`** — dùng `python-socketio` với FastAPI ASGIApp
4. **Đừng để ESP32 gửi ảnh liên tục không delay** — sẽ flood WebSocket buffer
5. **Đừng quên `esp_camera_fb_return(fb)`** — leak memory nghiêm trọng
6. **Railway WebSocket cần heartbeat** — server phải gửi ping mỗi 20 giây nếu không có traffic
7. **Đừng dùng multiprocessing** — face encodings in-memory không share qua process
8. **Đừng commit API keys hay passwords** — dùng ENV vars, có `.env.example`

---

## 🔧 LỆNH CHẠY LOCAL (để test trước khi deploy)

```bash
# 1. Tạo venv
python -m venv venv && source venv/bin/activate

# 2. Cài deps
pip install -r requirements.txt

# 3. Start PostgreSQL local (Docker)
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16

# 4. Set env
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/attendance"
export SECRET_KEY="dev-secret-key-change-in-prod"

# 5. Init DB
python scripts/init_db.py

# 6. Chạy server
uvicorn app.main:app --reload --port 8000

# Test WebSocket ESP32 (dùng websocat):
# websocat "ws://localhost:8000/ws/camera?api_key=test&device_id=test" --binary < test_image.jpg
```

---

*Prompt này được tối ưu cho Codex / GPT-4o. Thực hiện tuần tự từ backend → database → ESP32 → frontend → Dockerfile. Kiểm tra checklist trước khi kết thúc.*
