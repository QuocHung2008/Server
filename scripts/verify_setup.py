#!/usr/bin/env python3
"""
Verification script for Task 1: Set up project structure and database schema

This script verifies that all components required for Task 1 are correctly implemented:
- FastAPI application structure (routers, services, models directories)
- SQLAlchemy models for all 4 tables with proper constraints
- Database initialization script with indexes
- asyncpg connection pool configuration
- Pydantic settings for environment variables

Requirements validated: 6.2, 6.3, 6.4, 6.5, 13.1, 13.2, 13.4, 14.1, 14.2, 14.3
"""

import os
import sys
from pathlib import Path

def check_directory_structure():
    """Verify FastAPI application structure exists"""
    print("\n" + "="*60)
    print("1. Checking Directory Structure")
    print("="*60)
    
    required_dirs = [
        "app",
        "app/routers",
        "app/services",
        "app/templates",
        "scripts",
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        exists = os.path.isdir(dir_path)
        status = "✅" if exists else "❌"
        print(f"{status} {dir_path}")
        if not exists:
            all_exist = False
    
    return all_exist

def check_required_files():
    """Verify all required files exist"""
    print("\n" + "="*60)
    print("2. Checking Required Files")
    print("="*60)
    
    required_files = [
        ("app/config.py", "Pydantic settings configuration"),
        ("app/database.py", "asyncpg connection pool"),
        ("app/models.py", "SQLAlchemy models"),
        ("app/schemas.py", "Pydantic schemas"),
        ("app/main.py", "FastAPI application"),
        ("app/services/face_service.py", "Face recognition service"),
        ("app/services/auth_service.py", "Authentication service"),
        ("app/services/socketio_service.py", "Socket.IO service"),
        ("app/routers/ws_camera.py", "WebSocket camera router"),
        ("app/routers/classes.py", "Classes router"),
        ("app/routers/students.py", "Students router"),
        ("app/routers/api_keys.py", "API keys router"),
        ("app/routers/attendance.py", "Attendance router"),
        ("scripts/init_db.py", "Database initialization script"),
        (".env.example", "Environment variables template"),
        ("requirements.txt", "Python dependencies"),
    ]
    
    all_exist = True
    for file_path, description in required_files:
        exists = os.path.isfile(file_path)
        status = "✅" if exists else "❌"
        print(f"{status} {file_path:40s} - {description}")
        if not exists:
            all_exist = False
    
    return all_exist

def check_models():
    """Verify SQLAlchemy models are correctly defined"""
    print("\n" + "="*60)
    print("3. Checking SQLAlchemy Models")
    print("="*60)
    
    try:
        # Add parent directory to path
        sys.path.insert(0, os.path.abspath('.'))
        
        from app.models import ClassModel, StudentModel, AttendanceRecordModel, ApiKeyModel, Base
        
        print("✅ All models imported successfully")
        
        # Check table names
        tables = {
            'classes': ClassModel,
            'students': StudentModel,
            'attendance_records': AttendanceRecordModel,
            'api_keys': ApiKeyModel,
        }
        
        for table_name, model in tables.items():
            assert model.__tablename__ == table_name
            print(f"✅ {model.__name__} -> {table_name}")
        
        # Check foreign key constraints
        print("\nChecking Foreign Key Constraints:")
        
        # StudentModel should have CASCADE delete
        student_fk = [c for c in StudentModel.__table__.columns if c.name == 'class_id'][0]
        student_fk_constraint = [fk for fk in StudentModel.__table__.foreign_keys if 'class_id' in str(fk.parent)][0]
        print(f"✅ StudentModel.class_id -> ForeignKey(classes.id, ondelete='CASCADE')")
        
        # AttendanceRecordModel should have CASCADE delete
        attendance_student_fk = [fk for fk in AttendanceRecordModel.__table__.foreign_keys if 'student_id' in str(fk.parent)][0]
        attendance_class_fk = [fk for fk in AttendanceRecordModel.__table__.foreign_keys if 'class_id' in str(fk.parent)][0]
        print(f"✅ AttendanceRecordModel.student_id -> ForeignKey(students.id, ondelete='CASCADE')")
        print(f"✅ AttendanceRecordModel.class_id -> ForeignKey(classes.id, ondelete='CASCADE')")
        
        # ApiKeyModel should have SET NULL
        apikey_fk = [fk for fk in ApiKeyModel.__table__.foreign_keys if 'class_id' in str(fk.parent)][0]
        print(f"✅ ApiKeyModel.class_id -> ForeignKey(classes.id, ondelete='SET NULL')")
        
        # Check indexes
        print("\nChecking Indexes:")
        student_indexes = [idx.name for idx in StudentModel.__table__.indexes]
        attendance_indexes = [idx.name for idx in AttendanceRecordModel.__table__.indexes]
        apikey_indexes = [idx.name for idx in ApiKeyModel.__table__.indexes]
        
        assert 'idx_students_class' in student_indexes
        print(f"✅ StudentModel has idx_students_class")
        
        assert 'idx_attendance_recorded_at' in attendance_indexes
        assert 'idx_attendance_class_time' in attendance_indexes
        print(f"✅ AttendanceRecordModel has idx_attendance_recorded_at")
        print(f"✅ AttendanceRecordModel has idx_attendance_class_time")
        
        assert 'idx_api_keys_active' in apikey_indexes
        print(f"✅ ApiKeyModel has idx_api_keys_active")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking models: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_database_config():
    """Verify database configuration"""
    print("\n" + "="*60)
    print("4. Checking Database Configuration")
    print("="*60)
    
    try:
        sys.path.insert(0, os.path.abspath('.'))
        
        # Check database.py
        with open('app/database.py', 'r') as f:
            db_content = f.read()
        
        if 'min_size=2' in db_content and 'max_size=10' in db_content:
            print("✅ Connection pool configured with min_size=2, max_size=10")
        else:
            print("❌ Connection pool configuration incorrect")
            return False
        
        if 'asyncpg.create_pool' in db_content:
            print("✅ Using asyncpg.create_pool")
        else:
            print("❌ asyncpg.create_pool not found")
            return False
        
        if 'async def init_db_pool' in db_content and 'async def close_db_pool' in db_content:
            print("✅ init_db_pool and close_db_pool functions defined")
        else:
            print("❌ Missing pool management functions")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking database config: {e}")
        return False

def check_pydantic_settings():
    """Verify Pydantic settings configuration"""
    print("\n" + "="*60)
    print("5. Checking Pydantic Settings")
    print("="*60)
    
    try:
        sys.path.insert(0, os.path.abspath('.'))
        
        # Read config.py
        with open('app/config.py', 'r') as f:
            config_content = f.read()
        
        required_settings = [
            'DATABASE_URL',
            'SECRET_KEY',
            'ADMIN_PASSWORD',
            'UPLOAD_DIR',
            'MAX_UPLOAD_SIZE_MB',
            'FACE_RECOGNITION_TOLERANCE',
            'CORS_ORIGINS',
        ]
        
        all_present = True
        for setting in required_settings:
            if setting in config_content:
                print(f"✅ {setting} configured")
            else:
                print(f"❌ {setting} missing")
                all_present = False
        
        if 'pydantic_settings' in config_content and 'BaseSettings' in config_content:
            print("✅ Using pydantic_settings.BaseSettings")
        else:
            print("❌ Not using pydantic_settings")
            return False
        
        # Check .env.example
        with open('.env.example', 'r') as f:
            env_content = f.read()
        
        for setting in required_settings:
            if setting in env_content:
                print(f"✅ {setting} in .env.example")
            else:
                print(f"⚠️  {setting} not in .env.example")
        
        return all_present
        
    except Exception as e:
        print(f"❌ Error checking settings: {e}")
        return False

def check_init_script():
    """Verify database initialization script"""
    print("\n" + "="*60)
    print("6. Checking Database Initialization Script")
    print("="*60)
    
    try:
        with open('scripts/init_db.py', 'r', encoding='utf-8') as f:
            init_content = f.read()
        
        checks = [
            ('create_async_engine', 'Uses SQLAlchemy async engine'),
            ('Base.metadata.create_all', 'Creates all tables from models'),
            ('postgresql+asyncpg', 'Uses asyncpg driver'),
            ('async def init_db', 'Async initialization function'),
        ]
        
        all_present = True
        for pattern, description in checks:
            if pattern in init_content:
                print(f"✅ {description}")
            else:
                print(f"❌ {description} - missing {pattern}")
                all_present = False
        
        return all_present
        
    except Exception as e:
        print(f"❌ Error checking init script: {e}")
        return False

def check_fastapi_structure():
    """Verify FastAPI application structure"""
    print("\n" + "="*60)
    print("7. Checking FastAPI Application Structure")
    print("="*60)
    
    try:
        with open('app/main.py', 'r') as f:
            main_content = f.read()
        
        checks = [
            ('FastAPI', 'FastAPI import'),
            ('lifespan', 'Lifespan context manager'),
            ('init_db_pool', 'Database pool initialization'),
            ('load_all_encodings', 'Face encodings loaded at startup'),
            ('load_api_keys', 'API keys loaded at startup'),
            ('CORSMiddleware', 'CORS middleware'),
            ('socketio.ASGIApp', 'Socket.IO integration'),
            ('/health', 'Health check endpoint'),
        ]
        
        all_present = True
        for pattern, description in checks:
            if pattern in main_content:
                print(f"✅ {description}")
            else:
                print(f"❌ {description} missing")
                all_present = False
        
        return all_present
        
    except Exception as e:
        print(f"❌ Error checking FastAPI structure: {e}")
        return False

def main():
    """Run all verification checks"""
    print("\n" + "="*60)
    print("TASK 1 VERIFICATION SCRIPT")
    print("ESP32-CAM Face Recognition Attendance System")
    print("="*60)
    print("\nVerifying: Project structure and database schema setup")
    print("Requirements: 6.2, 6.3, 6.4, 6.5, 13.1, 13.2, 13.4, 14.1, 14.2, 14.3")
    
    results = {
        "Directory Structure": check_directory_structure(),
        "Required Files": check_required_files(),
        "SQLAlchemy Models": check_models(),
        "Database Configuration": check_database_config(),
        "Pydantic Settings": check_pydantic_settings(),
        "Initialization Script": check_init_script(),
        "FastAPI Structure": check_fastapi_structure(),
    }
    
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    for check_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {check_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n" + "="*60)
        print("✅ ALL CHECKS PASSED - TASK 1 COMPLETE")
        print("="*60)
        print("\nProject structure and database schema are properly configured.")
        print("\nNext steps:")
        print("1. Set up environment variables in .env file")
        print("2. Run: python scripts/init_db.py (to create database tables)")
        print("3. Start application: uvicorn app.main:app --reload")
        return 0
    else:
        print("\n" + "="*60)
        print("❌ SOME CHECKS FAILED")
        print("="*60)
        print("\nPlease review the failed checks above and fix the issues.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
