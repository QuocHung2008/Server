import os, hashlib, pickle, json, cv2, numpy as np
from typing import Dict, List
import face_recognition

KNOWN_FACES_DIR = "known_faces"
ENCODINGS_FILE = "encodings.pkl"
META_FILE = "encodings_meta.json"

def compute_known_faces_hash(known_dir: str = KNOWN_FACES_DIR) -> str:
    entries = []
    for root, _, files in os.walk(known_dir):
        for f in sorted(files):
            path = os.path.join(root, f)
            try:
                entries.append(f"{os.path.relpath(path, known_dir)}|{os.path.getmtime(path)}")
            except OSError:
                pass
    return hashlib.sha1("\n".join(entries).encode("utf-8")).hexdigest()

# ✅ Cải tiến: Hàm tiền xử lý ảnh training
def preprocess_training_image(img_path):
    """Cải thiện chất lượng ảnh khi training"""
    img = cv2.imread(img_path)
    if img is None:
        return None
    
    # Cân bằng histogram (tăng độ tương phản)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    
    # Giảm nhiễu
    denoised = cv2.fastNlMeansDenoisingColored(enhanced, None, 10, 10, 7, 21)
    
    # Chuyển sang RGB cho face_recognition
    return cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB)

def build_encodings_for_class(class_dir: str) -> Dict[str, List]:
    known_dir = os.path.join(class_dir, "known_faces")
    encodings_file = os.path.join(class_dir, "encodings.pkl")
    meta_file = os.path.join(class_dir, "encodings_meta.json")

    known_encodings, known_names = [], []
    if os.path.exists(encodings_file):
        with open(encodings_file, "rb") as f:
            data = pickle.load(f)
            known_encodings = data.get("encodings", [])
            known_names = data.get("names", [])

    existing_people = set(known_names)

    names_in_dir = set(os.listdir(known_dir))
    updated_encodings, updated_names = [], []

    # Giữ lại các encoding cũ nếu người đó vẫn còn trong thư mục
    for enc, n in zip(known_encodings, known_names):
        if n in names_in_dir:
            updated_encodings.append(enc)
            updated_names.append(n)

    # Encode các người mới hoặc chưa có encoding
    for name in sorted(names_in_dir):
        if name in updated_names:
            continue
        person_dir = os.path.join(known_dir, name)
        if not os.path.isdir(person_dir):
            continue
        
        person_encodings = []  # Lưu tất cả encoding của 1 người
        
        for imgname in sorted(os.listdir(person_dir)):
            img_path = os.path.join(person_dir, imgname)
            try:
                # ✅ Dùng hàm tiền xử lý mới
                image = preprocess_training_image(img_path)
                if image is None:
                    print(f"[WARN] Không đọc được {img_path}, bỏ qua")
                    continue
                
                # ✅ Tăng num_jitters lên 5 cho training (chính xác hơn)
                encs = face_recognition.face_encodings(
                    image, 
                    num_jitters=5,  # Tăng từ 1 → 5 (chậm hơn nhưng chính xác hơn)
                    model="large"   # Dùng model lớn hơn khi training
                )
                
                if not encs:
                    print(f"[WARN] Không có khuôn mặt trong {img_path}, bỏ qua")
                    continue
                
                # ✅ Kiểm tra chất lượng encoding (loại bỏ ảnh mờ/xấu)
                # Nếu có nhiều khuôn mặt → cảnh báo
                if len(encs) > 1:
                    print(f"[WARN] {img_path} có {len(encs)} khuôn mặt, chỉ lấy khuôn mặt đầu")
                
                person_encodings.append(encs[0])
                print(f"[OK] Encoded {img_path} → {name}")
                
            except Exception as e:
                print(f"[ERR] {img_path}: {e}")
        
        # ✅ Cải tiến: Lưu NHIỀU encoding cho mỗi người (tăng độ chính xác)
        if person_encodings:
            for enc in person_encodings:
                updated_encodings.append(enc)
                updated_names.append(name)
            print(f"[INFO] {name}: Đã lưu {len(person_encodings)} ảnh")
        else:
            print(f"[WARN] {name}: Không có ảnh hợp lệ nào!")

    known_encodings, known_names = updated_encodings, updated_names

    # Lưu file
    with open(encodings_file, "wb") as f:
        pickle.dump({"encodings": known_encodings, "names": known_names}, f)
    with open(meta_file, "w") as f:
        json.dump({
            "hash": compute_known_faces_hash(known_dir),
            "count": len(known_names),
            "unique_people": len(set(known_names))
        }, f)

    print(f"[{os.path.basename(class_dir)}] ✅ Cập nhật xong ({len(set(known_names))} người, {len(known_names)} ảnh).")
    return {"encodings": known_encodings, "names": known_names}