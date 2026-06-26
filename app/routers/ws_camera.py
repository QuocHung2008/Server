from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import asyncio
from datetime import datetime, timezone
import json

from app.services.auth_service import is_valid_api_key
from app.services.face_service import face_service
from app.services.socketio_service import broadcast_attendance
from app.database import pool

router = APIRouter()


@router.websocket("/ws/camera")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str = Query(...),
    device_id: str = Query(...)
):
    """
    WebSocket endpoint for ESP32-CAM binary JPEG streaming and face recognition.
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 18.1
    
    Query Parameters:
        api_key: API key for authentication
        device_id: Device identifier for logging and tracking
    
    Protocol:
        - Receives: Binary JPEG frames
        - Sends: JSON responses with recognition results
    
    Error Handling:
        - Invalid API key → Close with code 1008
        - No face detected → Send "no_face" response
        - Face recognition error → Log error and send "no_face" response
    """
    # Validate API Key (Requirement 1.5)
    if not is_valid_api_key(api_key):
        print(f"Invalid API key attempt from device: {device_id}")
        await websocket.close(code=1008, reason="Invalid API Key")
        return
        
    await websocket.accept()
    print(f"Device connected: {device_id}")

    try:
        while True:
            # Receive binary frame from ESP32 (Requirement 1.2)
            data = await websocket.receive_bytes()
            
            timestamp = datetime.now(timezone.utc).isoformat()
            
            try:
                # Encode face from JPEG (Requirement 1.2)
                unknown_encoding = await face_service.encode_face(data)
                
                if unknown_encoding is None:
                    # No face detected (Requirement 18.1)
                    print(f"No face detected from device: {device_id}")
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
                    
                # Match face (Requirement 1.2)
                match_result = await face_service.match_face(unknown_encoding)
                
                if match_result.matched:
                    # Send recognized response immediately (Requirement 1.3)
                    await websocket.send_json({
                        "status": "recognized",
                        "name": match_result.student_name,
                        "student_id": match_result.student_id,  # UUID string
                        "class_name": match_result.class_name,
                        "confidence": match_result.confidence,
                        "timestamp": timestamp,
                        "device_id": device_id
                    })
                    
                    # Asynchronously save to DB and broadcast (Requirement 1.4)
                    asyncio.create_task(
                        save_and_broadcast(
                            student_id=match_result.student_id,
                            class_name=match_result.class_name,
                            student_code=match_result.student_code,
                            student_name=match_result.student_name,
                            device_id=device_id,
                            confidence=match_result.confidence,
                            status="present"
                        )
                    )
                else:
                    # Send unknown response (Requirement 1.3)
                    await websocket.send_json({
                        "status": "unknown",
                        "name": None,
                        "student_id": None,
                        "class_name": None,
                        "confidence": None,
                        "timestamp": timestamp,
                        "device_id": device_id
                    })
                    
            except Exception as e:
                # Face recognition error → send no_face response (Requirement 18.1)
                print(f"Face recognition error from device {device_id}: {e}")
                await websocket.send_json({
                    "status": "no_face",
                    "name": None,
                    "student_id": None,
                    "class_name": None,
                    "confidence": None,
                    "timestamp": timestamp,
                    "device_id": device_id
                })

    except WebSocketDisconnect:
        # Log disconnection (Requirement 18.3)
        print(f"Device disconnected: {device_id}")
    except Exception as e:
        # Log unexpected errors (Requirement 18.1)
        print(f"WebSocket error from device {device_id}: {e}")
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
