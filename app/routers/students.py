from fastapi import APIRouter, File, UploadFile, Form, HTTPException
import os
import aiofiles
import pickle
from uuid import UUID
from app.database import pool
from app.config import settings
from app.services.face_service import encode_face, known_encodings

router = APIRouter(prefix="/api/students", tags=["students"])

@router.get("/")
async def get_students():
    if pool is None: return []
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT s.id, s.student_code, s.full_name, c.name as class_name, s.image_path 
            FROM students s 
            LEFT JOIN classes c ON s.class_id = c.id
        """)
        return [dict(r) for r in records]

@router.post("/")
async def create_student(
    student_code: str = Form(...),
    full_name: str = Form(...),
    class_id: UUID = Form(...),
    file: UploadFile = File(...)
):
    if pool is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
        
    # save file
    file_path = os.path.join(settings.UPLOAD_DIR, "faces", file.filename)
    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)
        
    # encode face
    encoding = await encode_face(content)
    if encoding is None:
        raise HTTPException(status_code=400, detail="No face found in the image")
        
    encoding_bytes = pickle.dumps(encoding)
    
    async with pool.acquire() as conn:
        try:
            student_id = await conn.fetchval('''
                INSERT INTO students (student_code, full_name, class_id, image_path, face_encoding)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            ''', student_code, full_name, class_id, file_path, encoding_bytes)
            
            # Update memory dict
            class_record = await conn.fetchrow('SELECT name FROM classes WHERE id = $1', class_id)
            if class_record:
                class_name = class_record['name']
                if class_name not in known_encodings:
                    known_encodings[class_name] = []
                known_encodings[class_name].append((encoding, str(student_id), full_name, student_code))
                
            return {"status": "success", "id": student_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
