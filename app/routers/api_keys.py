from fastapi import APIRouter
from app.database import pool

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])

@router.get("/")
async def get_api_keys():
    if pool is None: return []
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT id, key_hash, label, device_id, is_active FROM api_keys")
        return [dict(r) for r in records]
