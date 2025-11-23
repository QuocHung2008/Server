from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from encode_known_faces import build_encodings_for_class
from openpyxl import Workbook
import os, sqlite3, pickle, cv2, numpy as np, face_recognition
import datetime, threading, time, logging
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

# ==================================================================================
# CONFIG
# ==================================================================================

BASE_DIR = "classes"
TOLERANCE = 0.4
DETECTION_MODEL = "hog"
POOL_WORKERS = 6  # Thread pool để xử lý face encoding song song
ENCODING_CACHE_TTL = 3600  # Cache encodings 1 giờ
LOG_LEVEL = logging.INFO

# Logging setup
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# ==================================================================================
# GLOBAL STATE MANAGEMENT
# ==================================================================================

class CachedEncodings:
    """Thread-safe encoding cache với TTL"""
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        self._lock = threading.RLock()
    
    def get(self, class_name):
        with self._lock:
            if class_name in self._cache:
                # Check TTL
                age = time.time() - self._timestamps[class_name]
                if age < ENCODING_CACHE_TTL:
                    return self._cache[class_name]
                else:
                    del self._cache[class_name]
                    del self._timestamps[class_name]
        return None
    
    def set(self, class_name, data):
        with self._lock:
            self._cache[class_name] = data
            self._timestamps[class_name] = time.time()
    
    def invalidate(self, class_name):
        with self._lock:
            self._cache.pop(class_name, None)
            self._timestamps.pop(class_name, None)

class ThreadSafeDB:
    """Connection pool đơn giản cho SQLite"""
    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
    
    def execute(self, query, params=()):
        """Thread-safe query execution"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                conn.isolation_level = None  # Autocommit mode
                c = conn.cursor()
                c.execute(query, params)
                result = c.fetchall()
                conn.close()
                return result
            except sqlite3.OperationalError as e:
                logger.error(f"DB Error: {e}")
                return []
    
    def execute_insert(self, query, params=()):
        """Insert dengan transaction"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                c = conn.cursor()
                c.execute(query, params)
                conn.commit()
                conn.close()
                return True
            except sqlite3.IntegrityError:
                return False
            except Exception as e:
                logger.error(f"Insert Error: {e}")
                return False

ENCODINGS_CACHE = CachedEncodings()
DB_CONNECTIONS = {}  # Store per-class DB objects
LOCKS = {}  # Per-class locks for critical sections

# ==================================================================================
# UTILITY FUNCTIONS
# ==================================================================================

def sort_by_vietnamese_name(names):
    """Sắp xếp tên Việt theo họ"""
    def name_key(fullname):
        parts = fullname.strip().split()
        return parts[::-1]
    return sorted(names, key=name_key)

def get_status_by_time(now):
    """Xác định trạng thái điểm danh"""
    morning_limit = now.replace(hour=6, minute=45, second=0, microsecond=0)
    afternoon_limit = now.replace(hour=13, minute=15, second=0, microsecond=0)
    if now.hour < 12:
        return "Trễ" if now > morning_limit else "Có mặt"
    return "Trễ" if now > afternoon_limit else "Có mặt"

def ensure_class(class_name):
    """Khởi tạo lớp (thread-safe)"""
    class_dir = os.path.join(BASE_DIR, class_name)
    os.makedirs(os.path.join(class_dir, "known_faces"), exist_ok=True)
    
    if class_name not in LOCKS:
        LOCKS[class_name] = threading.RLock()
    
    if class_name not in DB_CONNECTIONS:
        db_path = os.path.join(class_dir, "attendance.db")
        DB_CONNECTIONS[class_name] = ThreadSafeDB(db_path)
        
        # Create table if not exists
        db = DB_CONNECTIONS[class_name]
        db.execute("""CREATE TABLE IF NOT EXISTS attendance(
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT, date TEXT,
                first_time TEXT, status TEXT, 
                timestamp_iso TEXT, 
                UNIQUE(name, date))""")
    
    return class_dir

def get_encodings_data(class_name):
    """Lấy encodings từ cache hoặc file"""
    cached = ENCODINGS_CACHE.get(class_name)
    if cached:
        return cached
    
    class_dir = os.path.join(BASE_DIR, class_name)
    enc_path = os.path.join(class_dir, "encodings.pkl")
    
    if not os.path.exists(enc_path):
        logger.info(f"Building encodings for {class_name}...")
        data = build_encodings_for_class(class_dir)
    else:
        with open(enc_path, "rb") as f:
            data = pickle.load(f)
    
    ENCODINGS_CACHE.set(class_name, data)
    return data

def reload_cache(class_name):
    """Reload cache khi có thay đổi"""
    ENCODINGS_CACHE.invalidate(class_name)
    get_encodings_data(class_name)

# ==================================================================================
# FACE RECOGNITION (CORE LOGIC)
# ==================================================================================

def process_face_recognition(class_name, img_bytes):
    """
    Xử lý nhận diện khuôn mặt (có thể chạy song song)
    Returns: (name, confidence, error_msg)
    """
    try:
        # Decode image
        img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img_bgr is None:
            return "Unknown", 0.0, "Invalid image"
        
        # RGB conversion
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        
        # Get encodings data
        data = get_encodings_data(class_name)
        if not data.get("encodings"):
            return "Unknown", 0.0, "No training data"
        
        # Detect faces
        locs = face_recognition.face_locations(img_rgb, model=DETECTION_MODEL)
        if len(locs) == 0:
            return "Unknown", 0.0, "No face detected"
        
        # Get encodings
        encs = face_recognition.face_encodings(img_rgb, locs)
        if not encs:
            return "Unknown", 0.0, "Could not encode face"
        
        # ===== SELECT BEST FACE (Largest = Closest to camera) =====
        best_face_idx = 0
        if len(locs) > 1:
            areas = [(loc[2] - loc[0]) * (loc[1] - loc[3]) for loc in locs]
            best_face_idx = np.argmax(areas)
        
        enc = encs[best_face_idx]
        
        # Compare with database
        matches = face_recognition.compare_faces(data["encodings"], enc, TOLERANCE)
        distances = face_recognition.face_distance(data["encodings"], enc)
        
        if len(distances) == 0:
            return "Unknown", 0.0, "Comparison failed"
        
        best_idx = np.argmin(distances)
        confidence = 1.0 - distances[best_idx]
        
        if matches[best_idx]:
            name = data["names"][best_idx]
            return name, confidence, None
        else:
            return "Unknown", confidence, None
    
    except Exception as e:
        logger.error(f"Recognition error: {e}")
        return "Unknown", 0.0, str(e)

def record_attendance(class_name, name):
    """Ghi điểm danh (thread-safe)"""
    try:
        db = DB_CONNECTIONS.get(class_name)
        if not db:
            ensure_class(class_name)
            db = DB_CONNECTIONS[class_name]
        
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        iso = now.isoformat(sep=" ", timespec="seconds")
        status = get_status_by_time(now)
        
        query = """INSERT OR IGNORE INTO attendance
                   (name, date, first_time, status, timestamp_iso) 
                   VALUES(?, ?, ?, ?, ?)"""
        
        success = db.execute_insert(query, (name, today, time_str, status, iso))
        
        if success:
            logger.info(f"[{class_name}] Recorded: {name} - {status}")
        
    except Exception as e:
        logger.error(f"Record attendance error: {e}")

# ==================================================================================
# ROUTES
# ==================================================================================

@app.route("/")
def index():
    """Dashboard - Tổng hợp tất cả lớp"""
    data = []
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
    
    for class_name in os.listdir(BASE_DIR):
        class_dir = os.path.join(BASE_DIR, class_name)
        if not os.path.isdir(class_dir):
            continue
        
        try:
            ensure_class(class_name)
            enc_path = os.path.join(class_dir, "encodings.pkl")
            
            if not os.path.exists(enc_path):
                build_encodings_for_class(class_dir)
            
            with open(enc_path, "rb") as f:
                enc_data = pickle.load(f)
            
            all_people = sort_by_vietnamese_name(list(set(enc_data.get("names", []))))
            
            db = DB_CONNECTIONS[class_name]
            present = set(row[0] for row in db.execute(
                "SELECT DISTINCT name FROM attendance WHERE date=?", (today,)
            ))
            
            absent = [n for n in all_people if n not in present]
            
            data.append({
                "class": class_name,
                "present": len(present),
                "absent": len(absent),
                "absent_names": ", ".join(absent) if absent else "Đủ mặt"
            })
        except Exception as e:
            logger.error(f"Index error for {class_name}: {e}")
    
    return render_template("index.html", classes=data)

@app.route("/class/<class_name>/")
def class_home(class_name):
    """Trang điểm danh của lớp"""
    class_dir = ensure_class(class_name)
    data = get_encodings_data(class_name)
    db = DB_CONNECTIONS[class_name]
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    present_rows = db.execute(
        "SELECT name, status FROM attendance WHERE date=?", (today,)
    )
    present = {r[0]: r[1] for r in present_rows}
    
    all_people = sort_by_vietnamese_name(list(set(data["names"])))
    students = [
        {"name": name, "status": present.get(name, "Vắng")}
        for name in all_people
    ]
    
    return render_template("attendance.html", class_name=class_name, students=students)

@app.route("/class/<class_name>/recognize", methods=["POST"])
def recognize(class_name):
    """
    ===== CORE ENDPOINT - Nhận diện khuôn mặt =====
    Tối ưu cho nhiều device cùng kết nối
    """
    start_time = time.time()
    
    try:
        ensure_class(class_name)
        
        if 'image' not in request.files:
            return jsonify({"name": "Unknown", "error": "No image"}), 400
        
        img_bytes = request.files['image'].read()
        
        # Save last upload for debugging
        class_dir = os.path.join(BASE_DIR, class_name)
        last_img_path = os.path.join(class_dir, "last_upload.jpg")
        try:
            with open(last_img_path, "wb") as f:
                f.write(img_bytes)
        except:
            pass
        
        # ===== PROCESS RECOGNITION =====
        name, confidence, error = process_face_recognition(class_name, img_bytes)
        
        # Record attendance if recognized
        if name != "Unknown":
            record_attendance(class_name, name)
        
        elapsed = time.time() - start_time
        logger.info(f"[{class_name}] {name} ({confidence:.3f}) - {elapsed:.3f}s")
        
        return jsonify({
            "name": name,
            "confidence": float(confidence),
            "time": round(elapsed, 3)
        })
    
    except Exception as e:
        logger.error(f"Recognize error: {e}")
        return jsonify({"name": "Unknown", "error": str(e)}), 500

@app.route("/class/<class_name>/add_student", methods=["GET", "POST"])
def add_student(class_name):
    """Thêm học sinh mới"""
    class_dir = ensure_class(class_name)
    
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        files = request.files.getlist("images")
        
        if not name or not files:
            return "Missing name or images", 400
        
        person_dir = os.path.join(class_dir, "known_faces", name)
        os.makedirs(person_dir, exist_ok=True)
        
        for file in files:
            fname = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
            file.save(os.path.join(person_dir, fname))
        
        # Rebuild encodings in background
        threading.Thread(
            target=lambda: (
                build_encodings_for_class(class_dir),
                reload_cache(class_name)
            ),
            daemon=True
        ).start()
        
        return redirect(url_for("class_home", class_name=class_name))
    
    return render_template("add_student.html", class_name=class_name)

@app.route("/class/<class_name>/history")
def attendance_history(class_name):
    """Lịch sử điểm danh"""
    ensure_class(class_name)
    db = DB_CONNECTIONS[class_name]
    
    rows = db.execute(
        "SELECT name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC"
    )
    
    return render_template("attendance_history.html", class_name=class_name, records=rows)

@app.route("/class/<class_name>/export_excel")
def export_excel_class(class_name):
    """Export điểm danh ra Excel"""
    ensure_class(class_name)
    db = DB_CONNECTIONS[class_name]
    
    rows = db.execute(
        "SELECT name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC"
    )
    
    excel_path = f"{class_name}_attendance.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Điểm danh"
    ws.append(["Tên học sinh", "Ngày", "Giờ điểm danh", "Trạng thái"])
    
    for row in rows:
        ws.append(row)
    
    for column_cells in ws.columns:
        max_len = max(len(str(cell.value)) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = max_len + 2
    
    wb.save(excel_path)
    return send_file(excel_path, as_attachment=True)

# ==================================================================================
# BACKGROUND TASKS
# ==================================================================================

def reset_attendance_daily():
    """Tự động xóa điểm danh lúc 13h và 18h"""
    while True:
        now = datetime.datetime.now()
        noon = now.replace(hour=13, minute=0, second=0, microsecond=0)
        evening = now.replace(hour=18, minute=0, second=0, microsecond=0)
        
        if now < noon:
            next_reset = noon
        elif now < evening:
            next_reset = evening
        else:
            next_reset = (now + datetime.timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
        
        sleep_time = (next_reset - now).total_seconds()
        logger.info(f"[Scheduler] Next reset: {next_reset.strftime('%d/%m/%Y %H:%M')} (in {sleep_time/3600:.1f}h)")
        time.sleep(sleep_time)
        
        logger.info("[Reset] Starting attendance reset...")
        if os.path.exists(BASE_DIR):
            for class_name in os.listdir(BASE_DIR):
                if class_name in DB_CONNECTIONS:
                    try:
                        db = DB_CONNECTIONS[class_name]
                        db.execute("DELETE FROM attendance")
                        logger.info(f"  ✓ Reset {class_name}")
                    except Exception as e:
                        logger.error(f"  ✗ Error resetting {class_name}: {e}")
        
        logger.info("[Reset] Complete.")

# ==================================================================================
# MAIN
# ==================================================================================

if __name__ == "__main__":
    # Start background scheduler
    threading.Thread(target=reset_attendance_daily, daemon=True).start()
    
    # Run Flask with threading enabled
    app.run(
        host="192.168.1.173",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False
    )