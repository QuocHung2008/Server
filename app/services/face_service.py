import asyncio
import io
import pickle
import numpy as np
import face_recognition
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

from app.database import get_db

# known_encodings: dict[class_name, list[tuple[encoding, student_id, name, student_code]]]
known_encodings = {}

executor = ThreadPoolExecutor(max_workers=4)

async def load_all_encodings():
    global known_encodings
    known_encodings.clear()
    
    print("Loading all encodings from database...")
    from app.database import pool
    if pool is None:
        print("Error: DB Pool not initialized!")
        return
        
    async with pool.acquire() as conn:
        records = await conn.fetch('''
            SELECT s.id as student_id, s.full_name, s.student_code, s.face_encoding, c.name as class_name 
            FROM students s
            JOIN classes c ON s.class_id = c.id
            WHERE s.face_encoding IS NOT NULL
        ''')
        
        for record in records:
            class_name = record['class_name']
            if class_name not in known_encodings:
                known_encodings[class_name] = []
                
            try:
                encoding = pickle.loads(record['face_encoding'])
                known_encodings[class_name].append((
                    encoding, 
                    str(record['student_id']), 
                    record['full_name'],
                    record['student_code']
                ))
            except Exception as e:
                print(f"Failed to load encoding for {record['student_code']}: {e}")
                
    count = sum(len(encs) for encs in known_encodings.values())
    print(f"Loaded {count} encodings across {len(known_encodings)} classes.")

def encode_face_sync(image_bytes: bytes) -> np.ndarray:
    try:
        # Using PIL to load bytes
        image = face_recognition.load_image_file(io.BytesIO(image_bytes))
        encodings = face_recognition.face_encodings(image)
        if len(encodings) > 0:
            return encodings[0]
        return None
    except Exception as e:
        print(f"Error encoding face: {e}")
        return None

async def encode_face(image_bytes: bytes) -> np.ndarray:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, encode_face_sync, image_bytes)

def match_face_sync(unknown_encoding: np.ndarray, class_name=None, tolerance=0.5):
    # Find match in known encodings
    best_match = None
    best_distance = 1.0
    
    classes_to_check = [class_name] if class_name and class_name in known_encodings else known_encodings.keys()
    
    for c_name in classes_to_check:
        class_students = known_encodings.get(c_name, [])
        if not class_students:
            continue
            
        encs = [item[0] for item in class_students]
        distances = face_recognition.face_distance(encs, unknown_encoding)
        
        for i, distance in enumerate(distances):
            if distance <= tolerance and distance < best_distance:
                best_distance = distance
                best_match = {
                    "student_id": class_students[i][1],
                    "name": class_students[i][2],
                    "student_code": class_students[i][3],
                    "class_name": c_name,
                    "confidence": 1 - distance
                }
                
    return best_match

async def match_face(unknown_encoding: np.ndarray, class_name=None, tolerance=0.5):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, match_face_sync, unknown_encoding, class_name, tolerance)
