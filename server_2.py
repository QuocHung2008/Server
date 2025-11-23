from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from encode_known_faces import build_encodings_for_class
from openpyxl import Workbook
import os, sqlite3, pickle, cv2, numpy as np, face_recognition
import datetime, threading, time

BASE_DIR = "classes"
# ✅ Cải tiến 1: Tăng tolerance lên 0.45 (cân bằng giữa chính xác & nhận diện được)
# ✅ Cải tiến 2: Dùng "cnn" model cho độ chính xác cao hơn (nếu có GPU)
TOLERANCE = 0.45
DETECTION_MODEL = "cnn"  # Đổi "hog" → "cnn" (chính xác hơn nhưng chậm hơn)

# ✅ Nếu máy yếu, giữ "hog" nhưng tăng số lần upsample
UPSAMPLE_TIMES = 1  # Tăng lên 2 nếu muốn phát hiện khuôn mặt xa hơn

app = Flask(__name__)
LOCKS = {}
ENCODINGS_CACHE = {} 

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
    db_path = os.path.join(class_dir, "attendance.db")
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS attendance(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, date TEXT,
                    first_time TEXT, status TEXT, timestamp_iso TEXT)""")
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

def record_attendance(class_name, name):
    db_path = os.path.join(BASE_DIR, class_name, "attendance.db")
    with LOCKS[class_name]:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        iso = now.isoformat(sep=" ", timespec="seconds")
        status = get_status_by_time(now)
        exists = c.execute("SELECT 1 FROM attendance WHERE name=? AND date=?", (name, today)).fetchone()
        if not exists:
            c.execute("INSERT INTO attendance(name, date, first_time, status, timestamp_iso) VALUES(?,?,?,?,?)", 
                      (name, today, time_str, status, iso))
            conn.commit()
        conn.close()

# ✅ Cải tiến 3: Hàm tiền xử lý ảnh để tăng chất lượng
def preprocess_image(img_bgr):
    """Cải thiện chất lượng ảnh trước khi nhận diện"""
    # Tăng độ sáng nếu ảnh quá tối
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    
    # Giảm nhiễu
    denoised = cv2.fastNlMeansDenoisingColored(enhanced, None, 10, 10, 7, 21)
    
    return denoised
        
@app.route("/")
def index():
    data = []
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(BASE_DIR): os.makedirs(BASE_DIR)
    for class_name in os.listdir(BASE_DIR):
        class_dir = os.path.join(BASE_DIR, class_name)
        if not os.path.isdir(class_dir): continue
        
        db_path = os.path.join(class_dir, "attendance.db")
        enc_path = os.path.join(class_dir, "encodings.pkl")
        if not os.path.exists(db_path): continue
        if not os.path.exists(enc_path): build_encodings_for_class(class_dir)
        
        with open(enc_path, "rb") as f: enc_data = pickle.load(f)
        all_people = sort_by_vietnamese_name(list(set(enc_data.get("names", []))))
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT name FROM attendance WHERE date=?", (today,))
        present = {r[0] for r in c.fetchall()}
        conn.close()
        absent = [n for n in all_people if n not in present]
        data.append({
            "class": class_name, "present": len(present),
            "absent": len(absent), "absent_names": ", ".join(absent)
        })
    return render_template("index.html", classes=data)

@app.route("/class/<class_name>/")
def class_home(class_name):
    class_dir = ensure_class(class_name)
    data = get_encodings_data(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT name, status FROM attendance WHERE date=?", (today,))
    present_data = cur.fetchall()
    conn.close()
    present = {r[0]: r[1] for r in present_data}
    all_people = sort_by_vietnamese_name(list(set(data["names"])))
    students = []
    for name in all_people:
        status = present.get(name, "Vắng")
        students.append({"name": name, "status": status})
    return render_template("attendance.html", class_name=class_name, students=students)

@app.route("/class/<class_name>/add_student", methods=["GET", "POST"])
def add_student(class_name):
    class_dir = ensure_class(class_name)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        files = request.files.getlist("images")
        if not name or not files: return "Thiếu tên hoặc ảnh!", 400
        person_dir = os.path.join(class_dir, "known_faces", name)
        os.makedirs(person_dir, exist_ok=True)
        for file in files:
            fname = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
            file.save(os.path.join(person_dir, fname))
        build_encodings_for_class(class_dir)
        reload_cache(class_name)
        return redirect(url_for("class_home", class_name=class_name))
    return render_template("add_student.html", class_name=class_name)

# ✅ CẢI TIẾN 4: Thuật toán nhận diện mới (chính xác hơn nhiều)
@app.route("/class/<class_name>/recognize", methods=["POST"])
def recognize(class_name):
    start_time = time.time()
    
    class_dir = ensure_class(class_name) 
    data = get_encodings_data(class_name)
    
    if 'image' not in request.files:
        return jsonify({"name": "Unknown", "error": "No image"}), 400

    img_bytes = request.files['image'].read()
    
    # Lưu ảnh để debug
    last_img_path = os.path.join(class_dir, "last_upload.jpg")
    try:
        with open(last_img_path, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        print(f"Lỗi khi lưu ảnh: {e}")

    # Giải mã ảnh
    img_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        return jsonify({"name": "Unknown", "error": "Invalid image"}), 400
    
    # ✅ Áp dụng tiền xử lý ảnh
    img_bgr = preprocess_image(img_bgr)
    
    # Chuyển sang RGB
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    # ✅ Tìm khuôn mặt với tham số tối ưu
    locs = face_recognition.face_locations(
        img_rgb, 
        number_of_times_to_upsample=UPSAMPLE_TIMES,
        model=DETECTION_MODEL
    )
    
    if len(locs) == 0:
        print(f"[{class_name}] Không phát hiện khuôn mặt | {time.time() - start_time:.3f}s")
        return jsonify({"name": "Unknown", "error": "No face detected"})
    
    # ✅ Encode với model chính xác hơn
    encs = face_recognition.face_encodings(img_rgb, locs, num_jitters=2)
    
    # Chọn khuôn mặt LỚN NHẤT (gần camera nhất)
    best_face_idx = 0
    if len(locs) > 1:
        areas = [(loc[2] - loc[0]) * (loc[1] - loc[3]) for loc in locs]
        best_face_idx = np.argmax(areas)
    
    enc = encs[best_face_idx]
    
    # ✅ Cải tiến 5: So sánh thông minh hơn với voting
    matches = face_recognition.compare_faces(data["encodings"], enc, TOLERANCE)
    dist = face_recognition.face_distance(data["encodings"], enc)
    
    recognized_name = "Unknown"
    
    if True in matches:
        # Lấy tất cả các match
        matched_indices = [i for i, match in enumerate(matches) if match]
        matched_names = [data["names"][i] for i in matched_indices]
        matched_dists = [dist[i] for i in matched_indices]
        
        # ✅ Voting: Chọn tên xuất hiện nhiều nhất
        from collections import Counter
        name_counts = Counter(matched_names)
        
        # Nếu có tên xuất hiện nhiều lần → chọn tên đó
        if name_counts:
            best_name = name_counts.most_common(1)[0][0]
            
            # Lấy distance nhỏ nhất của tên đó
            best_name_indices = [i for i, n in enumerate(matched_names) if n == best_name]
            best_dist = min(matched_dists[i] for i in best_name_indices)
            
            # ✅ Chỉ chấp nhận nếu distance < ngưỡng an toàn
            if best_dist < TOLERANCE * 0.9:  # 90% của tolerance để chắc chắn hơn
                recognized_name = best_name
                record_attendance(class_name, recognized_name)
                print(f"[{class_name}] ✅ {recognized_name} (dist: {best_dist:.3f}) | {time.time() - start_time:.3f}s")
            else:
                print(f"[{class_name}] ⚠️ Không chắc chắn (dist: {best_dist:.3f})")
    
    if recognized_name == "Unknown":
        print(f"[{class_name}] ❌ Không nhận diện được | {time.time() - start_time:.3f}s")
    
    return jsonify({"name": recognized_name})

@app.route("/class/<class_name>/history")
def attendance_history(class_name):
    class_dir = ensure_class(class_name)
    db_path = os.path.join(class_dir, "attendance.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
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
    cur.execute("SELECT name, date, first_time, status FROM attendance ORDER BY date DESC, first_time DESC")
    rows = cur.fetchall()
    conn.close()
    wb = Workbook()
    ws = wb.active
    ws.title = "Điểm danh"
    ws.append(["Tên học sinh", "Ngày", "Giờ điểm danh", "Trạng thái"])
    for row in rows: ws.append(row)
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
    app.run(host="192.168.1.173", port=5000, debug=False, threaded=True)