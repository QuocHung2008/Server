import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

import os, hashlib, json, cv2, numpy as np
from typing import Dict, List
import face_recognition
import sys

KNOWN_FACES_DIR = "known_faces"
ENCODINGS_FILE = "encodings.npz"
META_FILE = "encodings_meta.json"

# ✅ GLOBAL FLAG để tránh recursive call
_ENCODING_IN_PROGRESS = set()

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

def get_largest_face_location(face_locations):
    """Trả về location của khuôn mặt lớn nhất"""
    if not face_locations:
        return None
    
    if len(face_locations) == 1:
        return face_locations[0]
    
    areas = [(loc[2] - loc[0]) * (loc[1] - loc[3]) for loc in face_locations]
    largest_idx = np.argmax(areas)
    
    if len(face_locations) > 1:
        print(f"    🎯 Tìm thấy {len(face_locations)} mặt, chọn mặt lớn nhất (diện tích: {areas[largest_idx]} px)")
    
    return face_locations[largest_idx]

def build_encodings_for_class(class_dir: str) -> Dict[str, List]:
    """Build encodings với protection chống lặp vô hạn"""
    
    # ✅ PROTECTION 1: Kiểm tra đang encode hay chưa
    abs_class_dir = os.path.abspath(class_dir)
    if abs_class_dir in _ENCODING_IN_PROGRESS:
        print(f"⚠️ CẢNH BÁO: {class_dir} đang được encode, bỏ qua để tránh lặp!")
        return {"encodings": [], "names": []}
    
    _ENCODING_IN_PROGRESS.add(abs_class_dir)
    
    try:
        return _build_encodings_internal(class_dir, force_rebuild=False)
    finally:
        # ✅ PROTECTION 2: Luôn remove khỏi set khi xong
        _ENCODING_IN_PROGRESS.discard(abs_class_dir)

def build_encodings_for_class_force(class_dir: str) -> Dict[str, List]:
    abs_class_dir = os.path.abspath(class_dir)
    if abs_class_dir in _ENCODING_IN_PROGRESS:
        print(f"⚠️ CẢNH BÁO: {class_dir} đang được encode, bỏ qua để tránh lặp!")
        return {"encodings": [], "names": []}
    _ENCODING_IN_PROGRESS.add(abs_class_dir)
    try:
        return _build_encodings_internal(class_dir, force_rebuild=True)
    finally:
        _ENCODING_IN_PROGRESS.discard(abs_class_dir)

def _build_encodings_internal(class_dir: str, force_rebuild: bool) -> Dict[str, List]:
    """Hàm encode thực sự (internal)"""
    
    known_dir = os.path.join(class_dir, "known_faces")
    encodings_file = os.path.join(class_dir, "encodings.npz")
    legacy_encodings_file = os.path.join(class_dir, "encodings.pkl")
    meta_file = os.path.join(class_dir, "encodings_meta.json")

    print(f"\n{'='*70}")
    print(f"🔧 BẮT ĐẦU ENCODE: {os.path.basename(class_dir)}")
    print(f"{'='*70}")

    if not os.path.exists(known_dir):
        print(f"❌ Không tìm thấy thư mục: {known_dir}")
        return {"encodings": [], "names": []}

    current_hash = compute_known_faces_hash(known_dir)
    stored_hash = None
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                stored_hash = (json.load(f) or {}).get("hash")
        except Exception:
            stored_hash = None

    if not force_rebuild and stored_hash and stored_hash == current_hash and os.path.exists(encodings_file):
        try:
            loaded = np.load(encodings_file, allow_pickle=False)
            encs = [e for e in loaded["encodings"]]
            names = [str(n) for n in loaded["names"]]
            print(f"📦 Encoding đã up-to-date: {len(set(names))} người, {len(names)} ảnh")
            return {"encodings": encs, "names": names}
        except Exception:
            pass

    if force_rebuild:
        print("♻️ Force rebuild encodings (bỏ qua cache cũ)")
    else:
        print("♻️ Detected changes in known_faces, rebuild encodings")

    if not os.path.exists(known_dir):
        print(f"❌ Không tìm thấy thư mục: {known_dir}")
        return {"encodings": [], "names": []}
    
    people = sorted([d for d in os.listdir(known_dir) if os.path.isdir(os.path.join(known_dir, d))])

    updated_encodings, updated_names = [], []
    
    # Encode từng người
    for idx, name in enumerate(people, 1):
        person_dir = os.path.join(known_dir, name)
        
        print(f"\n[{idx}/{len(people)}] 👤 {name}")
        
        # Lọc file ảnh hợp lệ
        image_files = sorted([f for f in os.listdir(person_dir) 
                            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))])
        
        if not image_files:
            print(f"   ⚠️ Không có file ảnh!")
            processed_names.add(name)  # ✅ Vẫn đánh dấu
            continue
        
        print(f"   📷 Tìm thấy {len(image_files)} file ảnh")
        
        person_encodings = []
        
        for img_idx, imgname in enumerate(image_files, 1):
            img_path = os.path.join(person_dir, imgname)
            
            try:
                # Đọc ảnh đơn giản
                image = face_recognition.load_image_file(img_path)
                
                # Resize nếu quá lớn
                h, w = image.shape[:2]
                if w > 1600:
                    scale = 1600 / w
                    image = cv2.resize(image, (1600, int(h * scale)))
                    print(f"   [{img_idx}/{len(image_files)}] 📐 {imgname} (resized)")
                else:
                    print(f"   [{img_idx}/{len(image_files)}] 🔍 {imgname}")
                
                # Tìm mặt với HOG (nhanh, ổn định)
                face_locations = face_recognition.face_locations(image, model="hog")
                
                if not face_locations:
                    print(f"      ⚠️ Không có mặt")
                    continue
                
                # Lấy mặt lớn nhất
                largest_face = get_largest_face_location(face_locations)
                
                # Encode với cài đặt nhẹ
                encs = face_recognition.face_encodings(
                    image, 
                    known_face_locations=[largest_face],
                    num_jitters=2  # Giảm xuống 2 cho nhanh
                )
                
                if not encs:
                    print(f"      ⚠️ Không encode được")
                    continue
                
                person_encodings.append(encs[0])
                print(f"      ✅ OK")
                
            except Exception as e:
                print(f"      ❌ Lỗi: {str(e)[:50]}")
        
        # Lưu kết quả
        if person_encodings:
            for enc in person_encodings:
                updated_encodings.append(enc)
                updated_names.append(name)
            print(f"   ✅ Thành công: {len(person_encodings)}/{len(image_files)} ảnh")
        else:
            print(f"   ⚠️ Không có ảnh nào hợp lệ!")
        
    # Lưu file
    print(f"\n💾 Đang lưu vào {encodings_file}...")

    enc_arr = np.asarray(updated_encodings, dtype=np.float64)
    name_arr = np.asarray(updated_names, dtype=str)
    np.savez_compressed(encodings_file, encodings=enc_arr, names=name_arr)
    
    unique_people = len(set(updated_names))
    total_images = len(updated_names)
    
    with open(meta_file, "w") as f:
        json.dump({
            "hash": current_hash,
            "count": total_images,
            "unique_people": unique_people
        }, f)

    print(f"\n{'='*70}")
    print(f"✅ HOÀN TẤT: {os.path.basename(class_dir)}")
    print(f"{'='*70}")
    print(f"👥 Tổng số người: {unique_people}")
    print(f"📷 Tổng số ảnh: {total_images}")
    if unique_people > 0:
        print(f"📊 Trung bình: {total_images / unique_people:.1f} ảnh/người")
    print(f"{'='*70}\n")
    
    return {"encodings": updated_encodings, "names": updated_names}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python encode_known_faces_fixed.py <class_dir>")
        print("Example: python encode_known_faces_fixed.py classes/Lop10A")
        print("\nHoặc encode tất cả lớp:")
        print("python encode_known_faces_fixed.py classes")
        sys.exit(1)
    
    path = sys.argv[1]
    
    # Nếu truyền vào thư mục "classes" → encode tất cả lớp
    if os.path.isdir(path) and os.path.basename(path) == "classes":
        print(f"🔄 Sẽ encode tất cả lớp trong: {path}\n")
        
        class_dirs = []
        for name in sorted(os.listdir(path)):
            class_dir = os.path.join(path, name)
            if os.path.isdir(class_dir):
                known_faces = os.path.join(class_dir, "known_faces")
                if os.path.exists(known_faces):
                    class_dirs.append(class_dir)
        
        if not class_dirs:
            print("❌ Không tìm thấy lớp nào có thư mục known_faces!")
            sys.exit(1)
        
        print(f"Tìm thấy {len(class_dirs)} lớp\n")
        
        for i, class_dir in enumerate(class_dirs, 1):
            print(f"\n{'#'*70}")
            print(f"# [{i}/{len(class_dirs)}] {os.path.basename(class_dir)}")
            print(f"{'#'*70}")
            build_encodings_for_class(class_dir)
    
    # Encode 1 lớp cụ thể
    else:
        build_encodings_for_class(path)
