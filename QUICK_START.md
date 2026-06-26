# Quick Start Guide - ESP32-CAM Face Recognition System

## Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Git

## Initial Setup

### 1. Clone and Navigate
```bash
cd Server
```

### 2. Create Virtual Environment (Recommended)
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

**Note:** `dlib` installation may take several minutes as it compiles from source.

### 4. Configure Environment Variables

Copy the example file:
```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/attendance
SECRET_KEY=generate-a-random-secret-key-here
ADMIN_PASSWORD=your_admin_password
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=10
FACE_RECOGNITION_TOLERANCE=0.5
CORS_ORIGINS=*
```

### 5. Initialize Database

Make sure PostgreSQL is running, then:
```bash
python scripts/init_db.py
```

You should see:
```
Creating all tables and indexes from models...
✅ Database initialization completed successfully!
```

### 6. Verify Setup

Run the verification script:
```bash
python scripts/verify_setup.py
```

All checks should pass with:
```
✅ ALL CHECKS PASSED - TASK 1 COMPLETE
```

### 7. Start Development Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Access the application at: http://localhost:8000

## API Endpoints

### Web Pages
- `GET /` - Home page
- `GET /attendance` - Attendance dashboard (real-time updates)
- `GET /students` - Student management
- `GET /api_keys` - API key management

### WebSocket
- `WS /ws/camera?api_key=XXX&device_id=YYY` - ESP32-CAM binary frame streaming

### REST API
- `GET /api/classes` - List classes
- `POST /api/classes` - Create class
- `GET /api/students` - List students
- `POST /api/students` - Add student with photo
- `DELETE /api/students/{id}` - Delete student
- `POST /api/api_keys` - Create API key
- `DELETE /api/api_keys/{id}` - Deactivate API key
- `GET /api/attendance/export` - Download Excel report
- `GET /health` - Health check

### Socket.IO Events
- Event: `attendance_update` - Real-time attendance notifications

## Project Structure

```
Server/
├── app/
│   ├── config.py              # Environment configuration
│   ├── database.py            # Database connection pool
│   ├── models.py              # SQLAlchemy models
│   ├── schemas.py             # Pydantic schemas
│   ├── main.py                # FastAPI app
│   ├── routers/               # API endpoints
│   │   ├── ws_camera.py       # WebSocket for ESP32
│   │   ├── classes.py
│   │   ├── students.py
│   │   ├── api_keys.py
│   │   └── attendance.py
│   ├── services/              # Business logic
│   │   ├── face_service.py    # Face recognition
│   │   ├── auth_service.py    # Authentication
│   │   └── socketio_service.py # Real-time events
│   └── templates/             # HTML templates
├── scripts/
│   ├── init_db.py             # Database initialization
│   └── verify_setup.py        # Setup verification
├── uploads/                   # Student photos
├── .env                       # Environment variables (create from .env.example)
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Docker configuration
└── railway.toml               # Railway deployment config
```

## Development Workflow

### Adding a New Student
1. Navigate to `/students`
2. Upload photo (face must be clearly visible)
3. Enter student code and full name
4. Select class
5. System will automatically extract face encoding

### Creating an API Key
1. Navigate to `/api_keys`
2. Enter label and device ID
3. Optionally associate with a class
4. Copy the generated key (shown only once!)
5. Use key in ESP32 WebSocket connection

### Viewing Attendance
1. Navigate to `/attendance`
2. Filter by class and date range
3. View real-time updates as students are recognized
4. Export to Excel for reports

## Testing WebSocket Connection

### Using `websocat` (Linux/Mac)
```bash
# Install websocat
cargo install websocat

# Connect
echo "binary_data" | websocat "ws://localhost:8000/ws/camera?api_key=YOUR_KEY&device_id=TEST_01"
```

### Using JavaScript (Browser Console)
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/camera?api_key=YOUR_KEY&device_id=TEST_01');

ws.onopen = () => {
    console.log('Connected');
    // Send test data
    ws.send(new Blob(['test']));
};

ws.onmessage = (event) => {
    console.log('Response:', event.data);
};
```

## Common Issues

### Issue: `ModuleNotFoundError: No module named 'dlib'`
**Solution:** Install build dependencies first
```bash
# Ubuntu/Debian
sudo apt-get install build-essential cmake

# Then reinstall
pip install dlib
```

### Issue: Database connection failed
**Solution:** Check PostgreSQL is running and credentials are correct
```bash
# Check if PostgreSQL is running
# Windows
pg_ctl status

# Linux
sudo systemctl status postgresql
```

### Issue: Face encoding fails
**Solution:** 
- Ensure image has a clear, front-facing face
- Check image format (JPEG/PNG)
- Verify file size < MAX_UPLOAD_SIZE_MB

### Issue: Port 8000 already in use
**Solution:** 
```bash
# Find process using port
# Windows
netstat -ano | findstr :8000

# Linux
lsof -i :8000

# Use different port
uvicorn app.main:app --reload --port 8001
```

## Railway Deployment

### 1. Install Railway CLI
```bash
npm install -g @railway/cli
```

### 2. Login to Railway
```bash
railway login
```

### 3. Initialize Project
```bash
railway init
```

### 4. Add PostgreSQL
```bash
railway add postgresql
```

### 5. Set Environment Variables
```bash
railway variables set SECRET_KEY=your-secret-key
railway variables set ADMIN_PASSWORD=your-admin-password
```

### 6. Deploy
```bash
railway up
```

### 7. Initialize Database (After First Deploy)
```bash
railway run python scripts/init_db.py
```

### 8. Get Deployment URL
```bash
railway domain
```

## ESP32-CAM Configuration

Edit `esp32/config.h`:
```cpp
#define WIFI_SSID "YourWiFiSSID"
#define WIFI_PASSWORD "YourWiFiPassword"
#define SERVER_HOST "your-app.railway.app"  // Or localhost for testing
#define SERVER_PORT 443  // 443 for HTTPS (Railway), 8000 for local
#define WS_PATH "/ws/camera?api_key=YOUR_API_KEY&device_id=ESP32_01"
#define USE_SSL true  // true for Railway, false for local
```

Upload to ESP32-CAM using Arduino IDE.

## Monitoring

### Check Application Health
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "ok"}
```

### View Logs
```bash
# Local development (console output)
# Shows all print statements and errors

# Railway
railway logs
```

### Database Status
```bash
# Connect to PostgreSQL
psql $DATABASE_URL

# Check tables
\dt

# Check attendance count
SELECT COUNT(*) FROM attendance_records;
```

## Performance Tips

1. **Single Worker Only**: Always run with `--workers 1`
   ```bash
   uvicorn app.main:app --workers 1
   ```

2. **Face Encoding Cache**: Restart app after adding many students to reload cache

3. **Database Indexes**: Already optimized for common queries

4. **Connection Pool**: Configured for 2-10 connections (good for small/medium scale)

## Support

- Check `TASK_1_COMPLETION_SUMMARY.md` for detailed implementation
- Run `python scripts/verify_setup.py` to diagnose issues
- Check application logs for error messages
- Ensure all requirements in `requirements.txt` are installed

## Next Steps After Setup

1. Create some test classes
2. Add test students with photos
3. Generate API keys
4. Configure ESP32-CAM device
5. Test face recognition
6. Monitor attendance dashboard

---

**Ready to go!** 🚀
