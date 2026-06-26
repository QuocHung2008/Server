import asyncpg
from app.config import settings

# Global connection pool
pool = None

async def init_db_pool():
    global pool
    print("Initializing Database connection pool...")
    pool = await asyncpg.create_pool(
        settings.DATABASE_URL,
        min_size=2,
        max_size=10
    )
    print("Database connection pool initialized.")

async def close_db_pool():
    global pool
    if pool is not None:
        print("Closing Database connection pool...")
        await pool.close()
        print("Database connection pool closed.")

async def get_db():
    global pool
    if pool is None:
        raise Exception("Database pool is not initialized")
    async with pool.acquire() as connection:
        yield connection
