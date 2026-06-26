import socketio

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

async def broadcast_attendance(data: dict):
    # Payload format:
    # {
    #   "event": "attendance_update",
    #   "data": { ... }
    # }
    await sio.emit('attendance_update', data)
