import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
import socketio

from app.config import settings
from app.services.socketio_service import sio
# from app.database import init_db_pool, close_db_pool
# from app.services.face_service import load_all_encodings
# from app.services.auth_service import load_api_keys

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up...")
    # await init_db_pool()
    # await load_all_encodings()
    # await load_api_keys()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    yield
    # Shutdown
    print("Shutting down...")
    # await close_db_pool()

app = FastAPI(lifespan=lifespan)

# CORS
origins = settings.CORS_ORIGINS.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO app mount
sio_app = socketio.ASGIApp(socketio_server=sio, other_asgi_app=app)

# Static files
# app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

@app.get("/")
async def read_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/attendance")
async def read_attendance(request: Request):
    return templates.TemplateResponse("attendance.html", {"request": request})

@app.get("/students")
async def read_students(request: Request):
    return templates.TemplateResponse("students.html", {"request": request})

@app.get("/api_keys")
async def read_api_keys(request: Request):
    return templates.TemplateResponse("api_keys.html", {"request": request})

from app.routers import ws_camera, classes, students, api_keys, attendance

app.include_router(ws_camera.router)
app.include_router(classes.router)
app.include_router(students.router)
app.include_router(api_keys.router)
app.include_router(attendance.router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Mount the ASGI app
app = sio_app
