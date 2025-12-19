from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, session, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from encode_known_faces import build_encodings_for_class
from typing import Dict
from openpyxl import load_workbook, Workbook
import os, sqlite3, pickle, cv2, numpy as np, face_recognition
import datetime, threading, time, json, secrets
import paho.mqtt.client as mqtt
import base64
import signal
import sys
import uuid

DS_DIR = "classes/DS"
BASE_DIR = "classes"
TOLERANCE, DETECTION_MODEL = 0.5, "hog"

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Vui lòng đăng nhập để truy cập.'

# MQTT Configuration
MQTT_BROKER = os.environ.get('MQTT_BROKER', 'broker.hivemq.com')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
MQTT_KEEPALIVE = 60

# API Key cho ESP32
VALID_API_KEYS = {}

LOCKS = {}
ENCODINGS_CACHE = {}
image_buffer = {}

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
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = c.fetchone()
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
        conn = sqlite3.connect('api_keys.db')
        c = conn.cursor()
        c.execute("SELECT api_key, class_name, device_name, created_at FROM api_keys WHERE is_active=1")
        VALID_API_KEYS = {}
        for row in c.fetchall():
            VALID_API_KEYS[row[0]] = {
                'class_name': row[1],
                'device_name': row[2],
                'created_at': row[3]
            }
        conn.close()
        print(f"✅ Loaded {len(VALID_API_KEYS)} API keys")
    except Exception as e:
        print(f"❌ Error loading API keys: {e}")

def verify_api_key(api_key, class_name):
    if api_key in VALID_API_KEYS:
        if VALID_API_KEYS[api_key]['class_name'] == class_name:
            return True
    return False

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
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username=?", (username,))
            row = c.fetchone()
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
                conn = sqlite3.connect('users.db')
                c = conn.cursor()
                new_hash = generate_password_hash(new_password)
                c.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, current_user.id))
                conn.commit()
                conn.close()
                flash('Đổi mật khẩu thành công', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                print(f"❌ Password change error: {e}")
                flash('Lỗi đổi mật khẩu', 'error')
    
    return render_template('change_password.html')

# ============================================================
# API KEY ROUTES
# ============================================================
@app.route('/api_keys')
@login_required
def manage_api_keys():
    try:
        conn = sqlite3.connect('api_keys.db')
        c = conn.cursor()
        c.execute("SELECT id, api_key, class_name, device_name, created_at, is_active FROM api_keys ORDER BY created_at DESC")
        keys = c.fetchall()
        conn.close()
        return render_template('api_keys.html', keys=keys)
    except Exception as e:
        print(f"❌ Error loading API keys: {e}")
        flash('Lỗi tải API keys', 'error')
        return render_template('api_keys.html', keys=[])

@app.route('/api_keys/create', methods=['POST'])
@login_required
def create_api_key():
    class_name = request.form.get('class_name')
    device_name = request.form.get('device_name')
    
    if not class_name:
        flash('Vui lòng chọn lớp', 'error')
        return redirect(url_for('manage_api_keys'))
    
    try:
        api_key = generate_api_key()
        conn = sqlite3.connect('api_keys.db')
        c = conn.cursor()
        c.execute("INSERT INTO api_keys (api_key, class_name, device_name, created_at) VALUES (?, ?, ?, ?)",
                 (api_key, class_name, device_name, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        load_api_keys()
        flash(f'Tạo API key thành công: {api_key}', 'success')
    except Exception as e:
        print(f"❌ Error creating API key: {e}")
        flash('Lỗi tạo API key', 'error')
    
    return redirect(url_for('manage_api_keys'))

@app.route('/api_keys/delete/<int:key_id>', methods=['POST'])
@login_required
def delete_api_key(key_id):
    try:
        conn = sqlite3.connect('api_keys.db')
        c = conn.cursor()
        c.execute("UPDATE api_keys SET is_active=0 WHERE id=?", (key_id,))
        conn.commit()
        conn.close()
        
        load_api_keys()
        flash('Đã vô hiệu hóa API key', 'success')
    except Exception as e:
        print(f"❌ Error deleting API key: {e}")
        flash('Lỗi xóa API key', 'error')
    
    return redirect(url_for('manage_api_keys'))

@app.route("/health")
def health():
    """Health check endpoint for Railway/Docker"""
    return jsonify({"status": "healthy"}), 200

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def load_student_list(class_name: str) -> Dict[str, str]:
    file_path = os.path.join(DS_DIR, f"DS_{class_name}.xlsx")
    if not os.path.exists(file_path):
        return {}
    try:
        wb = load_workbook(file_path, read_only=True)
        ws = wb.active
        students = {}
        for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
            if row[0] and row[1]:
                students[str(row[0]).strip()] = str(row[1]).strip()
        wb.close()
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

def ensure_class(class_name):
    class_dir = os.path.join(BASE_DIR, class_name)
    os.makedirs(os.path.join(class_dir, "known_faces"), exist_ok=True)
    db_path = os.path.join(class_dir, "attendance.db")
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS attendance(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT,
                    name TEXT,
                    date TEXT,
                    first_time TEXT,
                    status TEXT,
                    timestamp_iso TEXT)""")
        conn.close()
    if class_name not in LOCKS:
        LOCKS[class_name] = threading.Lock()
    return class_dir

def get_encodings_data(class_name):
    if class_name in ENCODINGS_CACHE:
        return ENCODINGS_CACHE[class_name]
    enc_path = os.path.join(BASE_DIR, class_name, "encodings.pkl")
    if not os.path.exists(enc_path):
        data = build_encodings_for_class(os.path.join(BASE_DIR, class_name))
    else:
        with open(enc_path, "rb") as f:
            data = pickle.load(f)
    ENCODINGS_CACHE[class_name] = data
    return data

def reload_cache(class_name):
    enc_path = os.path.join(BASE_DIR, class_name, "encodings.pkl")
    if os.path.exists(enc_path):
        with open(enc_path, "rb") as f:
            ENCODINGS_CACHE[class_name] = pickle.load(f)

def record_attendance(class_name, student_id):
    student_name = get_student_name(class_name, student_id)
    db_path = os.path.join(BASE_DIR, class_name, "attendance.db")
    with LOCKS[class_name]:
        conn = sqlite3.connect(db_path)
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
        conn.close()

def recognize_face_from_image(class_name: str, img_bytes: bytes):
    start_time = time.time()
    ensure_class(class_name)
    data = get_encodings_data(class_name)
    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        print(f"[{class_name}] ❌ Invalid image")
        return "Unknown"
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    locs = face_recognition.face_locations(img_rgb, model=DETECTION_MODEL)
    if len(locs) == 0:
        print(f"[{class_name}] ❌ No face detected | {time.time() - start_time:.3f}s")
        return "Unknown"
    encs = face_recognition.face_encodings(img_rgb, locs)
    best_face_idx = 0
    if len(locs) > 1:
        areas = [(loc[2] - loc[0]) * (loc[1] - loc[3]) for loc in locs]
        best_face_idx = np.argmax(areas)
    enc = encs[best_face_idx]
    matches = face_recognition.compare_faces(data["encodings"], enc, TOLERANCE)
    dist = face_recognition.face_distance(data["encodings"], enc)
    recognized_name = "Unknown"
    if len(dist) > 0:
        best = np.argmin(dist)
        if matches[best]:
            student_id = data["names"][best]
            recognized_name = get_student_name(class_name, student_id)
            threading.Thread(target=record_attendance, args=(class_name, student_id), daemon=True).start()
    elapsed = time.time() - start_time
    print(f"[{class_name}] ✅ {recognized_name} | {elapsed:.3f}s")
    return recognized_name

# ============================================================
# MQTT CALLBACKS
# ============================================================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker")
        client.subscribe("esp32cam/+/image/#")
        print("📡 Subscribed: esp32cam/+/image/#")
    else:
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
        image_buffer[class_name] = {"chunks": {}, "meta": {}, "api_key": None}
    
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
            print(f"[{class_name}] 📥 Meta received: {meta['chunks']} chunks")
        except Exception as e:
            print(f"[{class_name}] ❌ Error parsing meta: {e}")
    
    elif message_type == "chunk":
        if not image_buffer[class_name].get("api_key"):
            print(f"[{class_name}] ❌ Chunk received before meta")
            return
        
        chunk_id = int(parts[4])
        image_buffer[class_name]["chunks"][chunk_id] = payload.decode()
    
    elif message_type == "done":
        if not image_buffer[class_name].get("api_key"):
            print(f"[{class_name}] ❌ Done received but no API key")
            return
        
        print(f"[{class_name}] ⚙️ Processing...")
        try:
            chunks_dict = image_buffer[class_name]["chunks"]
            sorted_chunks = [chunks_dict[i] for i in sorted(chunks_dict.keys())]
            base64_image = "".join(sorted_chunks)
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

def start_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"❌ MQTT error: {e}")
        time.sleep(5)
        start_mqtt()

# ============================================================
# WEB ROUTES
# ============================================================
@app.route("/")
@login_required
def index():
    try:
        data = []
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        if not os.path.exists(BASE_DIR): 
            os.makedirs(BASE_DIR)
        for class_name in os.listdir(BASE_DIR):
            class_dir = os.path.join(BASE_DIR, class_name)
            if not os.path.isdir(class_dir) or class_name == "DS": 
                continue
            db_path = os.path.join(class_dir, "attendance.db")
            if not os.path.exists(db_path): 
                continue
            students = load_student_list(class_name)
            if not students: 
                continue
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT DISTINCT student_id FROM attendance WHERE date=?", (today,))
            present_ids = {r[0] for r in c.fetchall()}
            conn.close()
            absent_ids = [sid for sid in students.keys() if sid not in present_ids]
            absent_names = [students[sid] for sid in absent_ids]
            data.append({
                "class": class_name,
                "present": len(present_ids),
                "absent": len(absent_ids),
                "absent_names": ", ".join(absent_names)
            })
        return render_template('index.html', classes=data, user=current_user)
    except Exception as e:
        print(f"❌ Index error: {e}")
        return render_template('index.html', classes=[], user=current_user)

@app.route("/class/<class_name>/")
@login_required
def class_home(class_name):
    class_dir = ensure_class(class_name)
    students_dict = load_student_list(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT student_id, status FROM attendance WHERE date=?", (today,))
    present_data = cur.fetchall()
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
    class_dir = ensure_class(class_name)
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
        person_dir = os.path.join(class_dir, "known_faces", student_id)
        os.makedirs(person_dir, exist_ok=True)
        for file in files:
            fname = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
            file.save(os.path.join(person_dir, fname))
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
    class_dir = ensure_class(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC")
    rows = cur.fetchall()
    conn.close()
    return render_template('attendance_history.html', class_name=class_name, records=rows, user=current_user)

@app.route("/class/<class_name>/export_excel")
@login_required
def export_excel_class(class_name):
    db_path = os.path.join(BASE_DIR, class_name, "attendance.db")
    excel_path = f"{class_name}_attendance.xlsx"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT student_id, name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC")
    rows = cur.fetchall()
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
    wb.save(excel_path)
    return send_file(excel_path, as_attachment=True)

# ============================================================
# STARTUP
# ============================================================
# Load API keys when app starts
print("📡 Loading API keys...")
load_api_keys()

# Start MQTT in background thread
print("📡 Starting MQTT client...")
mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
mqtt_thread.start()

print("✅ Flask app initialized")