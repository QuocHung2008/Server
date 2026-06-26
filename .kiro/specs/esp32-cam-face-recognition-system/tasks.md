# Implementation Plan: ESP32-CAM Face Recognition Attendance System

## Overview

This implementation plan breaks down the ESP32-CAM Face Recognition Attendance System into discrete coding tasks. The system uses FastAPI (Python) for the backend and Arduino C++ for the ESP32-CAM client. The architecture is single-worker with in-memory caching for face encodings and API keys.

## Tasks

- [x] 1. Set up project structure and database schema
  - Create FastAPI application structure with routers, services, and models directories
  - Define SQLAlchemy models for classes, students, attendance_records, and api_keys tables
  - Create database initialization script with proper indexes
  - Set up asyncpg connection pool with Railway PostgreSQL
  - Configure Pydantic settings for environment variables
  - _Requirements: 6.2, 6.3, 6.4, 6.5, 13.1, 13.2, 13.4, 14.1, 14.2, 14.3_

- [ ] 2. Implement authentication service with in-memory API key cache
  - [x] 2.1 Create AuthService class with in-memory API key cache
    - Implement `load_api_keys()` to load active API keys from database into set
    - Implement `validate_key()` to check API key hash against in-memory cache
    - Implement `add_key()` and `deactivate_key()` to update both database and cache
    - Use SHA256 hashing for API key storage
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  
  - [x] 2.2 Write property test for API key cache consistency
    - **Property 5: API Key Cache Consistency**
    - **Validates: Requirements 4.3**
    - Test that cache updates immediately after create/deactivate operations

- [ ] 3. Implement face recognition service with in-memory encodings
  - [x] 3.1 Create FaceService class with ThreadPoolExecutor
    - Implement `load_all_encodings()` to load face encodings from database into dictionary organized by class
    - Implement `encode_face()` using face_recognition library with run_in_executor wrapper
    - Implement `match_face()` with face_distance calculation using tolerance 0.5
    - Use ThreadPoolExecutor with 4 workers for CPU-bound operations
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4_
  
  - [-] 3.2 Write property test for face encoding serialization round-trip
    - **Property 1: Face Encoding Serialization Round-Trip**
    - **Validates: Requirements 21.3**
    - Test that pickle serialization/deserialization preserves numpy array equality
  
  - [-] 3.3 Write property test for best match selection
    - **Property 4: Best Match Selection**
    - **Validates: Requirements 2.5**
    - Test that match_face returns the known encoding with minimum distance below tolerance
  
  - [-] 3.4 Write property test for student encoding cache consistency
    - **Property 3: Student Encoding Cache Consistency**
    - **Validates: Requirements 2.3**
    - Test that adding a student updates in-memory cache immediately

- [ ] 4. Implement WebSocket handler for ESP32-CAM image streaming
  - [ ] 4.1 Create WebSocket endpoint at /ws/camera
    - Accept api_key and device_id as query parameters
    - Validate API key using AuthService before accepting connection
    - Implement binary frame reception loop
    - Call FaceService.encode_face() and match_face() for each frame
    - Return JSON response with status, name, student_id, class_name, confidence, timestamp, device_id
    - Handle errors: invalid API key → close with code 1008, no face detected → send "no_face" response
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 18.1_
  
  - [~] 4.2 Write property test for JSON response structure
    - **Property 2: JSON Response Structure and Validation**
    - **Validates: Requirements 22.1, 22.2, 22.3, 22.4, 22.5**
    - Test that recognition responses contain all required keys with correct types and null/non-null constraints

- [ ] 5. Implement Socket.IO service for real-time browser updates
  - [~] 5.1 Create Socket.IO server and integrate with FastAPI
    - Initialize AsyncServer with ASGI mode and CORS configuration
    - Implement `broadcast_attendance_update()` function to emit attendance_update events
    - Wrap FastAPI app with socketio.ASGIApp
    - _Requirements: 5.1, 5.3, 5.4_
  
  - [~] 5.2 Write property test for Socket.IO event payload structure
    - **Property 6: Socket.IO Event Payload Structure**
    - **Validates: Requirements 5.2**
    - Test that attendance_update events contain all required fields with correct types

- [~] 6. Checkpoint - Ensure core services are functional
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement attendance recording with async database saves
  - [~] 7.1 Create attendance record save function
    - Accept student_id, class_id, device_id, confidence
    - Insert record into attendance_records table using asyncpg
    - Call broadcast_attendance_update() after successful save
    - Execute save operation asynchronously without blocking WebSocket response
    - _Requirements: 5.1, 17.4, 18.4_
  
  - [~] 7.2 Write integration tests for attendance recording
    - Test that attendance records are saved to database
    - Test that Socket.IO events are emitted after save
    - Test error handling for database connection failures

- [ ] 8. Implement REST API routers
  - [~] 8.1 Create attendance router
    - GET /attendance → render attendance page template
    - GET /api/attendance/records → fetch attendance records with pagination, class filter, date filter
    - GET /api/attendance/export → generate Excel file using openpyxl with applied filters
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 16.1, 16.2_
  
  - [~] 8.2 Write property test for Excel export column structure
    - **Property 7: Excel Export Column Structure**
    - **Validates: Requirements 10.2**
    - Test that Excel files contain all required columns in correct order
  
  - [~] 8.3 Create students router
    - GET /students → render student management page template
    - POST /api/students → upload student photo, extract face encoding, save to database
    - GET /api/students → list students with pagination
    - DELETE /api/students/{id} → delete student
    - Validate image file size (max 10MB) and format (JPEG/PNG)
    - Return error if no face detected in uploaded image
    - Update FaceService in-memory cache after adding new student
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 16.1, 16.2_
  
  - [~] 8.4 Create classes router
    - GET /api/classes → list all classes
    - POST /api/classes → create new class
    - DELETE /api/classes/{id} → delete class with cascade
    - _Requirements: 16.1, 16.2_
  
  - [~] 8.5 Create API keys router
    - GET /api_keys → render API key management page template
    - POST /api/api_keys → create new API key with SHA256 hash
    - DELETE /api/api_keys/{id} → deactivate API key
    - Update AuthService in-memory cache after create/deactivate operations
    - _Requirements: 4.3, 16.1, 16.2_

- [ ] 9. Implement frontend templates with Tailwind CSS
  - [~] 9.1 Create base template with light mode styling
    - Set up Jinja2 template structure with base.html
    - Include Tailwind CSS CDN with light mode configuration
    - Use white background (#FFFFFF or #F8FAFC) and slate-800 text (#1E293B)
    - Use blue-600 (#2563EB) for accent colors
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 16.1_
  
  - [~] 9.2 Create attendance page template
    - Display attendance records table with pagination (50 records per page)
    - Add filters for class selection and date range
    - Add "Export Excel" button
    - Integrate Socket.IO client for real-time updates
    - Implement row highlighting (bg-blue-50 for 3 seconds) on new records
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 16.2_
  
  - [~] 9.3 Create students management page template
    - Display student list with class information
    - Add photo upload form with file size/format validation
    - Display error messages for invalid uploads
    - _Requirements: 16.2_
  
  - [~] 9.4 Create API keys management page template
    - Display API key list with label, device_id, and active status
    - Add form to create new API key
    - Add deactivate button for each active key
    - _Requirements: 16.2_
  
  - [~] 9.5 Create index page template
    - Display dashboard overview with recent attendance statistics
    - _Requirements: 16.2_

- [~] 10. Checkpoint - Ensure web interface is functional
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement ESP32-CAM client firmware
  - [~] 11.1 Create config.h header file
    - Define WiFi credentials (WIFI_SSID, WIFI_PASSWORD)
    - Define server connection parameters (SERVER_HOST, SERVER_PORT, WS_PATH, USE_SSL)
    - Define API_KEY and DEVICE_ID
    - Define camera configuration (CAMERA_MODEL_AI_THINKER, CAPTURE_INTERVAL_MS, JPEG_QUALITY, FRAME_SIZE)
    - _Requirements: 19.1, 19.2, 19.3_
  
  - [~] 11.2 Implement ESP32 camera initialization
    - Configure camera pins for AI_THINKER model
    - Set JPEG quality and frame size (FRAMESIZE_VGA)
    - Initialize camera module in setup() function
    - _Requirements: 7.1, 19.2_
  
  - [~] 11.3 Implement WiFi connection logic
    - Connect to WiFi using configured credentials
    - Implement connection retry logic with Serial logging
    - _Requirements: 7.1_
  
  - [~] 11.4 Implement WebSocket client with SSL support
    - Initialize WebSocket Secure (WSS) client
    - Connect to server with api_key and device_id query parameters
    - Implement onMessage callback for JSON responses
    - Implement reconnection logic with 3-second delay
    - _Requirements: 7.2, 7.6, 20.2, 20.3_
  
  - [~] 11.5 Implement frame capture and transmission loop
    - Capture JPEG frame every 1500ms using esp_camera_fb_get()
    - Send frame as binary WebSocket message
    - Return frame buffer immediately with esp_camera_fb_return()
    - Check heap memory and restart if below 50KB
    - _Requirements: 7.3, 7.7, 7.8_
  
  - [~] 11.6 Implement LED feedback for recognition results
    - Parse JSON response from server
    - Light LED green for 800ms when status is "recognized"
    - Log to Serial when status is "unknown"
    - _Requirements: 7.4, 7.5_

- [ ] 12. Implement Docker containerization for Railway deployment
  - [~] 12.1 Create Dockerfile with dlib dependencies
    - Use python:3.11-slim base image
    - Install cmake, build-essential, libopenblas-dev, liblapack-dev for dlib
    - Install dlib first as cached layer
    - Install remaining Python dependencies from requirements.txt
    - Copy application code to /app
    - Set command to run uvicorn with workers=1
    - _Requirements: 12.1, 12.2, 12.3_
  
  - [~] 12.2 Create railway.toml configuration
    - Specify dockerfile builder
    - Configure /health endpoint for healthcheck
    - _Requirements: 12.4, 12.5_
  
  - [~] 12.3 Create health endpoint
    - Implement GET /health route returning {"status": "ok"}
    - _Requirements: 12.4_
  
  - [~] 12.4 Create .env.example file
    - Document all required environment variables with example values
    - Include DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD, UPLOAD_DIR, MAX_UPLOAD_SIZE_MB, FACE_RECOGNITION_TOLERANCE, CORS_ORIGINS
    - _Requirements: 13.3_

- [~] 13. Implement CORS configuration
  - Configure FastAPI CORSMiddleware with environment-based origins
  - Allow credentials, all methods, and all headers
  - _Requirements: 15.1, 15.2, 15.3_

- [ ] 14. Implement error handling and logging
  - [~] 14.1 Add logging for WebSocket connections
    - Log successful connections with device_id
    - Log disconnections with device_id
    - Log face recognition errors
    - _Requirements: 18.1, 18.3_
  
  - [~] 14.2 Add error handling for database operations
    - Log database connection failures during startup
    - Log attendance record save failures
    - Continue processing frames even if database save fails
    - _Requirements: 18.2, 18.4_
  
  - [~] 14.3 Write integration tests for error scenarios
    - Test WebSocket disconnection handling
    - Test database connection failure handling
    - Test invalid API key handling

- [ ] 15. Final integration and testing
  - [~] 15.1 Initialize database with sample data
    - Create sample classes
    - Add sample students with face encodings
    - Create API keys for testing
  
  - [~] 15.2 Test complete flow: ESP32 → WebSocket → Recognition → Database → Socket.IO → Browser
    - Verify ESP32 can connect and stream frames
    - Verify face recognition works with in-memory encodings
    - Verify attendance records are saved to database
    - Verify browser receives real-time updates via Socket.IO
    - Verify performance meets <500ms requirement
    - _Requirements: 17.1_
  
  - [~] 15.3 Run all property-based tests
    - Execute all property tests to verify correctness properties

- [~] 16. Final checkpoint - Deploy to Railway and verify
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The system uses single-worker architecture (uvicorn workers=1) to maintain in-memory state
- Face encodings and API keys are cached in RAM at startup for performance
- All CPU-bound face recognition operations execute in ThreadPoolExecutor to keep async event loop non-blocking
- ESP32 firmware is in C++ (Arduino framework), backend is Python FastAPI
- Property-based tests focus on pure functions: serialization, JSON formatting, cache consistency
- Integration tests cover WebSocket, database, and Socket.IO interactions
- Railway provides PostgreSQL via DATABASE_URL environment variable
- Performance requirement: <500ms end-to-end face recognition latency

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "3.3", "3.4", "4.1"] },
    { "id": 3, "tasks": ["4.2", "5.1", "7.1"] },
    { "id": 4, "tasks": ["5.2", "7.2", "8.1", "8.3", "8.4", "8.5"] },
    { "id": 5, "tasks": ["8.2", "9.1", "11.1", "11.2", "11.3"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.4", "9.5", "11.4"] },
    { "id": 7, "tasks": ["11.5", "11.6", "12.1"] },
    { "id": 8, "tasks": ["12.2", "12.3", "12.4", "13", "14.1"] },
    { "id": 9, "tasks": ["14.2", "14.3", "15.1"] },
    { "id": 10, "tasks": ["15.2", "15.3"] }
  ]
}
```
