from fastapi import APIRouter
from app.database import pool

router = APIRouter(prefix="/api/classes", tags=["classes"])

@router.get("/")
async def get_classes():
    if pool is None: return []
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT id, name, created_at FROM classes ORDER BY name")
        return [dict(r) for r in records]
