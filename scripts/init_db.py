import asyncio
import os
import sys

# Add root directory to sys.path to import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings
from app.models import Base

async def init_db():
    """
    Initialize database schema with all tables and indexes.
    This script is idempotent - safe to run multiple times.
    """
    print(f"Connecting to database...")
    
    # SQLAlchemy requires postgresql+asyncpg for async connections
    db_url = settings.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")
    
    engine = create_async_engine(db_url, echo=True)
    
    try:
        async with engine.begin() as conn:
            print("\n" + "="*60)
            print("Creating all tables and indexes from models...")
            print("="*60 + "\n")
            
            # Create all tables with indexes defined in models
            await conn.run_sync(Base.metadata.create_all)
            
            print("\n" + "="*60)
            print("Database initialization completed successfully!")
            print("="*60)
            print("\nCreated tables:")
            print("  - classes")
            print("  - students (with idx_students_class)")
            print("  - attendance_records (with idx_attendance_recorded_at, idx_attendance_class_time)")
            print("  - api_keys (with idx_api_keys_active)")
            print("\n")
            
    except Exception as e:
        print(f"\n❌ Error initializing database: {e}")
        sys.exit(1)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    if not settings.DATABASE_URL:
        print("❌ Error: DATABASE_URL environment variable is not set!")
        print("Please set DATABASE_URL in your .env file or environment.")
        sys.exit(1)
        
    asyncio.run(init_db())
