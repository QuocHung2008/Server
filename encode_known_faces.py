# import warnings
# warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

import os, hashlib, pickle, json
from typing import Dict, List
import face_recognition

KNOWN_FACES_DIR = "known_faces"
ENCODINGS_FILE = "encodings.pkl"
META_FILE = "encodisngs_meta.json"

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

    for enc, n in zip(known_encodings, known_names):
        if n in names_in_dir:
            updated_encodings.append(enc)
            updated_names.append(n)

    for name in sorted(names_in_dir):
        if name in updated_names:
            continue
        person_dir = os.path.join(known_dir, name)
        if not os.path.isdir(person_dir):
            continue
        for imgname in sorted(os.listdir(person_dir)):
            img_path = os.path.join(person_dir, imgname)
            try:
                image = face_recognition.load_image_file(img_path)
                encs = face_recognition.face_encodings(image)
                if not encs:
                    print(f"[WARN] No face in {img_path}, skipping")
                    continue
                updated_encodings.append(encs[0])
                updated_names.append(name)
                print(f"[OK] Encoded {img_path} -> {name}")
            except Exception as e:
                print(f"[ERR] {img_path}: {e}")

    known_encodings, known_names = updated_encodings, updated_names


    with open(encodings_file, "wb") as f:
        pickle.dump({"encodings": known_encodings, "names": known_names}, f)
    with open(meta_file, "w") as f:
        json.dump({
            "hash": compute_known_faces_hash(known_dir),
            "count": len(known_names)
        }, f)

    print(f"[{os.path.basename(class_dir)}] Cập nhật xong ({len(known_names)} khuôn mặt).")
    return {"encodings": known_encodings, "names": known_names}
