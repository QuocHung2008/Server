from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from encode_known_faces import build_encodings_for_class
from typing import Dict
from openpyxl import load_workbook, Workbook
import os, sqlite3, pickle, cv2, numpy as np, face_recognition
import datetime, threading, time

DS_DIR = "classes/DS"
BASE_DIR = "classes"
TOLERANCE, DETECTION_MODEL = 0.4, "hog"

app = Flask(__name__)
LOCKS = {}
ENCODINGS_CACHE = {} 

def load_student_list(class_name: str) -> Dict[str, str]:
    """
    Load danh sách học sinh từ file Excel
    Returns: {student_id: student_name}
    """
    file_path = os.path.join(DS_DIR, f"DS_{class_name}.xlsx")
    
    if not os.path.exists(file_path):
        return {}
    
    try:
        wb = load_workbook(file_path, read_only=True)
        ws = wb.active
        
        students = {}
        # Đọc từ dòng 2 (bỏ qua header)
        for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
            student_id = row[0]  # Cột A
            student_name = row[1]  # Cột B
            
            if student_id and student_name:
                students[str(student_id).strip()] = str(student_name).strip()
        
        wb.close()
        return students
        
    except Exception as e:
        print(f"❌ Lỗi đọc file {file_path}: {e}")
        return {}

def get_student_name(class_name: str, student_id: str) -> str:
    """Lấy tên học sinh từ mã học sinh"""
    students = load_student_list(class_name)
    return students.get(str(student_id), "Unknown")

def sort_by_vietnamese_name(names):
    def name_key(fullname):
        parts = fullname.strip().split()
        return parts[::-1]
    return sorted(names, key=name_key)

def get_status_by_time(now):
    morning_limit = now.replace(hour=6, minute=45, second=0, microsecond=0)
    afternoon_limit = now.replace(hour=13, minute=15, second=0, microsecond=0)
    if now.hour < 12:
        return "Trễ" if now > morning_limit else "Có mặt"
    return "Trễ" if now > afternoon_limit else "Có mặt"

def ensure_class(class_name):
    class_dir = os.path.join(BASE_DIR, class_name)
    os.makedirs(os.path.join(class_dir, "known_faces"), exist_ok=True)
    
    # Database với cột student_id
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
    """Ghi nhận điểm danh theo mã học sinh"""
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
        
@app.route("/")
def index():
    data = []
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(BASE_DIR): os.makedirs(BASE_DIR)
    
    for class_name in os.listdir(BASE_DIR):
        class_dir = os.path.join(BASE_DIR, class_name)
        if not os.path.isdir(class_dir) or class_name == "DS": continue
        
        db_path = os.path.join(class_dir, "attendance.db")
        if not os.path.exists(db_path): continue
        
        # Load từ file DS
        students = load_student_list(class_name)
        if not students: continue
        
        all_student_names = sort_by_vietnamese_name(list(students.values()))
        
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
    
    return render_template("index.html", classes=data)

@app.route("/class/<class_name>/")
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
    
    return render_template("attendance.html", class_name=class_name, students=students)

@app.route("/class/<class_name>/add_student", methods=["GET", "POST"])
def add_student(class_name):
    class_dir = ensure_class(class_name)
    
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        files = request.files.getlist("images")
        
        if not student_id or not files:
            return "Thiếu mã học sinh hoặc ảnh!", 400
        
        students = load_student_list(class_name)
        if student_id not in students:
            return f"Mã học sinh {student_id} không có trong danh sách!", 400
        
        # Lưu với tên thư mục = mã HS
        person_dir = os.path.join(class_dir, "known_faces", student_id)
        os.makedirs(person_dir, exist_ok=True)
        
        for file in files:
            fname = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
            file.save(os.path.join(person_dir, fname))
        
        build_encodings_for_class(class_dir)
        reload_cache(class_name)
        
        return redirect(url_for("class_home", class_name=class_name))
    
    # GET
    students = load_student_list(class_name)
    student_list = [{"id": sid, "name": name} for sid, name in sorted(students.items())]
    
    return render_template("add_student.html", class_name=class_name, students=student_list)

@app.route("/class/<class_name>/recognize", methods=["POST"])
def recognize(class_name):
    start_time = time.time()
    
    class_dir = ensure_class(class_name)
    data = get_encodings_data(class_name)
    
    if 'image' not in request.files:
        return jsonify({"name": "Unknown", "error": "No image"}), 400

    img_bytes = request.files['image'].read()
    
    last_img_path = os.path.join(class_dir, "last_upload.jpg")
    try:
        with open(last_img_path, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        print(f"Lỗi khi lưu ảnh: {e}")

    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        return jsonify({"name": "Unknown", "error": "Invalid image"}), 400
    
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    locs = face_recognition.face_locations(img_rgb, model=DETECTION_MODEL)
    
    if len(locs) == 0:
        print(f"[{class_name}] Không phát hiện khuôn mặt | {time.time() - start_time:.3f}s")
        return jsonify({"name": "Unknown", "error": "No face detected"})
    
    encs = face_recognition.face_encodings(img_rgb, locs)
    
    # Chọn mặt lớn nhất
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
            student_id = data["names"][best]  # names chứa student_id
            recognized_name = get_student_name(class_name, student_id)  # Trả về TÊN
            record_attendance(class_name, student_id)
    
    print(f"[{class_name}] Nhận diện: {recognized_name} | {time.time() - start_time:.3f}s")
    
    return jsonify({"name": recognized_name})

@app.route("/class/<class_name>/history")
def attendance_history(class_name):
    class_dir = ensure_class(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Chỉ lấy name, date, first_time, status (không lấy student_id)
    cur.execute("SELECT name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC")
    rows = cur.fetchall()
    conn.close()
    return render_template("attendance_history.html", class_name=class_name, records=rows)

@app.route("/class/<class_name>/export_excel")
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

def reset_attendance_daily():
    """Tự động xóa điểm danh lúc 13h và 18h mỗi ngày"""
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
        print(f"[Scheduler] Reset điểm danh lúc {next_reset.strftime('%d/%m/%Y %H:%M:%S')} (sau {sleep_time / 3600:.2f} giờ)")
        time.sleep(sleep_time)
        
        print("[Reset] Bắt đầu xóa điểm danh...")
        if not os.path.exists(BASE_DIR): continue
        
        for class_name in os.listdir(BASE_DIR):
            if class_name == "DS": continue
            db_path = os.path.join(BASE_DIR, class_name, "attendance.db")
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    conn.execute("DELETE FROM attendance")
                    conn.commit()
                    conn.close()
                    print(f" ✓ Đã xóa lớp {class_name}")
                except Exception as e: 
                    print(f" ✗ Lỗi lớp {class_name}: {e}")
        print("[Reset] Hoàn tất.")

if __name__ == "__main__":
    threading.Thread(target=reset_attendance_daily, daemon=True).start()
    app.run(host="172.20.10.14", port=5000, debug=False, threaded=True)