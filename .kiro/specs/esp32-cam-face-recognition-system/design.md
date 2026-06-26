# Design Document: ESP32-CAM Face Recognition Attendance System

## Overview

This document specifies the technical design for the ESP32-CAM Face Recognition Attendance System, a real-time facial recognition-based attendance tracking solution optimized for Railway deployment with PostgreSQL and WebSocket streaming.

### System Purpose

The system provides automated attendance tracking through facial recognition using ESP32-CAM hardware devices. It eliminates manual attendance processes by automatically identifying and recording student presence in real-time, with immediate visual feedback on the device and live dashboard updates for administrators.

### Key Technologies

- **Backend**: FastAPI with Python 3.11+ for async HTTP/WebSocket server
- **Face Recognition**: dlib-based face_recognition library with 128-dimensional encodings
- **Database**: PostgreSQL with asyncpg driver for async operations
- **Real-time Communication**: Socket.IO for browser push notifications, WebSocket binary protocol for ESP32 streaming
- **Hardware**: ESP32-CAM with AI_THINKER camera module
- **Deployment**: Railway platform with Docker containerization
- **Frontend**: Jinja2 templates with Tailwind CSS (light mode)

### High-Level Design Principles

1. **Single Worker Architecture**: The system runs with uvicorn workers=1 to maintain in-memory face encodings cache that cannot be shared across processes
2. **Async-First Design**: All I/O operations use asyncio with asyncpg for database, run_in_executor for CPU-bound face recognition
3. **In-Memory Performance**: Face encodings and API keys are cached in RAM at startup to avoid database queries during recognition
4. **Binary Protocol Efficiency**: ESP32 devices stream raw JPEG frames via WebSocket binary messages, receiving JSON responses (lower overhead than HTTP multipart)
5. **Non-Blocking Recognition**: Face recognition and database saves execute asynchronously without blocking WebSocket responses

---

## Architecture

### System Architecture Diagram

```
┌─────────────────┐
│   ESP32-CAM     │
│  (AI_THINKER)   │
└────────┬────────┘
         │ WSS Binary (JPEG frames)
         │ JSON Responses
         ▼
┌─────────────────────────────────────────┐
│         Railway HTTPS/WSS Proxy         │
└─────────────────┬───────────────────────┘
                  │
         ┌────────▼────────┐
         │   FastAPI App   │
         │  (Uvicorn w=1)  │
         └────────┬────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────┐  ┌──────────┐  ┌──────────┐
│WebSocket│ │Socket.IO │  │  REST    │
│Endpoint │  │  Server  │  │  API     │
└────┬───┘  └─────┬────┘  └────┬─────┘
     │            │             │
     │      ┌─────▼─────┐       │
     │      │ Browser   │       │
     │      │ Clients   │       │
     │      └───────────┘       │
     │                          │
     └─────────┬────────────────┘
               │
    ┌──────────▼───────────┐
    │   Service Layer      │
    ├──────────────────────┤
    │ • Face Service       │
    │ • Auth Service       │
    │ • Socket.IO Service  │
    └──────────┬───────────┘
               │
    ┌──────────▼───────────┐
    │  In-Memory Caches    │
    ├──────────────────────┤
    │ • Face Encodings     │
    │ • API Keys           │
    └──────────────────────┘
               │
    ┌──────────▼───────────┐
    │  PostgreSQL (asyncpg)│
    ├──────────────────────┤
    │ • classes            │
    │ • students           │
    │ • attendance_records │
    │ • api_keys           │
    └──────────────────────┘
```

### Data Flow: Face Recognition

```
1. ESP32-CAM captures JPEG → WebSocket Binary Frame
                              ↓
2. FastAPI WebSocket Handler receives bytes
                              ↓
3. Validate API Key (in-memory cache, no DB query)
                              ↓
4. Extract face encoding (ThreadPoolExecutor)
                              ↓
5. Match against in-memory encodings (ThreadPoolExecutor)
                              ↓
6. Send JSON response → ESP32-CAM (LED feedback)
                              ↓
7. [Async] Save attendance record to PostgreSQL
                              ↓
8. [Async] Broadcast Socket.IO event → Browser Clients
```

### Deployment Architecture

**Railway Platform Components:**
- **Web Service**: FastAPI application container
- **PostgreSQL Plugin**: Managed PostgreSQL database (provides DATABASE_URL)
- **HTTPS/WSS Termination**: Railway automatically provides TLS
- **Environment Variables**: Injected at runtime (SECRET_KEY, ADMIN_PASSWORD, etc.)

**Docker Container Layers:**
- Base: python:3.11-slim
- System deps: cmake, build-essential, libopenblas-dev, liblapack-dev (for dlib)
- Python deps: dlib (cached layer due to slow build), then requirements.txt
- Application code: /app directory
- Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`

---

## Components and Interfaces

### 1. WebSocket Handler (`app/routers/ws_camera.py`)

**Purpose**: Accept binary JPEG frames from ESP32-CAM devices and return JSON recognition results.

**Interface:**
```python
@router.websocket("/ws/camera")
async def websocket_camera(
    websocket: WebSocket,
    api_key: str,
    device_id: str
)
```

**Responsibilities:**
- Validate API key from in-memory cache
- Accept WebSocket connection
- Loop: receive binary frame → face recognition → send JSON response
- Handle disconnections gracefully
- Log all recognition events

**Error Handling:**
- Invalid API key → Close with code 1008 "Invalid API Key"
- No face detected → Send `{"status": "no_face", ...}` response
- Face recognition exception → Log error, send "no_face" response

### 2. Face Recognition Service (`app/services/face_service.py`)

**Purpose**: Manage in-memory face encodings cache and perform face matching.

**Interface:**
```python
class FaceService:
    known_encodings: Dict[str, List[Tuple[np.ndarray, UUID, str, str]]]
    executor: ThreadPoolExecutor
    
    async def load_all_encodings() -> None
    async def encode_face(image_bytes: bytes) -> Optional[np.ndarray]
    async def match_face(encoding: np.ndarray, class_name: Optional[str] = None) -> MatchResult
    async def add_student_encoding(student_id: UUID, image_bytes: bytes) -> None
```

**Data Structures:**
```python
# In-memory encodings organized by class
known_encodings = {
    "12T1": [
        (np.array([...128 floats...]), UUID("..."), "Nguyen Van A", "ST001"),
        (np.array([...128 floats...]), UUID("..."), "Tran Thi B", "ST002"),
    ],
    "10T1": [...]
}

# Match result
@dataclass
class MatchResult:
    matched: bool
    student_id: Optional[UUID]
    student_name: Optional[str]
    student_code: Optional[str]
    class_name: Optional[str]
    confidence: Optional[float]  # 1.0 - face_distance
```

**Threading Model:**
- CPU-bound operations execute in ThreadPoolExecutor with 4 workers
- Async wrappers use `asyncio.get_running_loop().run_in_executor()`
- Face encoding extraction: ~100-200ms per image
- Face matching: ~50-100ms for 100 known faces

### 3. Authentication Service (`app/services/auth_service.py`)

**Purpose**: Manage API key validation with in-memory caching.

**Interface:**
```python
class AuthService:
    active_keys: Set[str]  # SHA256 hashes
    
    async def load_api_keys() -> None
    async def validate_key(api_key: str) -> bool
    async def add_key(api_key: str) -> None
    async def deactivate_key(api_key: str) -> None
```

**Key Hashing:**
```python
# Storage: SHA256 hash
key_hash = hashlib.sha256(api_key.encode()).hexdigest()

# Validation: Hash provided key and check in-memory set
is_valid = hashlib.sha256(provided_key.encode()).hexdigest() in active_keys
```

### 4. Socket.IO Service (`app/services/socketio_service.py`)

**Purpose**: Broadcast real-time attendance updates to browser clients.

**Interface:**
```python
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*'
)

async def broadcast_attendance_update(record: AttendanceRecord) -> None:
    await sio.emit('attendance_update', {
        'id': str(record.id),
        'student_name': record.student.full_name,
        'student_code': record.student.student_code,
        'class_name': record.class_.name,
        'device_id': record.device_id,
        'confidence': record.confidence,
        'status': record.status,
        'recorded_at': record.recorded_at.isoformat()
    })
```

**Integration with FastAPI:**
```python
app = FastAPI()
# ... add routers ...
app = socketio.ASGIApp(sio, app)
```

### 5. REST API Routers

**Attendance Router (`app/routers/attendance.py`):**
- `GET /attendance` → Render attendance page
- `GET /api/attendance/export` → Generate Excel file with filters

**Students Router (`app/routers/students.py`):**
- `GET /students` → Render student management page
- `POST /api/students` → Upload student photo, extract encoding, save to DB
- `GET /api/students` → List students with pagination
- `DELETE /api/students/{id}` → Delete student

**Classes Router (`app/routers/classes.py`):**
- `GET /api/classes` → List all classes
- `POST /api/classes` → Create new class
- `DELETE /api/classes/{id}` → Delete class

**API Keys Router (`app/routers/api_keys.py`):**
- `GET /api_keys` → Render API key management page
- `POST /api/api_keys` → Create new API key
- `DELETE /api/api_keys/{id}` → Deactivate API key

### 6. ESP32-CAM Client (`esp32/esp32_cam_websocket.ino`)

**State Machine:**
```
[INIT]
  ↓ WiFi.begin()
[CONNECTING_WIFI]
  ↓ WiFi.status() == WL_CONNECTED
[CONNECTING_WEBSOCKET]
  ↓ client.connect(url)
[CONNECTED]
  ↓ Loop: capture → send → wait response → delay 1500ms
[PROCESSING]
  ↓ onMessage(JSON)
[RECOGNIZED] → LED green 800ms → [CONNECTED]
[UNKNOWN] → Serial.println → [CONNECTED]
[DISCONNECTED]
  ↓ delay(3000)
  → [CONNECTING_WEBSOCKET]
```

**Key Functions:**
```cpp
void setup() {
    initCamera();
    connectWiFi();
    connectWebSocket();
}

void loop() {
    if (!client.available()) {
        reconnectWebSocket();
    }
    
    captureAndSend();
    delay(CAPTURE_INTERVAL_MS);
    
    if (ESP.getFreeHeap() < 50000) {
        ESP.restart();
    }
}

void captureAndSend() {
    camera_fb_t *fb = esp_camera_fb_get();
    client.sendBinary((char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
}

void onMessageCallback(WebsocketsMessage msg) {
    JsonDocument doc;
    deserializeJson(doc, msg.data());
    
    if (doc["status"] == "recognized") {
        digitalWrite(LED_PIN, HIGH);
        delay(800);
        digitalWrite(LED_PIN, LOW);
    }
}
```

**Configuration (`esp32/config.h`):**
```cpp
#define WIFI_SSID "YourSSID"
#define WIFI_PASSWORD "YourPassword"
#define SERVER_HOST "your-app.railway.app"
#define SERVER_PORT 443
#define WS_PATH "/ws/camera?api_key=YOUR_KEY&device_id=ESP32_01"
#define USE_SSL true

#define CAMERA_MODEL_AI_THINKER
#define CAPTURE_INTERVAL_MS 1500
#define JPEG_QUALITY 12
#define FRAME_SIZE FRAMESIZE_VGA
```

---

## Data Models

### Database Schema

**PostgreSQL Tables (DDL):**

```sql
-- Classes table
CREATE TABLE classes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Students table
CREATE TABLE students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_code VARCHAR(50) UNIQUE NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    image_path TEXT,
    face_encoding BYTEA,  -- Pickled numpy array (128 floats)
    created_at TIMESTAMP DEFAULT NOW()
);

-- Attendance records table
CREATE TABLE attendance_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID REFERENCES students(id) ON DELETE CASCADE,
    class_id UUID REFERENCES classes(id) ON DELETE CASCADE,
    device_id VARCHAR(100),
    confidence FLOAT,
    status VARCHAR(20) DEFAULT 'present',
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- API keys table
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(64) UNIQUE NOT NULL,  -- SHA256 hex string
    label VARCHAR(100),
    class_id UUID REFERENCES classes(id) ON DELETE SET NULL,
    device_id VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP
);

-- Performance indexes
CREATE INDEX idx_attendance_recorded_at ON attendance_records(recorded_at DESC);
CREATE INDEX idx_attendance_class_time ON attendance_records(class_id, recorded_at DESC);
CREATE INDEX idx_students_class ON students(class_id);
CREATE INDEX idx_api_keys_active ON api_keys(is_active) WHERE is_active = TRUE;
```

### SQLAlchemy Models (`app/models.py`)

```python
from sqlalchemy import Column, String, Float, Boolean, ForeignKey, LargeBinary, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

class Class(Base):
    __tablename__ = "classes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    students = relationship("Student", back_populates="class_", cascade="all, delete-orphan")
    attendance_records = relationship("AttendanceRecord", back_populates="class_")

class Student(Base):
    __tablename__ = "students"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_code = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"))
    image_path = Column(Text)
    face_encoding = Column(LargeBinary)  # Pickled numpy array
    created_at = Column(DateTime, default=datetime.utcnow)
    
    class_ = relationship("Class", back_populates="students")
    attendance_records = relationship("AttendanceRecord", back_populates="student")

class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"))
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"))
    device_id = Column(String(100))
    confidence = Column(Float)
    status = Column(String(20), default="present")
    recorded_at = Column(DateTime, default=datetime.utcnow)
    
    student = relationship("Student", back_populates="attendance_records")
    class_ = relationship("Class", back_populates="attendance_records")

class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash = Column(String(64), unique=True, nullable=False)
    label = Column(String(100))
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL"))
    device_id = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)
```

### Pydantic Schemas (`app/schemas.py`)

```python
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import Optional

class ClassCreate(BaseModel):
    name: str = Field(..., max_length=100)

class ClassRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class StudentCreate(BaseModel):
    student_code: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=200)
    class_id: UUID

class StudentRead(BaseModel):
    id: UUID
    student_code: str
    full_name: str
    class_id: UUID
    image_path: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class AttendanceRecordRead(BaseModel):
    id: UUID
    student_id: UUID
    class_id: UUID
    device_id: Optional[str]
    confidence: Optional[float]
    status: str
    recorded_at: datetime
    student_name: str
    student_code: str
    class_name: str
    
    class Config:
        from_attributes = True

class APIKeyCreate(BaseModel):
    label: str = Field(..., max_length=100)
    class_id: Optional[UUID]
    device_id: Optional[str]

class APIKeyRead(BaseModel):
    id: UUID
    label: str
    device_id: Optional[str]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
```

### Face Encoding Serialization

**Serialization Format**: Python pickle (binary protocol)

**Encoding Process:**
```python
# Save to database
face_encoding_numpy = np.array([...128 floats...])  # dlib output
face_encoding_bytes = pickle.dumps(face_encoding_numpy)
# Store in students.face_encoding BYTEA column

# Load from database
face_encoding_bytes = row['face_encoding']
face_encoding_numpy = pickle.loads(face_encoding_bytes)
```

**Storage Size**: ~1KB per encoding (128 floats × 8 bytes + pickle overhead)

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Applicability of Property-Based Testing

This system is primarily **integration-heavy**, involving:
- ESP32 hardware communication
- External libraries (face_recognition, dlib)
- PostgreSQL database operations
- WebSocket and Socket.IO protocols
- Browser UI interactions

However, there are **critical pure functions and data transformations** suitable for property-based testing, particularly around:
- **Serialization/deserialization** of face encodings
- **JSON message formatting** for WebSocket responses
- **Data structure validation** for outputs
- **Cache consistency** for in-memory state

The following properties focus on these testable aspects while acknowledging that most system functionality requires integration testing.

---

### Property 1: Face Encoding Serialization Round-Trip

*For any* valid 128-dimensional numpy face encoding array, serializing with pickle.dumps() then deserializing with pickle.loads() SHALL produce an array equivalent to the original (element-wise equality within floating-point tolerance).

**Validates: Requirements 21.3**

**Rationale**: Face encodings are the core data structure for recognition. Corruption during serialization would cause recognition failures. This property ensures data integrity across the database boundary.

**Test Implementation**:
```python
@given(st.lists(st.floats(min_value=-10.0, max_value=10.0), min_size=128, max_size=128))
def test_face_encoding_round_trip(encoding_list):
    original = np.array(encoding_list, dtype=np.float64)
    serialized = pickle.dumps(original)
    deserialized = pickle.loads(serialized)
    assert np.allclose(original, deserialized, rtol=1e-9, atol=1e-9)
```

---

### Property 2: JSON Response Structure and Validation

*For any* recognition result (recognized, unknown, or no_face status), the generated JSON response SHALL:
1. Contain all required keys: status, name, student_id, class_name, confidence, timestamp, device_id
2. Have status field as one of: "recognized", "unknown", "no_face"
3. When status is "recognized", fields name, student_id, class_name, confidence SHALL be non-null
4. When status is "unknown" or "no_face", fields name, student_id, class_name, confidence SHALL be null
5. Have timestamp field as a valid ISO 8601 formatted string in UTC timezone

**Validates: Requirements 22.1, 22.2, 22.3, 22.4, 22.5**

**Rationale**: ESP32 clients depend on well-formed JSON responses for LED feedback and logging. Malformed responses cause client crashes. This property ensures message contract integrity.

**Test Implementation**:
```python
@given(
    status=st.sampled_from(["recognized", "unknown", "no_face"]),
    name=st.text() | st.none(),
    student_id=st.uuids() | st.none(),
    class_name=st.text() | st.none(),
    confidence=st.floats(min_value=0.0, max_value=1.0) | st.none(),
    device_id=st.text()
)
def test_json_response_structure(status, name, student_id, class_name, confidence, device_id):
    response = create_recognition_response(status, name, student_id, class_name, confidence, device_id)
    
    # All required keys present
    assert all(key in response for key in ["status", "name", "student_id", "class_name", "confidence", "timestamp", "device_id"])
    
    # Status is valid enum
    assert response["status"] in ["recognized", "unknown", "no_face"]
    
    # Conditional non-null/null validation
    if response["status"] == "recognized":
        assert response["name"] is not None
        assert response["student_id"] is not None
        assert response["class_name"] is not None
        assert response["confidence"] is not None
    else:
        assert response["name"] is None
        assert response["student_id"] is None
        assert response["class_name"] is None
        assert response["confidence"] is None
    
    # Timestamp is valid ISO 8601 UTC
    datetime.fromisoformat(response["timestamp"].replace("Z", "+00:00"))
```

---

### Property 3: Student Encoding Cache Consistency

*For any* new student with a valid face encoding added to the database, the in-memory face encodings cache SHALL be updated immediately such that a subsequent face matching query includes the new student as a candidate without requiring application restart.

**Validates: Requirements 2.3**

**Rationale**: The single-worker architecture relies on in-memory caching for performance. Cache staleness would cause newly registered students to not be recognized until restart, breaking the user experience.

**Test Implementation**:
```python
@given(
    student_code=st.text(min_size=1, max_size=50),
    full_name=st.text(min_size=1, max_size=200),
    class_name=st.text(min_size=1, max_size=100),
    encoding=st.lists(st.floats(min_value=-10.0, max_value=10.0), min_size=128, max_size=128)
)
async def test_student_cache_consistency(student_code, full_name, class_name, encoding):
    face_service = FaceService()
    initial_count = len(face_service.known_encodings.get(class_name, []))
    
    # Add student with encoding
    await face_service.add_student_encoding(student_code, full_name, class_name, np.array(encoding))
    
    # Verify cache updated immediately
    updated_count = len(face_service.known_encodings.get(class_name, []))
    assert updated_count == initial_count + 1
    
    # Verify the specific student is in cache
    class_encodings = face_service.known_encodings[class_name]
    assert any(meta[2] == student_code for _, _, meta, _ in class_encodings)
```

---

### Property 4: Best Match Selection

*For any* unknown face encoding and a non-empty set of known face encodings, when matching with a tolerance threshold, the face recognition service SHALL return the known encoding with the minimum face distance if and only if that distance is below the tolerance threshold.

**Validates: Requirements 2.5**

**Rationale**: Incorrect match selection could return wrong students or reject valid matches. This property ensures the matching algorithm always selects the closest match when available.

**Test Implementation**:
```python
@given(
    unknown_encoding=st.lists(st.floats(min_value=-10.0, max_value=10.0), min_size=128, max_size=128),
    known_encodings=st.lists(
        st.tuples(
            st.lists(st.floats(min_value=-10.0, max_value=10.0), min_size=128, max_size=128),
            st.uuids(),
            st.text(),
            st.text()
        ),
        min_size=1,
        max_size=10
    ),
    tolerance=st.floats(min_value=0.1, max_value=0.9)
)
async def test_best_match_selection(unknown_encoding, known_encodings, tolerance):
    face_service = FaceService()
    face_service.tolerance = tolerance
    
    unknown_np = np.array(unknown_encoding)
    known_np_list = [(np.array(enc), sid, name, code) for enc, sid, name, code in known_encodings]
    
    # Calculate distances manually
    distances = [np.linalg.norm(unknown_np - known_enc) for known_enc, _, _, _ in known_np_list]
    min_distance = min(distances)
    min_index = distances.index(min_distance)
    
    result = await face_service.match_face(unknown_np, known_encodings=known_np_list)
    
    if min_distance < tolerance:
        assert result.matched is True
        assert result.student_id == known_np_list[min_index][1]
    else:
        assert result.matched is False
```

---

### Property 5: API Key Cache Consistency

*For any* API key creation or deactivation operation in the database, the in-memory API key cache SHALL be updated immediately such that subsequent authentication requests reflect the current state without requiring application restart.

**Validates: Requirements 4.3**

**Rationale**: Stale API key cache would allow revoked keys to continue working or prevent newly created keys from being used, creating security vulnerabilities and operational issues.

**Test Implementation**:
```python
@given(
    api_key=st.text(min_size=16, max_size=64),
    operation=st.sampled_from(["create", "deactivate"])
)
async def test_api_key_cache_consistency(api_key, operation):
    auth_service = AuthService()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    if operation == "create":
        # Add key to database and cache
        await auth_service.add_key(api_key)
        assert key_hash in auth_service.active_keys
        assert await auth_service.validate_key(api_key) is True
        
    elif operation == "deactivate":
        # First create, then deactivate
        await auth_service.add_key(api_key)
        await auth_service.deactivate_key(api_key)
        assert key_hash not in auth_service.active_keys
        assert await auth_service.validate_key(api_key) is False
```

---

### Property 6: Socket.IO Event Payload Structure

*For any* attendance record that triggers a Socket.IO broadcast, the `attendance_update` event payload SHALL contain all required fields: id, student_name, student_code, class_name, device_id, confidence, status, recorded_at with correct types (UUID as string, floats, strings, ISO 8601 timestamp).

**Validates: Requirements 5.2**

**Rationale**: Browser clients depend on complete event payloads to update the UI. Missing fields cause JavaScript errors and prevent real-time updates.

**Test Implementation**:
```python
@given(
    student_name=st.text(min_size=1, max_size=200),
    student_code=st.text(min_size=1, max_size=50),
    class_name=st.text(min_size=1, max_size=100),
    device_id=st.text(min_size=1, max_size=100) | st.none(),
    confidence=st.floats(min_value=0.0, max_value=1.0),
    status=st.sampled_from(["present", "absent", "late"])
)
def test_socketio_payload_structure(student_name, student_code, class_name, device_id, confidence, status):
    record = create_attendance_record(student_name, student_code, class_name, device_id, confidence, status)
    payload = create_socketio_payload(record)
    
    # All required fields present
    required_fields = ["id", "student_name", "student_code", "class_name", "device_id", "confidence", "status", "recorded_at"]
    assert all(field in payload for field in required_fields)
    
    # Type validation
    assert isinstance(payload["id"], str)  # UUID as string
    assert isinstance(payload["student_name"], str)
    assert isinstance(payload["student_code"], str)
    assert isinstance(payload["class_name"], str)
    assert isinstance(payload["confidence"], float)
    assert isinstance(payload["status"], str)
    
    # Timestamp is valid ISO 8601
    datetime.fromisoformat(payload["recorded_at"].replace("Z", "+00:00"))
```

---

### Property 7: Excel Export Column Structure

*For any* set of attendance records exported to Excel format, the generated workbook SHALL contain all required columns: Timestamp, Student Name, Student Code, Class, Device, Status, Confidence, in the correct order with proper headers.

**Validates: Requirements 10.2**

**Rationale**: Excel exports are used for official reporting. Missing columns or incorrect structure would make reports unusable for administration.

**Test Implementation**:
```python
@given(
    attendance_records=st.lists(
        st.builds(
            AttendanceRecord,
            student_name=st.text(min_size=1, max_size=200),
            student_code=st.text(min_size=1, max_size=50),
            class_name=st.text(min_size=1, max_size=100),
            device_id=st.text() | st.none(),
            confidence=st.floats(min_value=0.0, max_value=1.0),
            status=st.sampled_from(["present", "absent", "late"])
        ),
        min_size=0,
        max_size=50
    )
)
def test_excel_export_column_structure(attendance_records):
    excel_bytes = generate_attendance_excel(attendance_records)
    workbook = openpyxl.load_workbook(BytesIO(excel_bytes))
    sheet = workbook.active
    
    # Verify header row
    expected_headers = ["Timestamp", "Student Name", "Student Code", "Class", "Device", "Status", "Confidence"]
    actual_headers = [cell.value for cell in sheet[1]]
    assert actual_headers == expected_headers
    
    # Verify data rows match record count
    assert sheet.max_row == len(attendance_records) + 1  # +1 for header
```

---

## Error Handling

### WebSocket Connection Errors

**Invalid API Key**:
- **Detection**: API key not found in in-memory cache during connection handshake
- **Response**: Close WebSocket with code 1008 (Policy Violation) and reason "Invalid API Key"
- **Logging**: Log warning with attempted API key (first 8 chars) and device_id
- **ESP32 Behavior**: Retry connection after 3 seconds (may require config update if key is revoked)

**Connection Timeout**:
- **Detection**: No activity on WebSocket for Railway's idle timeout (30 seconds)
- **Response**: Connection automatically closed by Railway proxy
- **ESP32 Behavior**: Detect disconnection, attempt reconnection with exponential backoff (3s, 6s, 12s, max 30s)

**Malformed Binary Frame**:
- **Detection**: Binary data cannot be decoded as JPEG image
- **Response**: Log error, send JSON response `{"status": "no_face", ...}` with null fields
- **ESP32 Behavior**: Continue sending next frame after delay
- **Prevention**: ESP32 validates camera buffer before sending

### Face Recognition Errors

**No Face Detected**:
- **Detection**: `face_recognition.face_encodings()` returns empty list
- **Response**: Send JSON `{"status": "no_face", "name": null, "student_id": null, "class_name": null, "confidence": null, "timestamp": "...", "device_id": "..."}`
- **Logging**: Log info-level message with device_id
- **ESP32 Behavior**: No LED feedback, continue capturing

**Multiple Faces Detected**:
- **Detection**: `face_recognition.face_encodings()` returns list with >1 element
- **Response**: Use first detected face encoding, log warning
- **Alternative Design**: Reject frame with "multiple_faces" status (not implemented in v1)

**Face Recognition Library Exception**:
- **Detection**: `face_recognition.face_encodings()` or `face_distance()` raises exception
- **Response**: Log error with full traceback, send "no_face" response
- **Recovery**: Continue processing next frame (no service restart)
- **Monitoring**: Track error rate for alerting

**No Match Found**:
- **Detection**: All face distances exceed tolerance threshold (0.5)
- **Response**: Send JSON `{"status": "unknown", "name": null, ...}`
- **Logging**: Log info-level with device_id and minimum distance
- **ESP32 Behavior**: Log to Serial, no LED feedback

### Database Errors

**Connection Failure at Startup**:
- **Detection**: asyncpg connection pool creation fails
- **Response**: Log critical error, exit application (Railway will restart container)
- **Prevention**: Railway automatically provides DATABASE_URL
- **Recovery**: Automatic restart with exponential backoff

**Query Failure During Save**:
- **Detection**: INSERT into attendance_records fails (constraint violation, connection loss)
- **Response**: Log error with full context (student_id, class_id, device_id)
- **Recovery**: Face recognition response already sent to ESP32, so continue processing
- **Impact**: Attendance record lost for this recognition (UI not updated)
- **Mitigation**: Implement retry with exponential backoff (3 attempts) for transient errors

**Face Encoding Deserialization Error**:
- **Detection**: `pickle.loads()` fails on corrupted BYTEA data
- **Response**: Log error with student_id, skip this encoding during cache load
- **Recovery**: System continues with remaining valid encodings
- **Fix**: Admin must re-upload student photo

### File Upload Errors

**Invalid Image Format**:
- **Detection**: File is not JPEG/PNG or cannot be decoded
- **Response**: Return HTTP 400 with error message "Invalid image format"
- **UI Feedback**: Show error alert to user

**File Size Exceeded**:
- **Detection**: Upload size > MAX_UPLOAD_SIZE_MB (10MB)
- **Response**: FastAPI automatically returns HTTP 413 (Payload Too Large)
- **Prevention**: Client-side validation before upload

**No Face in Uploaded Image**:
- **Detection**: `face_recognition.face_encodings()` returns empty list
- **Response**: Return HTTP 400 with error message "No face detected in image. Please upload a clear photo with one face."
- **UI Feedback**: Show error alert, allow retry

**Face Encoding Save Failure**:
- **Detection**: Database INSERT fails after successful face encoding
- **Response**: Return HTTP 500 with error message "Failed to save student"
- **Recovery**: User retries upload (idempotent with student_code unique constraint)

### Memory Management (ESP32)

**Low Heap Memory**:
- **Detection**: `ESP.getFreeHeap() < 50000` (50KB threshold)
- **Response**: Log warning to Serial, call `esp_restart()`
- **Prevention**: Always call `esp_camera_fb_return(fb)` immediately after sending frame
- **Monitoring**: Log heap usage every 100 frames

**Camera Frame Buffer Leak**:
- **Detection**: Gradual heap reduction over time
- **Response**: Automatic restart when heap hits threshold
- **Prevention**: Strict RAII pattern: `fb_get()` → `send()` → `fb_return()` without early returns

### Cache Consistency Errors

**Face Encodings Cache Out of Sync**:
- **Scenario**: Admin deletes student via direct database query (bypassing API)
- **Detection**: In-memory cache contains deleted student
- **Impact**: Deleted student can still be recognized until restart
- **Prevention**: Always use API endpoints that update cache
- **Recovery**: Manual restart or implement cache invalidation API

**API Key Cache Out of Sync**:
- **Scenario**: API key deactivated via direct database update
- **Detection**: Deactivated key still accepted
- **Impact**: Revoked device can continue accessing system
- **Prevention**: Always use API endpoints that update cache
- **Recovery**: Manual restart or implement cache invalidation API

### Socket.IO Broadcasting Errors

**No Connected Clients**:
- **Detection**: `sio.emit()` with zero connected clients
- **Response**: No-op (broadcast silently ignored)
- **Impact**: No impact, attendance record still saved

**Socket.IO Emit Failure**:
- **Detection**: Exception during `sio.emit()`
- **Response**: Log error, continue processing (don't block WebSocket response)
- **Recovery**: Browser clients reconnect automatically, fetch latest data on page load

### Railway Deployment Errors

**Health Check Failure**:
- **Detection**: `/health` endpoint returns non-200 or times out
- **Response**: Railway marks container as unhealthy, may restart
- **Prevention**: `/health` endpoint is simple synchronous check `{"status": "ok"}`

**Build Timeout**:
- **Detection**: Docker build exceeds Railway's timeout (30 minutes)
- **Response**: Build fails, no deployment
- **Prevention**: Cache dlib build layer in Dockerfile, use multi-stage build if needed

**Environment Variable Missing**:
- **Detection**: Pydantic settings validation fails at startup
- **Response**: Log error with missing variable name, exit application
- **Prevention**: `.env.example` documents all required variables

---

## Testing Strategy

### Overview

This system uses a **layered testing approach** combining property-based testing for core transformations, unit tests for specific behaviors, integration tests for external dependencies, and end-to-end tests for complete workflows.

**Testing Philosophy**:
- **Property-based tests** verify universal correctness properties (serialization, message formats, data structures)
- **Unit tests** verify specific examples and edge cases
- **Integration tests** verify external system interactions (database, WebSocket, Socket.IO, ESP32 hardware)
- **Property tests run 100+ iterations** to catch edge cases through randomization
- **Unit tests focus on concrete examples** and boundary conditions

### Property-Based Testing

**Library**: Hypothesis for Python

**Configuration**:
```python
from hypothesis import settings, Verbosity

# Minimum 100 iterations per property test
settings.register_profile("default", max_examples=100)
settings.register_profile("ci", max_examples=200, verbosity=Verbosity.verbose)
```

**Test Organization**:
- Location: `tests/properties/test_*.py`
- Naming: `test_property_{number}_{description}`
- Tags: Each test includes comment with design document reference

**Example Test Structure**:
```python
# Feature: esp32-cam-face-recognition-system, Property 1: Face Encoding Serialization Round-Trip
@given(st.lists(st.floats(min_value=-10.0, max_value=10.0), min_size=128, max_size=128))
@settings(max_examples=100)
def test_property_1_face_encoding_round_trip(encoding_list):
    original = np.array(encoding_list, dtype=np.float64)
    serialized = pickle.dumps(original)
    deserialized = pickle.loads(serialized)
    assert np.allclose(original, deserialized, rtol=1e-9, atol=1e-9)
```

**Property Test Suite**:

1. **Face Encoding Serialization** (`test_properties_face_encoding.py`)
   - Property 1: Round-trip preservation
   - Generators: Random 128-dimensional float arrays
   - Tag: `# Feature: esp32-cam-face-recognition-system, Property 1`

2. **JSON Response Formatting** (`test_properties_json_response.py`)
   - Property 2: Structure validation, enum constraints, conditional nullability, ISO 8601 timestamps
   - Generators: Random status, names, UUIDs, confidence scores
   - Tag: `# Feature: esp32-cam-face-recognition-system, Property 2`

3. **Cache Consistency** (`test_properties_cache.py`)
   - Property 3: Student encoding cache updates
   - Property 5: API key cache updates
   - Generators: Random student data, API keys, operations
   - Tags: `# Feature: esp32-cam-face-recognition-system, Property 3`, `Property 5`

4. **Face Matching** (`test_properties_matching.py`)
   - Property 4: Best match selection
   - Generators: Random encodings, distance thresholds
   - Tag: `# Feature: esp32-cam-face-recognition-system, Property 4`

5. **Event Payloads** (`test_properties_events.py`)
   - Property 6: Socket.IO payload structure
   - Property 7: Excel export columns
   - Generators: Random attendance records
   - Tags: `# Feature: esp32-cam-face-recognition-system, Property 6`, `Property 7`

### Unit Testing

**Library**: pytest with pytest-asyncio

**Focus Areas**:

1. **Face Service Unit Tests** (`tests/unit/test_face_service.py`)
   - Specific examples: Known matching faces, known non-matching faces
   - Edge cases: Empty encoding list, single encoding, all below/above threshold
   - Error cases: Invalid numpy array shapes, None values

2. **Auth Service Unit Tests** (`tests/unit/test_auth_service.py`)
   - API key hashing: Verify SHA256 output format (64 hex chars)
   - Cache operations: Add, deactivate, validate specific keys
   - Edge cases: Empty cache, duplicate keys, malformed keys

3. **WebSocket Handler Unit Tests** (`tests/unit/test_ws_handler.py`)
   - Connection acceptance: Valid API key
   - Connection rejection: Invalid API key, missing parameters
   - Response formatting: Recognized, unknown, no_face statuses

4. **Excel Export Unit Tests** (`tests/unit/test_excel_export.py`)
   - Empty record set: Header row only
   - Single record: Correct data types
   - Date filtering: Boundary conditions (midnight, timezone)

### Integration Testing

**Focus Areas**:

1. **Database Integration** (`tests/integration/test_database.py`)
   - Connection pool creation with asyncpg
   - CRUD operations for all tables
   - Face encoding storage and retrieval with pickle
   - Index usage verification with EXPLAIN ANALYZE
   - Transaction rollback and error recovery

2. **WebSocket Integration** (`tests/integration/test_websocket.py`)
   - Binary frame upload with test JPEG images
   - JSON response parsing
   - Connection stability over 60 seconds
   - Reconnection after disconnect
   - Concurrent connections from multiple "devices"

3. **Socket.IO Integration** (`tests/integration/test_socketio.py`)
   - Client connection and event reception
   - Broadcast to multiple clients
   - Message ordering and delivery guarantees

4. **Face Recognition Library Integration** (`tests/integration/test_face_recognition.py`)
   - Known test images: Verify expected matches
   - No face images: Verify no_face response
   - Multiple face images: Verify first face used
   - Performance: Measure encoding time (<200ms target)

### ESP32 Hardware Testing

**Test Setup**:
- Physical ESP32-CAM device with AI_THINKER module
- Test server running locally or on Railway staging environment
- Serial monitor for log capture

**Test Scenarios**:

1. **Connection Lifecycle** (`tests/hardware/test_esp32_connection.ino`)
   - Power on → WiFi connect → WebSocket connect
   - Measure time to first frame send
   - Verify reconnection after server restart
   - Verify reconnection after WiFi drop

2. **Memory Stability** (`tests/hardware/test_esp32_memory.ino`)
   - Capture and send 1000 frames
   - Log heap usage every 100 frames
   - Verify no gradual memory leak
   - Verify automatic restart on low heap

3. **Recognition Feedback** (`tests/hardware/test_esp32_feedback.ino`)
   - Present known face → Verify LED green for 800ms
   - Present unknown face → Verify Serial log only
   - Present no face → Verify no LED, no excessive Serial spam

4. **Network Resilience** (`tests/hardware/test_esp32_network.ino`)
   - Disconnect WebSocket server → Verify 3s reconnect attempts
   - Introduce network latency → Verify timeout handling
   - Long idle periods → Verify connection maintained

### End-to-End Testing

**Test Scenarios**:

1. **Complete Recognition Flow**
   - Admin uploads student photo via web UI
   - Face encoding extracted and cached
   - ESP32 captures student's face
   - Server recognizes student, saves record
   - Browser dashboard updates in real-time (<2s total)

2. **Excel Export Flow**
   - Generate attendance records via ESP32 recognitions
   - Apply class and date filters on web UI
   - Click export button
   - Verify Excel file downloads with filtered records

3. **API Key Management Flow**
   - Admin creates new API key via web UI
   - Configure ESP32 with new key
   - ESP32 connects and sends frames
   - Admin deactivates key via web UI
   - ESP32 connection rejected (next reconnect attempt)

### Performance Testing

**Latency Targets**:
- WebSocket frame → JSON response: <500ms (p95)
- Face encoding extraction: <200ms
- Face matching (100 known faces): <100ms
- Database save (async): <50ms
- Socket.IO broadcast: <10ms

**Load Testing Scenarios**:

1. **Single Device Sustained Load** (`tests/performance/test_single_device.py`)
   - 1 ESP32 sending frames every 1.5s for 30 minutes
   - Measure response time percentiles (p50, p95, p99)
   - Verify no memory leaks in server process

2. **Multiple Device Concurrent Load** (`tests/performance/test_concurrent_devices.py`)
   - 10 simulated ESP32 clients sending frames concurrently
   - Measure throughput (frames/second)
   - Verify ThreadPoolExecutor handles load without blocking

3. **Database Query Performance** (`tests/performance/test_db_queries.py`)
   - Insert 10,000 attendance records
   - Query with class+date filters
   - Verify index usage, measure query time (<100ms)

### Test Execution

**Local Development**:
```bash
# Run all tests
pytest

# Run property tests only
pytest tests/properties/ -v

# Run specific property test
pytest tests/properties/test_properties_face_encoding.py::test_property_1_face_encoding_round_trip -v

# Run integration tests (requires PostgreSQL)
pytest tests/integration/ --asyncio-mode=auto

# Run with coverage
pytest --cov=app --cov-report=html
```

**CI/CD (GitHub Actions)**:
```yaml
- name: Run Property Tests
  run: pytest tests/properties/ --hypothesis-profile=ci -v

- name: Run Unit Tests
  run: pytest tests/unit/ -v

- name: Run Integration Tests
  run: pytest tests/integration/ --asyncio-mode=auto
  env:
    DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}
```

**Coverage Targets**:
- Property tests: 100% of identified properties
- Unit tests: 80% line coverage for services and routers
- Integration tests: All critical paths (connection, recognition, database save, broadcast)

---

## Performance Considerations

### Latency Optimization

**In-Memory Caching**:
- Face encodings and API keys loaded at startup
- Zero database queries during recognition processing
- Cache updates happen asynchronously after responses sent

**Async Non-Blocking Architecture**:
- WebSocket response sent before database save
- Socket.IO broadcast doesn't block WebSocket handler
- ThreadPoolExecutor isolates CPU-bound operations from event loop

**Database Indexing**:
- `recorded_at DESC` index for recent attendance queries
- `(class_id, recorded_at DESC)` composite index for filtered queries
- UUID primary keys with gen_random_uuid() for distributed generation

### Scalability Limitations

**Single Worker Constraint**:
- In-memory cache cannot be shared across processes
- Vertical scaling only (more CPU cores benefit ThreadPoolExecutor)
- Maximum throughput: ~20 concurrent ESP32 devices per worker

**Mitigation Strategies**:
- **Vertical scaling**: Increase Railway container CPU allocation
- **Future: Redis cache**: Replace in-memory dict with Redis for multi-worker support
- **Future: PostgreSQL read replicas**: Offload Excel export queries

### Memory Usage

**Server (per worker)**:
- Base Python + FastAPI: ~100MB
- dlib library: ~50MB
- Face encodings cache (100 students): ~100KB
- API keys cache: ~10KB
- Total: ~150MB resident

**ESP32-CAM**:
- Camera buffer (VGA JPEG): ~15KB
- WiFi stack: ~40KB
- Free heap target: >50KB
- Total PSRAM: 4MB (sufficient)

### Network Bandwidth

**ESP32 Upload**:
- VGA JPEG (quality 12): ~15KB per frame
- 1 frame per 1.5s = 10KB/s per device
- 10 devices = 100KB/s = 800 Kbps
- Railway bandwidth: More than sufficient

**Browser Download**:
- Socket.IO event payload: ~200 bytes per attendance record
- Negligible bandwidth for real-time updates

---

## Deployment Configuration

### Dockerfile

**Build Strategy**: Multi-layer caching to optimize dlib build time

```dockerfile
FROM python:3.11-slim as builder

# Install system dependencies for dlib
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dlib separately to cache this slow layer
RUN pip install --no-cache-dir dlib==19.24.2

FROM python:3.11-slim

# Copy dlib from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libopenblas-base \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app
COPY scripts ./scripts

# Railway provides PORT environment variable
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

### railway.toml

```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3

[[deploy.environmentVariables]]
name = "PYTHONUNBUFFERED"
value = "1"
```

### Environment Variables

**Required** (set in Railway dashboard):
- `DATABASE_URL`: Auto-provided by PostgreSQL plugin
- `SECRET_KEY`: Random 32-byte hex string for session security
- `ADMIN_PASSWORD`: Admin dashboard password (bcrypt hashed)

**Optional** (with defaults):
- `UPLOAD_DIR`: `/app/uploads` (default)
- `MAX_UPLOAD_SIZE_MB`: `10` (default)
- `FACE_RECOGNITION_TOLERANCE`: `0.5` (default)
- `CORS_ORIGINS`: `*` (allow all, restrict in production)
- `LOG_LEVEL`: `INFO` (default, use `DEBUG` for troubleshooting)

### Database Initialization

**One-Time Setup** (run after first deployment):
```bash
# SSH into Railway container
railway run python scripts/init_db.py
```

**Script** (`scripts/init_db.py`):
```python
import asyncio
import asyncpg
from app.config import settings

async def init_db():
    conn = await asyncpg.connect(settings.DATABASE_URL)
    
    # Create tables with idempotent DDL
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS classes (...);
        CREATE TABLE IF NOT EXISTS students (...);
        CREATE TABLE IF NOT EXISTS attendance_records (...);
        CREATE TABLE IF NOT EXISTS api_keys (...);
        
        CREATE INDEX IF NOT EXISTS idx_attendance_recorded_at ...;
        CREATE INDEX IF NOT EXISTS idx_attendance_class_time ...;
    """)
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(init_db())
```

### Monitoring and Logging

**Logging Configuration**:
```python
import logging
from app.config import settings

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
```

**Key Metrics to Monitor**:
- WebSocket connection count (gauge)
- Face recognition latency (histogram)
- Database query duration (histogram)
- Cache hit rate (counter)
- Error rate by type (counter)
- Memory usage (gauge)
- ESP32 reconnection rate (counter)

**Railway Logs**:
- Automatically collected from stdout/stderr
- Accessible via Railway dashboard or CLI
- Retention: 7 days on free plan, configurable on paid plans

---

## Security Considerations

### API Key Security

**Storage**: SHA256 hashes in database, never plaintext
**Transmission**: Over WSS (TLS encrypted) only
**Rotation**: Admin can deactivate and create new keys via web UI
**Scope**: Keys can be scoped to specific classes and devices

### Face Encoding Privacy

**Storage**: Face encodings are mathematical representations, not reversible to original photos
**GDPR Compliance**: Face encodings are biometric data, require consent and right-to-deletion
**Deletion**: CASCADE delete from students table removes all encodings and attendance records

### Network Security

**TLS/WSS**: Railway provides automatic HTTPS/WSS termination
**CORS**: Configurable via environment variable, default allows all for development
**API Authentication**: All WebSocket connections require valid API key
**Admin Dashboard**: Password-protected (bcrypt hashed password)

### Input Validation

**File Uploads**: FastAPI validators limit size (10MB) and MIME types (image/jpeg, image/png)
**WebSocket Frames**: Binary data validated as JPEG before processing
**SQL Injection**: SQLAlchemy ORM and asyncpg parameterized queries prevent injection
**XSS**: Jinja2 templates auto-escape HTML by default

---

## Future Enhancements

### Multi-Worker Support with Redis

**Current Limitation**: Single worker due to in-memory caching
**Solution**: Replace in-memory dicts with Redis
**Benefits**: Horizontal scaling, multiple Railway instances
**Implementation**: Redis Sorted Sets for face encodings, Redis Sets for API keys

### Advanced Recognition Features

**Liveness Detection**: Prevent photo spoofing attacks
**Face Quality Scoring**: Reject blurry or poorly lit images before recognition
**Multiple Face Handling**: Track multiple students in group settings
**Expression Invariance**: Improve recognition with different facial expressions

### Analytics and Reporting

**Attendance Analytics**: Daily/weekly/monthly attendance rates
**Student Insights**: Punctuality trends, absence patterns
**Device Health**: ESP32 memory usage trends, reconnection frequency
**Recognition Accuracy**: Track confidence scores over time

### Mobile App Integration

**Progressive Web App**: Offline-capable attendance dashboard
**Push Notifications**: Real-time attendance alerts to teachers
**QR Code Fallback**: Manual attendance for recognition failures

---

## Appendix: Technology Decisions

### Why FastAPI over Flask?

- Native async/await support for PostgreSQL and WebSocket
- Automatic OpenAPI documentation
- Pydantic data validation
- Better performance for I/O-bound operations

### Why asyncpg over psycopg2?

- True async PostgreSQL driver (no thread pool hack)
- 3x faster than psycopg2 in benchmarks
- Native asyncio integration

### Why dlib over OpenCV for Face Recognition?

- 128-dimensional encodings more accurate than OpenCV's face recognition
- Pretrained model (ResNet) works out-of-the-box
- Widely adopted face_recognition library wraps dlib

### Why pickle for Face Encoding Serialization?

- Native Python serialization for numpy arrays
- Compact binary format (~1KB per encoding)
- Fast serialize/deserialize (<1ms)
- Alternative: JSON with base64 (3x larger, slower)

### Why Single Worker Architecture?

- In-memory caching simplifies architecture (no Redis dependency)
- Face recognition is CPU-bound (vertical scaling more cost-effective)
- Railway free tier supports sufficient load for MVP (20 devices)
- Can migrate to Redis cache if horizontal scaling needed

---

