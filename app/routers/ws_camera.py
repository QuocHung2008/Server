from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import asyncio
from datetime import datetime, timezone
import json

from app.services.auth_service import is_valid_api_key
from app.services.face_service import encode_face, match_face
from app.services.socketio_service import broadcast_attendance
from app.database import pool

router = APIRouter()

@router.websocket("/ws/camera")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str = Query(...),
    device_id: str = Query(...)
):
    # Validate API Key
    if not is_valid_api_key(api_key):
        await websocket.close(code=1008, reason="Invalid API Key")
        return
        
    await websocket.accept()
    print(f"Device connected: {device_id}")

    try:
        while True:
            # Receive binary frame from ESP32
            data = await websocket.receive_bytes()
            
            # Encode face from JPEG
            unknown_encoding = await encode_face(data)
            
            timestamp = datetime.now(timezone.utc).isoformat()
            
            if unknown_encoding is None:
                # No face detected or decoding failed
                await websocket.send_json({
                    "status": "no_face",
                    "name": None,
                    "student_id": None,
                    "class_name": None,
                    "confidence": None,
                    "timestamp": timestamp,
                    "device_id": device_id
                })
                continue
                
            # Match face
            match_result = await match_face(unknown_encoding)
            
            if match_result:
                status = "recognized"
                # Send immediately to ESP32
                await websocket.send_json({
                    "status": status,
                    "name": match_result["name"],
                    "student_id": match_result["student_code"],
                    "class_name": match_result["class_name"],
                    "confidence": match_result["confidence"],
                    "timestamp": timestamp,
                    "device_id": device_id
                })
                
                # Asynchronously save to DB and broadcast
                asyncio.create_task(
                    save_and_broadcast(
                        student_id=match_result["student_id"],
                        class_name=match_result["class_name"],
                        student_code=match_result["student_code"],
                        student_name=match_result["name"],
                        device_id=device_id,
                        confidence=match_result["confidence"],
                        status="present"
                    )
                )
            else:
                status = "unknown"
                await websocket.send_json({
                    "status": status,
                    "name": None,
                    "student_id": None,
                    "class_name": None,
                    "confidence": None,
                    "timestamp": timestamp,
                    "device_id": device_id
                })

    except WebSocketDisconnect:
        print(f"Device disconnected: {device_id}")
    except Exception as e:
        print(f"WebSocket error: {e}")
        if not websocket.client_state.name == "DISCONNECTED":
            await websocket.close()

async def save_and_broadcast(student_id, class_name, student_code, student_name, device_id, confidence, status):
    if pool is None:
        return
        
    async with pool.acquire() as conn:
        try:
            # Get class_id
            class_record = await conn.fetchrow('SELECT id FROM classes WHERE name = $1', class_name)
            if not class_record:
                return
            class_id = class_record['id']
            
            record_id = await conn.fetchval('''
                INSERT INTO attendance_records (student_id, class_id, device_id, confidence, status)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            ''', student_id, class_id, device_id, confidence, status)
            
            # Broadcast
            payload = {
                "event": "attendance_update",
                "data": {
                    "id": str(record_id),
                    "student_name": student_name,
                    "student_code": student_code,
                    "class_name": class_name,
                    "device_id": device_id,
                    "confidence": confidence,
                    "status": status,
                    "recorded_at": datetime.now(timezone.utc).isoformat()
                }
            }
            await broadcast_attendance(payload)
            
        except Exception as e:
            print(f"DB Error while saving attendance: {e}")
