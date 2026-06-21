# Smart Face Recognition Attendance System (ESP32-CAM & Flask)

This is a premium, real-time face recognition attendance system designed to work with ESP32-CAM devices and a Flask central server. The system features a modern, responsive Glassmorphism dark-theme dashboard, instant updates via Socket.IO, Excel export, and key-based API protection for IoT devices.

---

## 🗺️ System Architecture

The following diagram illustrates how the components interact:

```mermaid
graph TD
    ESP32[ESP32-CAM Node] -- "1. Send Captured Image (HTTP POST /api/recognize)" --> Server[Flask Server]
    ESP32 -- "MQTT Heartbeat/Status" --> Broker[MQTT Broker: HiveMQ]
    Server -- "Query/Save Records" --> DB[(SQLite/Postgres)]
    Server -- "Compute Embeddings" --> FaceLib[dlib / face_recognition]
    Server -- "2. Broadcast Event (Socket.IO)" --> UI[Web Interface (Real-time HTML/JS)]
    Broker -- "MQTT Status Monitor" --> Server
```

---

## 🚀 Local Installation & Setup (macOS)

Follow these steps to get the server running locally on macOS.

### 📋 Prerequisites
- **Python 3.10 - 3.14** (We configured and compiled successfully with Python **3.14.6**)
- **Xcode Command Line Tools** (For compiling C++ components if needed):
  ```bash
  xcode-select --install
  ```
- **CMake** (Required for the `dlib` C++ compiler backend):
  ```bash
  brew install cmake
  ```

### 🛠️ Step-by-Step Setup

1. **Clone & Navigate to the workspace:**
   ```bash
   cd /Users/billcipher/Downloads/CODE/ESP32/project_backup/Server
   ```

2. **Create a local Python virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install packaging tools and project dependencies:**
   ```bash
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```
   *(Note: The `dlib` C++ dependency compiles automatically during installation thanks to the installed CMake).*

4. **Initialize databases and folder structures:**
   ```bash
   python init_databases.py
   ```
   This script creates the database files (`users.db`, `api_keys.db`) and structure under `classes/_system/`.

5. **Retrieve the Auto-Generated Admin Password:**
   Upon first database initialization, a secure administrative password is created and saved at:
   `classes/_system/admin_password`
   Use the username **`admin`** and copy the password from that file to log into the web panel.

6. **Start the Flask Development Server:**
   ```bash
   python server.py
   ```
   The application will start on `http://localhost:5000` (or the port defined by the `PORT` environment variable).

---

## 📂 Directory Structure

```
Server/
├── server.py                 # Core Flask Server (routing, Socket.IO, database, face matching)
├── encode_known_faces.py     # Background worker to encode images into 128D vectors
├── init_databases.py         # Database initialization and directory setups
├── requirements.txt          # Python packages listing
├── generate_esp32_config.py  # Utility to generate C config file for ESP32 flash
├── classes/                  # Persistent data directory
│   ├── _system/              # System DBs (users.db, api_keys.db) and admin password
│   ├── DS/                   # Excel student lists (.xlsx) for each class
│   └── [ClassName]/          # Directory structure for class student images & records
└── templates/                # Glassmorphic responsive dark mode templates
    ├── base.html             # Common layout, styles (Outfit Font, glass cards, inputs)
    ├── index.html            # Dashboard (Chart.js stats, live metrics, list of classes)
    ├── attendance.html       # Real-time attendance logs showing matched faces
    └── api_keys.html         # Key rotation, revoking and authorization config
```

---

## 🔌 API & WebSocket Reference

### 1. Attendance Check API
- **Endpoint**: `POST /api/recognize`
- **Headers**:
  - `Authorization`: `Bearer <API_KEY>`
- **Body** (multipart/form-data):
  - `image`: Image file (JPEG/PNG)
- **Response**:
  ```json
  {"status": "success", "match": "Student Name", "student_id": "12345"}
  ```

### 2. Live Synchronization Event (Socket.IO)
- **Event Name**: `attendance_update`
- **Payload**:
  ```json
  {
    "class_name": "12T1",
    "student_id": "ST001",
    "name": "Nguyen Van A",
    "time": "08:30:15",
    "status": "present",
    "device_id": "ESP32_CAM_01"
  }
  ```

---

## 🤖 Instructions for AI Agents (AI Developer Guide)

If you are an AI assistant continuing the development of this project, pay attention to the following details:

### 🎨 UI Style Guide
- **Theme**: Premium modern dark mode with vibrant glassmorphic layers.
- **Tailwind CSS**: The templates use **Tailwind CSS** (via CDN in `base.html`). Avoid hardcoding bright white (`bg-white`), dark grey text (`text-slate-800`), or default borders (`border-slate-300`). 
- **Glassmorphic components**:
  - Cards: Use `.classic-card` (inherits `bg-slate-900/45` with background blur and thin semi-transparent border).
  - Buttons: Use `.classic-btn` for main actions (blue-to-indigo gradient with hover translation and shadow). Use `bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10` for secondary buttons.
  - Inputs & select elements: Inherit styles globally in `base.html`. Do not hardcode bright backgrounds.

### 🐍 Python Coding Standards
- **Global Variables**: `server.py` relies on in-memory mapping of API keys (`api_keys` dict) and face encodings. If you alter the database API keys, make sure to call `load_api_keys()` to keep the memory cache synchronized.
- **Relational Fallbacks**: The code supports both local SQLite and remote PostgreSQL (`DATABASE_URL` check). Always write queries that are compatible with both SQL syntaxes (e.g. use standard placeholders `?` or `%s` appropriately, which the `db_execute` utility wrapper in `server.py` helps abstracts).
- **Graceful Shutdown**: The server catches SIGINT/SIGTERM to cleanly disconnect the active MQTT client.

### 🛠️ How to Extend
1. **Adding new endpoints**: Add decorators to `server.py`. Ensure they are protected with `@login_required` if they serve administrative views.
2. **Extending Database Schema**: Update both `init_databases.py` and the `init_database_schema` function inside `server.py` to keep SQLite and PostgreSQL declarations matching.
3. **Face Recognition Updates**: Face encodings are done using `encode_known_faces.py`. When new images are uploaded via `add_student.html`, the backend automatically calls the encoder to update the `.pkl` files inside `classes/` structure.
