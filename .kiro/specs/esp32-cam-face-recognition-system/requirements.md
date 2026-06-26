# Requirements Document: ESP32-CAM Face Recognition Attendance System

## Introduction

This document specifies the requirements for the ESP32-CAM Face Recognition Attendance System, a real-time facial recognition-based attendance tracking solution optimized for Railway deployment. The system uses FastAPI with WebSocket for binary image streaming from ESP32-CAM devices, PostgreSQL for data persistence, and Socket.IO for real-time browser updates.

## Glossary

- **ESP32-CAM**: Microcontroller device with integrated camera module that captures and streams JPEG images
- **System**: The complete FastAPI backend application running on Railway
- **Recognition_Engine**: The face recognition service using dlib 128-dimensional face encodings
- **WebSocket_Server**: The FastAPI WebSocket endpoint at `/ws/camera` that accepts binary JPEG frames
- **Socket_IO_Server**: The Socket.IO server that broadcasts real-time attendance updates to web clients
- **API_Key**: SHA256-hashed authentication token stored in the `api_keys` table
- **Face_Encoding**: 128-dimensional numpy array representing facial features (dlib-based)
- **Attendance_Record**: A timestamped record of a recognized student's presence
- **Railway**: The deployment platform providing PostgreSQL and HTTPS/WSS termination
- **Browser_Client**: Web dashboard displaying real-time attendance data

---

## Requirements

### Requirement 1: Real-Time Binary Image Streaming

**User Story:** As an ESP32-CAM device, I want to stream JPEG images via WebSocket binary protocol, so that I can receive immediate face recognition results without HTTP overhead.

#### Acceptance Criteria

1. WHEN an ESP32-CAM device connects to `/ws/camera` with valid `api_key` and `device_id` query parameters, THE WebSocket_Server SHALL accept the connection
2. WHEN the ESP32-CAM sends a binary JPEG frame, THE WebSocket_Server SHALL decode the image and extract face encodings
3. WHEN face recognition completes, THE WebSocket_Server SHALL respond with a JSON message containing status, name, student_id, class_name, confidence, timestamp, and device_id
4. THE WebSocket_Server SHALL respond to each frame within 500 milliseconds of receipt
5. WHEN the API key is invalid, THE WebSocket_Server SHALL close the connection with code 1008 and reason "Invalid API Key"

---

### Requirement 2: Face Recognition with In-Memory Encodings

**User Story:** As a system operator, I want face encodings cached in RAM at startup, so that recognition queries do not require database I/O during frame processing.

#### Acceptance Criteria

1. WHEN the System starts up, THE Recognition_Engine SHALL load all face encodings from the PostgreSQL `students` table into an in-memory dictionary
2. THE Recognition_Engine SHALL organize encodings by class name as `dict[class_name, list[tuple[encoding, student_id, name, student_code]]]`
3. WHEN a new student face encoding is added, THE Recognition_Engine SHALL update the in-memory dictionary immediately without requiring a restart
4. WHEN performing face matching, THE Recognition_Engine SHALL compare the unknown encoding against all in-memory encodings using a tolerance of 0.5
5. THE Recognition_Engine SHALL return the best match with the lowest face distance if distance is below tolerance

---

### Requirement 3: Asynchronous Face Recognition Processing

**User Story:** As a backend service, I want CPU-bound face recognition operations executed in a thread pool executor, so that the async event loop remains non-blocking.

#### Acceptance Criteria

1. WHEN encoding a face from image bytes, THE Recognition_Engine SHALL execute `face_recognition.face_encodings()` in a ThreadPoolExecutor
2. WHEN matching a face encoding, THE Recognition_Engine SHALL execute `face_recognition.face_distance()` in a ThreadPoolExecutor
3. THE Recognition_Engine SHALL use `asyncio.get_running_loop().run_in_executor()` to wrap synchronous face_recognition calls
4. THE ThreadPoolExecutor SHALL have a maximum of 4 worker threads

---

### Requirement 4: API Key Authentication with In-Memory Cache

**User Story:** As a security-conscious system, I want API keys validated from an in-memory cache, so that authentication does not query the database for every frame.

#### Acceptance Criteria

1. WHEN the System starts up, THE Auth_Service SHALL load all active API keys from the `api_keys` table into an in-memory set
2. WHEN an ESP32-CAM connects, THE Auth_Service SHALL validate the API key against the in-memory cache without querying the database
3. WHEN a new API key is created or an existing key is deactivated, THE Auth_Service SHALL update the in-memory cache immediately
4. THE System SHALL store API keys in the database as SHA256 hashes

---

### Requirement 5: Real-Time Browser Updates via Socket.IO

**User Story:** As a web dashboard user, I want to see new attendance records appear instantly without page refresh, so that I can monitor attendance in real-time.

#### Acceptance Criteria

1. WHEN a face is successfully recognized and an attendance record is saved, THE Socket_IO_Server SHALL emit an `attendance_update` event to all connected Browser_Clients
2. THE `attendance_update` event payload SHALL include id, student_name, student_code, class_name, device_id, confidence, status, and recorded_at
3. WHEN a Browser_Client connects to the Socket.IO endpoint, THE Socket_IO_Server SHALL accept the connection
4. THE Socket_IO_Server SHALL be integrated into the FastAPI application using `socketio.ASGIApp`

---

### Requirement 6: PostgreSQL Data Persistence

**User Story:** As a system administrator, I want all attendance records, students, classes, and API keys stored in PostgreSQL, so that data persists across deployments and scales horizontally.

#### Acceptance Criteria

1. THE System SHALL use asyncpg for asynchronous PostgreSQL connections with a connection pool (min=2, max=10)
2. THE System SHALL create four tables: `classes`, `students`, `attendance_records`, and `api_keys`
3. THE `students` table SHALL store face encodings as pickled numpy arrays in a BYTEA column
4. THE `attendance_records` table SHALL have indexes on `recorded_at DESC` and `(class_id, recorded_at DESC)`
5. ALL primary keys SHALL use UUID with server default `gen_random_uuid()`

---

### Requirement 7: ESP32-CAM WebSocket Client Implementation

**User Story:** As an ESP32-CAM device, I want to connect to the server via WebSocket Secure (WSS), send JPEG frames, and receive JSON recognition results, so that I can provide immediate visual feedback via LED.

#### Acceptance Criteria

1. WHEN the ESP32-CAM powers on, THE ESP32_Client SHALL initialize the camera module and connect to WiFi
2. WHEN WiFi is connected, THE ESP32_Client SHALL connect to the WebSocket_Server using WSS with `api_key` and `device_id` query parameters
3. WHEN connected, THE ESP32_Client SHALL capture a JPEG frame every 1500 milliseconds and send it as a binary WebSocket message
4. WHEN the ESP32_Client receives a JSON response with status "recognized", THE ESP32_Client SHALL light the LED green for 800 milliseconds
5. WHEN the ESP32_Client receives a JSON response with status "unknown", THE ESP32_Client SHALL log the event to Serial
6. WHEN the WebSocket connection is lost, THE ESP32_Client SHALL attempt reconnection every 3 seconds
7. WHEN heap memory falls below 50KB, THE ESP32_Client SHALL restart using `esp_restart()`
8. THE ESP32_Client SHALL call `esp_camera_fb_return()` immediately after sending each frame

---

### Requirement 8: Light Mode User Interface

**User Story:** As a web dashboard user, I want a clean light-themed interface using Tailwind CSS, so that the UI is readable in well-lit environments without dark glassmorphism effects.

#### Acceptance Criteria

1. THE System SHALL render HTML templates with Tailwind CSS using a white background (#FFFFFF or #F8FAFC)
2. THE System SHALL use slate-800 (#1E293B) for primary text and slate-500 (#64748B) for secondary text
3. THE System SHALL use blue-600 (#2563EB) for accent colors on buttons and links
4. THE System SHALL NOT use any dark mode classes (bg-slate-900, bg-gray-800, text-white on dark backgrounds)
5. THE System SHALL NOT use glassmorphism effects (backdrop-blur, glass-like transparency)

---

### Requirement 9: Real-Time Attendance Table Updates

**User Story:** As a web dashboard user, I want the attendance table to update automatically when new records are created, so that I can monitor attendance without refreshing the page.

#### Acceptance Criteria

1. WHEN the attendance page loads, THE Browser_Client SHALL connect to the Socket.IO server
2. WHEN the Browser_Client receives an `attendance_update` event, THE Browser_Client SHALL prepend a new row to the attendance table without reloading the page
3. THE new row SHALL be highlighted with bg-blue-50 for 3 seconds before the highlight fades
4. THE attendance table SHALL support client-side pagination with 50 records per page
5. THE attendance page SHALL include a filter for class selection and date range

---

### Requirement 10: Excel Export Functionality

**User Story:** As a teacher, I want to export attendance records to Excel format filtered by class and date, so that I can submit reports to administration.

#### Acceptance Criteria

1. WHEN a user clicks the "Export Excel" button on the attendance page, THE System SHALL generate an Excel file using openpyxl
2. THE Excel export SHALL include columns: Timestamp, Student Name, Student Code, Class, Device, Status, Confidence
3. THE Excel export SHALL respect the current class and date filters applied on the page
4. THE System SHALL return the Excel file with content-type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

---

### Requirement 11: Student Management with Face Encoding Upload

**User Story:** As an administrator, I want to upload student photos and automatically generate face encodings, so that the system can recognize students.

#### Acceptance Criteria

1. WHEN an administrator uploads a student photo via the students page, THE System SHALL accept JPEG or PNG images up to 10MB
2. WHEN the image is uploaded, THE System SHALL extract face encodings using face_recognition library
3. IF no face is detected in the uploaded image, THE System SHALL return an error message "No face detected in image"
4. WHEN face encoding succeeds, THE System SHALL pickle the numpy array and store it in the `students.face_encoding` BYTEA column
5. WHEN a new student encoding is saved, THE Recognition_Engine SHALL update the in-memory encodings dictionary immediately

---

### Requirement 12: Railway Deployment Configuration

**User Story:** As a DevOps engineer, I want the application packaged in a Docker container with proper Railway configuration, so that it deploys successfully with PostgreSQL integration.

#### Acceptance Criteria

1. THE System SHALL include a Dockerfile that installs cmake, build-essential, libopenblas-dev, liblapack-dev, and other dlib dependencies
2. THE Dockerfile SHALL install dlib before other Python dependencies to cache the slow build layer
3. THE System SHALL run with uvicorn using exactly 1 worker to maintain in-memory encodings state
4. THE System SHALL expose a `/health` endpoint that returns `{"status": "ok"}` for Railway health checks
5. THE railway.toml configuration SHALL specify dockerfile builder and `/health` healthcheck path

---

### Requirement 13: Environment Variable Configuration

**User Story:** As a system administrator, I want all sensitive configuration loaded from environment variables, so that secrets are not committed to version control.

#### Acceptance Criteria

1. THE System SHALL load DATABASE_URL from environment variables (auto-provided by Railway PostgreSQL plugin)
2. THE System SHALL load SECRET_KEY, ADMIN_PASSWORD, UPLOAD_DIR, MAX_UPLOAD_SIZE_MB, FACE_RECOGNITION_TOLERANCE, and CORS_ORIGINS from environment variables
3. THE System SHALL include a `.env.example` file demonstrating all required environment variables
4. THE System SHALL use pydantic-settings for configuration management

---

### Requirement 14: Database Initialization Scripts

**User Story:** As a database administrator, I want an initialization script that creates all tables and indexes, so that the database schema is reproducible.

#### Acceptance Criteria

1. THE System SHALL include a `scripts/init_db.py` script that creates all four tables with proper indexes
2. THE init_db script SHALL be idempotent (safe to run multiple times)
3. THE init_db script SHALL create indexes on `attendance_records(recorded_at DESC)` and `attendance_records(class_id, recorded_at DESC)`

---

### Requirement 15: CORS Configuration

**User Story:** As a frontend developer, I want CORS configured to allow cross-origin requests during development, so that I can test the API from localhost.

#### Acceptance Criteria

1. THE System SHALL enable CORS middleware using FastAPI's CORSMiddleware
2. THE System SHALL allow all origins when CORS_ORIGINS environment variable is set to "*"
3. THE System SHALL allow credentials, all methods, and all headers in CORS configuration

---

### Requirement 16: Static File Serving and Templates

**User Story:** As a web user, I want to access HTML pages for attendance, students, and API keys management, so that I can interact with the system through a browser.

#### Acceptance Criteria

1. THE System SHALL serve HTML templates using Jinja2 from the `app/templates` directory
2. THE System SHALL provide routes for `/` (index), `/attendance`, `/students`, and `/api_keys`
3. THE System SHALL include Socket.IO client script at `/socket.io/socket.io.js`

---

### Requirement 17: Performance Requirements

**User Story:** As a system architect, I want to ensure sub-500ms end-to-end face recognition latency, so that ESP32-CAM devices receive timely feedback.

#### Acceptance Criteria

1. THE System SHALL respond to WebSocket binary frames with face recognition results within 500 milliseconds under normal load
2. THE Recognition_Engine SHALL NOT perform database queries during face matching (use in-memory encodings only)
3. THE Auth_Service SHALL NOT perform database queries during API key validation (use in-memory cache only)
4. THE System SHALL save attendance records and broadcast Socket.IO events asynchronously without blocking the WebSocket response

---

### Requirement 18: Error Handling and Logging

**User Story:** As a system operator, I want comprehensive error logging for WebSocket connections, face recognition failures, and database errors, so that I can troubleshoot issues.

#### Acceptance Criteria

1. WHEN the WebSocket_Server encounters a face recognition error, THE System SHALL log the error to stdout and send a `no_face` response to the ESP32_Client
2. WHEN database connection fails during startup, THE System SHALL log the error and prevent the application from starting
3. WHEN an ESP32_Client disconnects, THE System SHALL log the disconnection with the device_id
4. WHEN saving attendance records fails, THE System SHALL log the error but continue processing subsequent frames

---

### Requirement 19: ESP32 Camera Configuration

**User Story:** As an ESP32 developer, I want a configuration header file with all WiFi and server settings, so that I can easily deploy to multiple devices.

#### Acceptance Criteria

1. THE ESP32_Client SHALL include a `config.h` header file with constants for WIFI_SSID, WIFI_PASSWORD, SERVER_HOST, SERVER_PORT, WS_PATH, API_KEY, DEVICE_ID
2. THE ESP32_Client SHALL support CAMERA_MODEL_AI_THINKER configuration for pin mappings
3. THE ESP32_Client SHALL allow configuration of CAPTURE_INTERVAL_MS (default 1500), JPEG_QUALITY (default 12), and FRAME_SIZE (default FRAMESIZE_VGA)

---

### Requirement 20: WebSocket Heartbeat and Connection Stability

**User Story:** As a real-time system, I want WebSocket connections to remain stable for extended periods, so that ESP32 devices do not disconnect during idle periods.

#### Acceptance Criteria

1. THE WebSocket_Server SHALL remain connected to ESP32 clients indefinitely during idle periods (Railway allows 30s idle timeout)
2. WHEN an ESP32_Client stops responding, THE WebSocket_Server SHALL detect the disconnect and clean up resources
3. THE ESP32_Client SHALL implement auto-reconnect logic with 3-second retry interval

---

## Parser and Serializer Requirements

### Requirement 21: Face Encoding Serialization

**User Story:** As a data persistence layer, I want to serialize numpy face encodings to binary format, so that they can be stored in PostgreSQL BYTEA columns.

#### Acceptance Criteria

1. WHEN saving a face encoding to the database, THE System SHALL serialize the numpy array using `pickle.dumps()`
2. WHEN loading a face encoding from the database, THE System SHALL deserialize using `pickle.loads()`
3. FOR ALL valid face encoding numpy arrays, serializing then deserializing SHALL produce an equivalent array (round-trip property)

---

### Requirement 22: JSON Response Formatting

**User Story:** As an ESP32 client, I want to receive recognition results in a well-defined JSON format, so that I can parse and display results reliably.

#### Acceptance Criteria

1. WHEN the WebSocket_Server sends a recognition result, THE response SHALL be valid JSON with keys: status, name, student_id, class_name, confidence, timestamp, device_id
2. THE status field SHALL be one of: "recognized", "unknown", "no_face"
3. WHEN status is "recognized", THE name, student_id, class_name, and confidence fields SHALL be non-null
4. WHEN status is "unknown" or "no_face", THE name, student_id, class_name, and confidence fields SHALL be null
5. THE timestamp field SHALL be an ISO 8601 formatted string in UTC timezone
