import asyncio
import asyncpg
import sys
import os

# Add root project path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

async def init_db():
    print(f"Connecting to {settings.DATABASE_URL} to initialize schema...")
    
    conn = await asyncpg.connect(settings.DATABASE_URL)
    
    try:
        # Create schema
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        ''')
        
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            student_code VARCHAR(50) UNIQUE NOT NULL,
            full_name VARCHAR(200) NOT NULL,
            class_id UUID REFERENCES classes(id),
            image_path TEXT,
            face_encoding BYTEA,            -- numpy array serialized (pickle/bytes)
            created_at TIMESTAMP DEFAULT NOW()
        );
        ''')
        
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS attendance_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            student_id UUID REFERENCES students(id),
            class_id UUID REFERENCES classes(id),
            device_id VARCHAR(100),
            confidence FLOAT,
            status VARCHAR(20) DEFAULT 'present',
            recorded_at TIMESTAMP DEFAULT NOW()
        );
        ''')
        
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_hash VARCHAR(64) UNIQUE NOT NULL,
            label VARCHAR(100),
            class_id UUID REFERENCES classes(id),
            device_id VARCHAR(100),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            last_used_at TIMESTAMP
        );
        ''')
        
        # Create indexes
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_attendance_recorded_at ON attendance_records(recorded_at DESC);')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_attendance_class_time ON attendance_records(class_id, recorded_at DESC);')
        
        print("Schema initialized successfully.")
    except Exception as e:
        print(f"Error initializing schema: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(init_db())
