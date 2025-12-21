from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from typing import Dict
from openpyxl import load_workbook, Workbook
import os, sqlite3, pickle, datetime, threading, time, json, secrets
import base64
import signal
import sys
import uuid
from io import BytesIO

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.environ.get("BASE_DIR") or os.path.join(PROJECT_ROOT, "classes")
DS_DIR = os.environ.get("DS_DIR") or os.path.join(BASE_DIR, "DS")
SYSTEM_DIR = os.environ.get("SYSTEM_DIR") or os.path.join(BASE_DIR, "_system")
TOLERANCE, DETECTION_MODEL = 0.5, "hog"

app = Flask(__name__)

def _abs_path(path: str) -> str:
    return os.path.abspath(path)

def _safe_join(base_dir: str, *paths: str) -> str:
    base_abs = _abs_path(base_dir)
    combined = _abs_path(os.path.join(base_dir, *paths))
    if combined == base_abs:
        return combined
    if not combined.startswith(base_abs + os.sep):
        raise ValueError("Invalid path")
    return combined

def _get_or_create_secret_key() -> str:
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    try:
        os.makedirs(SYSTEM_DIR, exist_ok=True)
        secret_path = os.path.join(SYSTEM_DIR, "flask_secret_key")
        if os.path.exists(secret_path):
            with open(secret_path, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        key = secrets.token_hex(32)
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(key)
        try:
            os.chmod(secret_path, 0o600)
        except Exception:
            pass
        return key
    except Exception:
        return secrets.token_hex(32)

app.secret_key = _get_or_create_secret_key()

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
MAX_IMAGES_PER_STUDENT = int(os.environ.get("MAX_IMAGES_PER_STUDENT", "10"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Vui lòng đăng nhập để truy cập.'

# MQTT Configuration
MQTT_BROKER = os.environ.get('MQTT_BROKER', 'broker.hivemq.com')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_KEEPALIVE = 60

# Global variables
VALID_API_KEYS = {}
LOCKS = {}
ENCODINGS_CACHE = {}
ENCODINGS_LOCK = threading.Lock()
image_buffer = {}
mqtt_client = None
mqtt_connected = False
mqtt_lock_file = None
cv2 = None
np = None
face_recognition = None
STUDENT_LIST_CACHE = {}
CLASSES_CACHE = {"value": None, "mtime": None}

def lazy_load_cv2():
    """Lazy load OpenCV"""
    global cv2, np
    if cv2 is None:
        import cv2 as cv2_module
        import numpy as np_module
        cv2 = cv2_module
        np = np_module
    return cv2, np

def lazy_load_face_recognition():
    """Lazy load face_recognition"""
    global face_recognition
    if face_recognition is None:
        import face_recognition as fr_module
        face_recognition = fr_module
    return face_recognition

# ============================================================
# HELPER FUNCTIONS - CLASS MANAGEMENT
# ============================================================
def get_all_classes():
    """Lấy danh sách tất cả các lớp từ file DS_*.xlsx"""
    global CLASSES_CACHE
    classes = []
    try:
        ds_candidates = [DS_DIR, BASE_DIR]
        sig_parts = []
        for p in ds_candidates:
            try:
                sig_parts.append(str(os.path.getmtime(p)) if os.path.exists(p) else "None")
            except OSError:
                sig_parts.append("None")
        signature = "|".join(sig_parts)
        if CLASSES_CACHE["value"] is not None and CLASSES_CACHE["mtime"] == signature:
            return CLASSES_CACHE["value"]

        found_any = False
        for directory in ds_candidates:
            print(f"📂 Checking directory: {directory}")
            if not os.path.exists(directory):
                if directory == DS_DIR:
                    print(f"⚠️ Directory not found: {directory}, creating...")
                    os.makedirs(directory, exist_ok=True)
                continue

            files = os.listdir(directory)
            print(f"📄 Files in {directory}: {files}")

            for filename in files:
                if filename.startswith('DS_') and filename.lower().endswith('.xlsx'):
                    class_name = filename[3:-5]
                    classes.append(class_name)
                    found_any = True
                    print(f"✅ Found class: {class_name}")

            if found_any:
                break
        
        classes = sorted(classes)
        print(f"📊 Total classes found: {len(classes)}")
        CLASSES_CACHE = {"value": classes, "mtime": signature}
        return classes
    except Exception as e:
        print(f"❌ Error in get_all_classes: {e}")
        return []

def ensure_class_structure(class_name):
    """Đảm bảo cấu trúc thư mục cho lớp"""
    class_dir = _safe_join(BASE_DIR, class_name)
    known_faces_dir = os.path.join(class_dir, "known_faces")
    os.makedirs(known_faces_dir, exist_ok=True)
    
    db_path = os.path.join(class_dir, "attendance.db")
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            with conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS attendance(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id TEXT,
                        name TEXT,
                        date TEXT,
                        first_time TEXT,
                        status TEXT,
                        timestamp_iso TEXT)""")
        finally:
            conn.close()
    
    if class_name not in LOCKS:
        LOCKS[class_name] = threading.Lock()
    
    return class_dir

def validate_class_exists(class_name):
    """Kiểm tra lớp có tồn tại trong danh sách hay không"""
    return class_name in get_all_classes()

def load_student_list(class_name: str) -> Dict[str, str]:
    """Load danh sách học sinh từ Excel"""
    file_path = _safe_join(DS_DIR, f"DS_{class_name}.xlsx")
    if not os.path.exists(file_path):
        print(f"⚠️ Student list not found: {file_path}")
        return {}
    try:
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            mtime = None
        cached = STUDENT_LIST_CACHE.get(class_name)
        if cached and cached[0] == mtime:
            return cached[1]

        wb = load_workbook(file_path, read_only=True)
        ws = wb.active
        students = {}
        for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
            if row[0] and row[1]:
                students[str(row[0]).strip()] = str(row[1]).strip()
        wb.close()
        print(f"✅ Loaded {len(students)} students from {class_name}")
        STUDENT_LIST_CACHE[class_name] = (mtime, students)
        return students
    except Exception as e:
        print(f"❌ Error reading {file_path}: {e}")
        return {}

def get_student_name(class_name: str, student_id: str) -> str:
    students = load_student_list(class_name)
    return students.get(str(student_id), "Unknown")

def get_status_by_time(now):
    morning_limit = now.replace(hour=6, minute=45, second=0, microsecond=0)
    afternoon_limit = now.replace(hour=13, minute=15, second=0, microsecond=0)
    if now.hour < 12:
        return "Trễ" if now > morning_limit else "Có mặt"
    return "Trễ" if now > afternoon_limit else "Có mặt"

# ============================================================
# USER MODEL
# ============================================================
class User(UserMixin):
    def __init__(self, id, username, password_hash, role='user'):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "users.db"), timeout=30)
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id=?", (user_id,))
            row = c.fetchone()
        finally:
            conn.close()
        if row:
            return User(row[0], row[1], row[2], row[3])
    except Exception as e:
        print(f"❌ Error loading user: {e}")
    return None

# ============================================================
# API KEY MANAGEMENT
# ============================================================
def generate_api_key():
    return 'esp32_' + secrets.token_urlsafe(32)

def load_api_keys():
    """Load API keys từ database vào memory"""
    global VALID_API_KEYS
    try:
        conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "api_keys.db"), timeout=30)
        try:
            c = conn.cursor()
            c.execute("SELECT api_key, class_name, device_name, created_at FROM api_keys WHERE is_active=1")
            VALID_API_KEYS = {}
            for row in c.fetchall():
                if not validate_class_exists(row[1]):
                    continue
                VALID_API_KEYS[row[0]] = {
                    'class_name': row[1],
                    'device_name': row[2],
                    'created_at': row[3]
                }
        finally:
            conn.close()
        print(f"✅ Loaded {len(VALID_API_KEYS)} API keys")
    except Exception as e:
        print(f"❌ Error loading API keys: {e}")

def verify_api_key(api_key, class_name):
    """Verify API key và class name"""
    if not validate_class_exists(class_name):
        return False
    if api_key in VALID_API_KEYS:
        if VALID_API_KEYS[api_key]['class_name'] == class_name:
            return True
    return False

@app.context_processor
def inject_globals():
    return {
        "mqtt_connected": mqtt_connected,
        "max_upload_mb": MAX_UPLOAD_MB,
    }

# ============================================================
# AUTHENTICATION ROUTES
# ============================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "users.db"), timeout=30)
            try:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username=?", (username,))
                row = c.fetchone()
            finally:
                conn.close()
            
            if row and check_password_hash(row[2], password):
                user = User(row[0], row[1], row[2], row[3])
                login_user(user)
                print(f"✅ User logged in: {username}")
                next_page = request.args.get('next')
                return redirect(next_page if next_page else url_for('index'))
            else:
                flash('Tên đăng nhập hoặc mật khẩu không đúng', 'error')
        except Exception as e:
            print(f"❌ Login error: {e}")
            flash('Lỗi hệ thống, vui lòng thử lại', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Đã đăng xuất thành công', 'success')
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not check_password_hash(current_user.password_hash, old_password):
            flash('Mật khẩu cũ không đúng', 'error')
        elif new_password != confirm_password:
            flash('Mật khẩu mới không khớp', 'error')
        elif len(new_password) < 6:
            flash('Mật khẩu phải có ít nhất 6 ký tự', 'error')
        else:
            try:
                conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "users.db"), timeout=30)
                try:
                    c = conn.cursor()
                    new_hash = generate_password_hash(new_password)
                    c.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, current_user.id))
                    conn.commit()
                finally:
                    conn.close()
                flash('Đổi mật khẩu thành công', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                print(f"❌ Password change error: {e}")
                flash('Lỗi đổi mật khẩu', 'error')
    
    return render_template('change_password.html')

# ============================================================
# CLASS MANAGEMENT ROUTES
# ============================================================
@app.route('/classes/manage')
@login_required
def manage_classes():
    """Trang quản lý danh sách lớp"""
    classes = get_all_classes()
    print(f"🔍 manage_classes route - Found {len(classes)} classes: {classes}")
    return render_template('manage_classes.html', classes=classes)

@app.route('/classes/template')
@login_required
def download_class_template():
    wb = Workbook()
    ws = wb.active
    ws.title = "Danh sách"
    ws.append(["Mã học sinh", "Tên học sinh"])
    ws.append(["001", "Nguyễn Văn A"])
    ws.append(["002", "Trần Thị B"])
    ws.append(["003", "Lê Văn C"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio,
        as_attachment=True,
        download_name="DS_Mau.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@app.route('/classes/upload', methods=['POST'])
@login_required
def upload_class_list():
    """Upload file Excel danh sách lớp"""
    if 'file' not in request.files:
        flash('Không có file được chọn', 'error')
        return redirect(url_for('manage_classes'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('Không có file được chọn', 'error')
        return redirect(url_for('manage_classes'))
    
    if not file.filename.lower().endswith('.xlsx'):
        flash('Chỉ chấp nhận file .xlsx', 'error')
        return redirect(url_for('manage_classes'))
    
    try:
        os.makedirs(DS_DIR, exist_ok=True)
        filename = secure_filename(file.filename)
        
        if not filename.startswith('DS_'):
            flash('Tên file phải có định dạng: DS_TenLop.xlsx (ví dụ: DS_12T1.xlsx)', 'error')
            return redirect(url_for('manage_classes'))
        
        filepath = _safe_join(DS_DIR, filename)
        file.save(filepath)
        print(f"💾 Saved file: {filepath}")
        
        try:
            wb = load_workbook(filepath, read_only=True)
            ws = wb.active
            
            header = [cell.value for cell in ws[1]]
            if len(header) < 2:
                os.remove(filepath)
                flash('File Excel phải có ít nhất 2 cột: Mã học sinh và Tên học sinh', 'error')
                return redirect(url_for('manage_classes'))
            
            student_count = sum(1 for row in ws.iter_rows(min_row=2, max_col=2, values_only=True) if row[0] and row[1])
            wb.close()
            
            class_name = filename[3:-5]
            ensure_class_structure(class_name)
            STUDENT_LIST_CACHE.pop(class_name, None)
            CLASSES_CACHE["value"] = None
            CLASSES_CACHE["mtime"] = None
            
            flash(f'Tải lên thành công! Lớp {class_name} có {student_count} học sinh', 'success')
            print(f"✅ Class {class_name} uploaded with {student_count} students")
            
        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            flash(f'File Excel không hợp lệ: {str(e)}', 'error')
            print(f"❌ Excel validation error: {e}")
            return redirect(url_for('manage_classes'))
        
    except Exception as e:
        print(f"❌ Upload error: {e}")
        flash(f'Lỗi tải file: {str(e)}', 'error')
    
    return redirect(url_for('manage_classes'))

@app.route('/classes/delete/<class_name>', methods=['POST'])
@login_required
def delete_class(class_name):
    """Xóa lớp học"""
    try:
        ds_file = _safe_join(DS_DIR, f"DS_{class_name}.xlsx")
        if os.path.exists(ds_file):
            os.remove(ds_file)
            print(f"🗑️ Deleted file: {ds_file}")
        STUDENT_LIST_CACHE.pop(class_name, None)
        CLASSES_CACHE["value"] = None
        CLASSES_CACHE["mtime"] = None
        
        try:
            conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "api_keys.db"), timeout=30)
            try:
                c = conn.cursor()
                c.execute("DELETE FROM api_keys WHERE class_name=?", (class_name,))
                deleted_count = c.rowcount
                conn.commit()
            finally:
                conn.close()
            
            if deleted_count > 0:
                load_api_keys()
                print(f"🗑️ Deleted {deleted_count} API keys for class {class_name}")
        except Exception as e:
            print(f"⚠️ Error deleting API keys: {e}")
        
        flash(f'Đã xóa lớp {class_name}', 'success')
    except Exception as e:
        print(f"❌ Delete error: {e}")
        flash(f'Lỗi xóa lớp: {str(e)}', 'error')
    
    return redirect(url_for('manage_classes'))

# ============================================================
# API KEY ROUTES
# ============================================================
@app.route('/api_keys')
@login_required
def manage_api_keys():
    try:
        available_classes = get_all_classes()
        
        conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "api_keys.db"), timeout=30)
        try:
            c = conn.cursor()
            c.execute("SELECT id, api_key, class_name, device_name, created_at, is_active FROM api_keys ORDER BY created_at DESC")
            keys = c.fetchall()
        finally:
            conn.close()
        return render_template('api_keys.html', keys=keys, available_classes=available_classes)
    except Exception as e:
        print(f"❌ Error loading API keys: {e}")
        flash('Lỗi tải API keys', 'error')
        return render_template('api_keys.html', keys=[], available_classes=[])

@app.route('/api_keys/create', methods=['POST'])
@login_required
def create_api_key():
    class_name = request.form.get('class_name')
    device_name = request.form.get('device_name', '').strip()
    
    if not class_name:
        flash('Vui lòng chọn lớp', 'error')
        return redirect(url_for('manage_api_keys'))
    
    if not validate_class_exists(class_name):
        flash(f'Lớp {class_name} không tồn tại trong hệ thống', 'error')
        return redirect(url_for('manage_api_keys'))
    
    try:
        api_key = generate_api_key()
        conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "api_keys.db"), timeout=30)
        try:
            c = conn.cursor()
            c.execute("INSERT INTO api_keys (api_key, class_name, device_name, created_at) VALUES (?, ?, ?, ?)",
                     (api_key, class_name, device_name, datetime.datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()
        
        load_api_keys()
        flash(f'Tạo API key thành công cho lớp {class_name}', 'success')
    except Exception as e:
        print(f"❌ Error creating API key: {e}")
        flash('Lỗi tạo API key', 'error')
    
    return redirect(url_for('manage_api_keys'))

@app.route('/api_keys/delete/<int:key_id>', methods=['POST'])
@login_required
def delete_api_key(key_id):
    try:
        conn = sqlite3.connect(_safe_join(SYSTEM_DIR, "api_keys.db"), timeout=30)
        try:
            c = conn.cursor()
            c.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
            conn.commit()
        finally:
            conn.close()
        
        load_api_keys()
        flash('Đã xóa API key', 'success')
    except Exception as e:
        print(f"❌ Error deleting API key: {e}")
        flash('Lỗi xóa API key', 'error')
    
    return redirect(url_for('manage_api_keys'))

# ============================================================
# FACE RECOGNITION FUNCTIONS
# ============================================================
def get_encodings_data(class_name):
    with ENCODINGS_LOCK:
        cached = ENCODINGS_CACHE.get(class_name)
    if cached is not None:
        return cached
    
    class_dir = ensure_class_structure(class_name)
    enc_path = os.path.join(class_dir, "encodings.pkl")
    if not os.path.exists(enc_path):
        from encode_known_faces import build_encodings_for_class
        data = build_encodings_for_class(class_dir)
    else:
        with open(enc_path, "rb") as f:
            data = pickle.load(f)
    
    with ENCODINGS_LOCK:
        ENCODINGS_CACHE[class_name] = data
    return data

def reload_cache(class_name):
    class_dir = ensure_class_structure(class_name)
    enc_path = os.path.join(class_dir, "encodings.pkl")
    if os.path.exists(enc_path):
        with open(enc_path, "rb") as f:
            with ENCODINGS_LOCK:
                ENCODINGS_CACHE[class_name] = pickle.load(f)

def record_attendance(class_name, student_id):
    student_name = get_student_name(class_name, student_id)
    class_dir = ensure_class_structure(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    lock = LOCKS.setdefault(class_name, threading.Lock())
    with lock:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            c = conn.cursor()
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            now = datetime.datetime.now()
            time_str = now.strftime("%H:%M:%S")
            iso = now.isoformat(sep=" ", timespec="seconds")
            status = get_status_by_time(now)
            exists = c.execute("SELECT 1 FROM attendance WHERE student_id=? AND date=?",
                              (student_id, today)).fetchone()
            if not exists:
                c.execute("""INSERT INTO attendance(student_id, name, date, first_time, status, timestamp_iso)
                            VALUES(?,?,?,?,?,?)""",
                         (student_id, student_name, today, time_str, status, iso))
                conn.commit()
        finally:
            conn.close()

def recognize_face_from_image(class_name: str, img_bytes: bytes):
    start_time = time.time()
    
    cv2_lib, np_lib = lazy_load_cv2()
    fr_lib = lazy_load_face_recognition()
    
    ensure_class_structure(class_name)
    data = get_encodings_data(class_name)
    
    img_bgr = cv2_lib.imdecode(np_lib.frombuffer(img_bytes, np_lib.uint8), cv2_lib.IMREAD_COLOR)
    if img_bgr is None:
        print(f"[{class_name}] ❌ Invalid image")
        return "Unknown"
    
    img_rgb = cv2_lib.cvtColor(img_bgr, cv2_lib.COLOR_BGR2RGB)
    locs = fr_lib.face_locations(img_rgb, model=DETECTION_MODEL)
    
    if len(locs) == 0:
        print(f"[{class_name}] ❌ No face detected | {time.time() - start_time:.3f}s")
        return "Unknown"
    
    encs = fr_lib.face_encodings(img_rgb, locs)
    best_face_idx = 0
    
    if len(locs) > 1:
        areas = [(loc[2] - loc[0]) * (loc[1] - loc[3]) for loc in locs]
        best_face_idx = np_lib.argmax(areas)
    
    enc = encs[best_face_idx]
    matches = fr_lib.compare_faces(data["encodings"], enc, TOLERANCE)
    dist = fr_lib.face_distance(data["encodings"], enc)
    
    recognized_name = "Unknown"
    if len(dist) > 0:
        best = np_lib.argmin(dist)
        if matches[best]:
            student_id = data["names"][best]
            recognized_name = get_student_name(class_name, student_id)
            threading.Thread(target=record_attendance, args=(class_name, student_id), daemon=True).start()
    
    elapsed = time.time() - start_time
    print(f"[{class_name}] ✅ {recognized_name} | {elapsed:.3f}s")
    return recognized_name

# ============================================================
# MQTT SETUP
# ============================================================
def init_mqtt():
    """Initialize MQTT client lazily"""
    global mqtt_client, mqtt_connected, mqtt_lock_file
    
    try:
        if mqtt_client is not None:
            return

        os.makedirs(SYSTEM_DIR, exist_ok=True)
        try:
            import fcntl
            mqtt_lock_file = open(os.path.join(SYSTEM_DIR, "mqtt.lock"), "w")
            try:
                fcntl.flock(mqtt_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                mqtt_connected = False
                try:
                    mqtt_lock_file.close()
                except Exception:
                    pass
                mqtt_lock_file = None
                return
        except Exception:
            mqtt_lock_file = None

        import paho.mqtt.client as mqtt
        
        def purge_old_buffers(now_ts: float):
            stale = []
            for k, v in list(image_buffer.items()):
                ts = v.get("received_at")
                if ts is not None and now_ts - ts > 60:
                    stale.append(k)
            for k in stale:
                del image_buffer[k]

        def on_connect(client, userdata, flags, rc):
            global mqtt_connected
            if rc == 0:
                mqtt_connected = True
                print("✅ Connected to MQTT Broker")
                client.subscribe("esp32cam/+/image/#")
                print("📡 Subscribed: esp32cam/+/image/#")
            else:
                mqtt_connected = False
                print(f"❌ MQTT connection failed, rc={rc}")
        
        def on_message(client, userdata, msg):
            topic = msg.topic
            payload = msg.payload
            parts = topic.split("/")
            if len(parts) < 4:
                return
            class_name = parts[1]
            message_type = parts[3]
            
            if class_name not in image_buffer:
                image_buffer[class_name] = {"chunks": {}, "meta": {}, "api_key": None, "received_at": time.time(), "expected_chunks": None}
            image_buffer[class_name]["received_at"] = time.time()
            purge_old_buffers(image_buffer[class_name]["received_at"])
            
            if message_type == "meta":
                try:
                    meta = json.loads(payload.decode())
                    api_key = meta.get('api_key')
                    
                    if not api_key or not verify_api_key(api_key, meta.get('class', class_name)):
                        print(f"[{class_name}] ❌ Invalid API Key")
                        client.publish(f"esp32cam/{class_name}/result", 
                                     json.dumps({"name": "Unauthorized", "error": "Invalid API key"}))
                        return
                    
                    image_buffer[class_name]["meta"] = meta
                    image_buffer[class_name]["api_key"] = api_key
                    image_buffer[class_name]["chunks"] = {}
                    image_buffer[class_name]["expected_chunks"] = meta.get("chunks")
                    print(f"[{class_name}] 📥 Meta received: {meta.get('chunks')} chunks")
                except Exception as e:
                    print(f"[{class_name}] ❌ Error parsing meta: {e}")
            
            elif message_type == "chunk":
                if not image_buffer[class_name].get("api_key"):
                    return
                if len(parts) < 5:
                    return
                try:
                    chunk_id = int(parts[4])
                except Exception:
                    return
                image_buffer[class_name]["chunks"][chunk_id] = payload.decode(errors="ignore")
            
            elif message_type == "done":
                if not image_buffer[class_name].get("api_key"):
                    return
                
                print(f"[{class_name}] ⚙️ Processing...")
                try:
                    expected = image_buffer[class_name].get("expected_chunks")
                    chunks_dict = image_buffer[class_name]["chunks"]
                    if expected is not None and len(chunks_dict) != int(expected):
                        raise ValueError(f"Missing chunks: expected={expected}, got={len(chunks_dict)}")
                    sorted_chunks = [chunks_dict[i] for i in sorted(chunks_dict.keys())]
                    base64_image = "".join(sorted_chunks)
                    try:
                        img_bytes = base64.b64decode(base64_image, validate=True)
                    except Exception:
                        img_bytes = base64.b64decode(base64_image)
                    recognized_name = recognize_face_from_image(class_name, img_bytes)
                    result_topic = f"esp32cam/{class_name}/result"
                    result_json = json.dumps({"name": recognized_name})
                    client.publish(result_topic, result_json)
                    print(f"[{class_name}] 📤 Result sent: {recognized_name}")
                    del image_buffer[class_name]
                except Exception as e:
                    print(f"[{class_name}] ❌ Processing error: {e}")
                    client.publish(f"esp32cam/{class_name}/result", 
                                 json.dumps({"name": "Unknown", "error": str(e)}))
                    if class_name in image_buffer:
                        del image_buffer[class_name]
        
        mqtt_client = mqtt.Client(client_id=f"railway-{uuid.uuid4().hex[:8]}")
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
        mqtt_client.loop_start()
        print("📡 MQTT client initialized (async)")
        
    except Exception as e:
        print(f"⚠️ MQTT initialization warning: {e}")
        mqtt_connected = False

# ============================================================
# WEB ROUTES
# ============================================================
@app.route("/")
@login_required
def index():
    try:
        print("🏠 Index route called")
        data = []
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        all_classes = get_all_classes()
        print(f"📊 Found {len(all_classes)} classes: {all_classes}")
        
        for class_name in all_classes:
            class_dir = ensure_class_structure(class_name)
            db_path = os.path.join(class_dir, "attendance.db")
            
            students = load_student_list(class_name)
            if not students:
                print(f"⚠️ No students found for {class_name}")
                continue
            
            conn = sqlite3.connect(db_path, timeout=30)
            try:
                c = conn.cursor()
                c.execute("SELECT DISTINCT student_id FROM attendance WHERE date=?", (today,))
                present_ids = {r[0] for r in c.fetchall()}
            finally:
                conn.close()
            
            absent_ids = [sid for sid in students.keys() if sid not in present_ids]
            absent_names = [students[sid] for sid in absent_ids]
            
            data.append({
                "class": class_name,
                "present": len(present_ids),
                "absent": len(absent_ids),
                "absent_names": ", ".join(absent_names)
            })
            print(f"✅ Processed class {class_name}: {len(present_ids)} present, {len(absent_ids)} absent")
        
        print(f"📋 Rendering index with {len(data)} classes")
        return render_template('index.html', classes=data, user=current_user)
    except Exception as e:
        print(f"❌ Index error: {e}")
        import traceback
        traceback.print_exc()
        return render_template('index.html', classes=[], user=current_user)

@app.route("/class/<class_name>/")
@login_required
def class_home(class_name):
    if not validate_class_exists(class_name):
        flash(f'Lớp {class_name} không tồn tại', 'error')
        return redirect(url_for('index'))
    
    class_dir = ensure_class_structure(class_name)
    students_dict = load_student_list(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cur = conn.cursor()
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        cur.execute("SELECT student_id, status FROM attendance WHERE date=?", (today,))
        present_data = cur.fetchall()
    finally:
        conn.close()
    present = {r[0]: r[1] for r in present_data}
    students = []
    for student_id in sorted(students_dict.keys()):
        student_name = students_dict[student_id]
        status = present.get(student_id, "Vắng")
        students.append({"name": student_name, "status": status})
    return render_template('attendance.html', class_name=class_name, students=students, user=current_user)

@app.route("/class/<class_name>/add_student", methods=["GET", "POST"])
@login_required
def add_student(class_name):
    if not validate_class_exists(class_name):
        flash(f'Lớp {class_name} không tồn tại', 'error')
        return redirect(url_for('index'))
    
    class_dir = ensure_class_structure(class_name)
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        files = request.files.getlist("images")
        if not student_id or not files:
            flash("Thiếu mã học sinh hoặc ảnh!", "error")
            return redirect(url_for('add_student', class_name=class_name))
        
        students = load_student_list(class_name)
        if student_id not in students:
            flash(f"Mã học sinh {student_id} không có trong danh sách!", "error")
            return redirect(url_for('add_student', class_name=class_name))

        if len(files) > MAX_IMAGES_PER_STUDENT:
            flash(f"Chỉ cho phép tối đa {MAX_IMAGES_PER_STUDENT} ảnh", "error")
            return redirect(url_for('add_student', class_name=class_name))
        
        try:
            known_faces_dir = os.path.join(class_dir, "known_faces")
            person_dir = _safe_join(known_faces_dir, student_id)
        except Exception:
            flash("Mã học sinh không hợp lệ", "error")
            return redirect(url_for('add_student', class_name=class_name))
        os.makedirs(person_dir, exist_ok=True)
        
        saved = 0
        for file in files:
            original = (file.filename or "").strip()
            ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
            if ext not in {"jpg", "jpeg", "png"}:
                continue

            try:
                from PIL import Image
                file.stream.seek(0)
                img = Image.open(file.stream)
                img.verify()
                file.stream.seek(0)
                img = Image.open(file.stream).convert("RGB")
                fname = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8] + ".jpg"
                img.save(os.path.join(person_dir, fname), format="JPEG", quality=90)
                saved += 1
            except Exception:
                continue

        if saved == 0:
            flash("Không có ảnh hợp lệ để lưu", "error")
            return redirect(url_for('add_student', class_name=class_name))
        
        # Import and build encodings
        from encode_known_faces import build_encodings_for_class
        build_encodings_for_class(class_dir)
        reload_cache(class_name)
        
        flash("Thêm học sinh thành công!", "success")
        return redirect(url_for("class_home", class_name=class_name))
    
    students = load_student_list(class_name)
    student_list = [{"id": sid, "name": name} for sid, name in sorted(students.items())]
    return render_template('add_student.html', class_name=class_name, students=student_list, user=current_user)

@app.route("/class/<class_name>/history")
@login_required
def attendance_history(class_name):
    if not validate_class_exists(class_name):
        flash(f'Lớp {class_name} không tồn tại', 'error')
        return redirect(url_for('index'))
    
    class_dir = ensure_class_structure(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC")
        rows = cur.fetchall()
    finally:
        conn.close()
    return render_template('attendance_history.html', class_name=class_name, records=rows, user=current_user)

@app.route("/class/<class_name>/export_excel")
@login_required
def export_excel_class(class_name):
    if not validate_class_exists(class_name):
        flash(f'Lớp {class_name} không tồn tại', 'error')
        return redirect(url_for('index'))
    
    class_dir = ensure_class_structure(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cur = conn.cursor()
        cur.execute("SELECT student_id, name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC")
        rows = cur.fetchall()
    finally:
        conn.close()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Điểm danh"
    ws.append(["Mã học sinh", "Tên học sinh", "Ngày", "Giờ điểm danh", "Trạng thái"])
    
    for row in rows:
        ws.append(row)
    
    for column_cells in ws.columns:
        max_len = max(len(str(cell.value)) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = max_len + 2
    
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    download_name = secure_filename(f"{class_name}_attendance.xlsx") or "attendance.xlsx"
    return send_file(bio, as_attachment=True, download_name=download_name, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================
# API ENDPOINTS
# ============================================================
@app.route('/api/recognize', methods=['POST'])
def api_recognize():
    """HTTP endpoint cho ESP32 gửi ảnh qua HTTP"""
    try:
        api_key = request.headers.get('X-API-Key')
        class_name = request.headers.get('X-Class-Name')
        
        if not api_key or not class_name:
            return jsonify({"error": "Missing API key or class name"}), 401
        
        if not verify_api_key(api_key, class_name):
            return jsonify({"error": "Invalid API key"}), 401
        
        if not validate_class_exists(class_name):
            return jsonify({"error": "Class not found"}), 404
        
        img_data = request.get_data()
        
        if not img_data:
            return jsonify({"error": "No image data"}), 400
        
        recognized_name = recognize_face_from_image(class_name, img_data)
        
        # Gửi kết quả qua MQTT nếu có
        if mqtt_client and mqtt_connected:
            result_topic = f"esp32cam/{class_name}/result"
            result_json = json.dumps({"name": recognized_name})
            mqtt_client.publish(result_topic, result_json)
        
        print(f"[HTTP API] {class_name}: {recognized_name}")
        
        return jsonify({
            "success": True,
            "name": recognized_name,
            "class": class_name
        }), 200
        
    except Exception as e:
        print(f"❌ API error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/class/<class_name>/count')
@login_required
def api_class_count(class_name):
    """API để lấy số lượng học sinh trong lớp"""
    try:
        students = load_student_list(class_name)
        return jsonify({"count": len(students)}), 200
    except Exception as e:
        return jsonify({"count": 0, "error": str(e)}), 500

@app.route('/api/classes/list')
@login_required
def api_classes_list():
    """API để lấy danh sách tất cả các lớp"""
    try:
        classes = get_all_classes()
        return jsonify({"classes": classes}), 200
    except Exception as e:
        return jsonify({"classes": [], "error": str(e)}), 500

@app.route('/api/class/<class_name>/students')
@login_required
def api_class_students(class_name):
    """API để lấy danh sách học sinh trong lớp"""
    try:
        if not validate_class_exists(class_name):
            return jsonify({"error": "Class not found"}), 404
        
        students = load_student_list(class_name)
        student_list = [{"id": k, "name": v} for k, v in sorted(students.items())]
        
        return jsonify({
            "class": class_name,
            "students": student_list,
            "count": len(student_list)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/class/<class_name>/attendance/today')
@login_required
def api_today_attendance(class_name):
    """API để lấy thông tin điểm danh hôm nay"""
    try:
        if not validate_class_exists(class_name):
            return jsonify({"error": "Class not found"}), 404
        
        class_dir = ensure_class_structure(class_name)
        db_path = os.path.join(class_dir, "attendance.db")
        
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            c = conn.cursor()
            c.execute("SELECT student_id, name, first_time, status FROM attendance WHERE date=?", (today,))
            records = c.fetchall()
        finally:
            conn.close()
        
        attendance_list = []
        for record in records:
            attendance_list.append({
                "student_id": record[0],
                "name": record[1],
                "time": record[2],
                "status": record[3]
            })
        
        return jsonify({
            "class": class_name,
            "date": today,
            "attendance": attendance_list,
            "present_count": len(attendance_list)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    """Health check endpoint"""
    global mqtt_connected
    return jsonify({
        "status": "healthy",
        "mqtt": "connected" if mqtt_connected else "disconnected",
        "classes": len(get_all_classes())
    }), 200

# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Not found"}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Internal server error"}), 500
    return render_template('500.html'), 500

@app.errorhandler(413)
def request_too_large(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": f"Payload too large (max {MAX_UPLOAD_MB}MB)"}), 413
    flash(f"Tệp tải lên quá lớn (tối đa {MAX_UPLOAD_MB}MB)", "error")
    return redirect(request.referrer or url_for("index"))

# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================
# ============================================================
# STARTUP
# ============================================================
def initialize_app():
    """Initialize app on startup"""
    print("\n" + "="*70)
    print("🚀 INITIALIZING FACE RECOGNITION ATTENDANCE SYSTEM")
    print("="*70 + "\n")
    
    # Ensure directories exist
    os.makedirs(DS_DIR, exist_ok=True)
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(SYSTEM_DIR, exist_ok=True)
    print(f"✅ Created directories: {DS_DIR}, {BASE_DIR}")
    
    # Check for existing classes
    classes = get_all_classes()
    print(f"📚 Found {len(classes)} existing classes: {classes}")
    
    # Load API keys
    print("🔑 Loading API keys...")
    load_api_keys()
    
    # Initialize MQTT (async)
    print("📡 Initializing MQTT client...")
    init_mqtt()
    
    print("\n" + "="*70)
    print("✅ SYSTEM READY")
    print("="*70 + "\n")

def _migrate_legacy_db(filename: str):
    legacy = os.path.join(os.getcwd(), filename)
    target = _safe_join(SYSTEM_DIR, filename)
    if os.path.exists(target) or not os.path.exists(legacy):
        return
    try:
        os.replace(legacy, target)
    except Exception:
        try:
            import shutil
            shutil.copy2(legacy, target)
        except Exception:
            pass

_migrate_legacy_db("users.db")
_migrate_legacy_db("api_keys.db")
initialize_app()

if __name__ == "__main__":
    def signal_handler(sig, frame):
        print('\n🛑 Shutting down gracefully...')
        if mqtt_client:
            mqtt_client.disconnect()
            print('✅ MQTT disconnected')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Development mode
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print(f"\n🌐 Starting Flask server on port {port}")
    print(f"🔧 Debug mode: {debug}\n")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
