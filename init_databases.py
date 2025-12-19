#!/usr/bin/env python3
"""
Script khởi tạo databases trước khi start Flask app
Chạy file này TRƯỚC khi start gunicorn
"""

import os
import sqlite3
import datetime
from werkzeug.security import generate_password_hash

def init_user_db():
    """Khởi tạo database users"""
    print("📊 Initializing user database...")
    
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        # Create table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TEXT
        )''')
        
        # Check if admin exists
        c.execute("SELECT * FROM users WHERE username='admin'")
        if not c.fetchone():
            admin_hash = generate_password_hash('admin123')
            c.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     ('admin', admin_hash, 'admin', datetime.datetime.now().isoformat()))
            print("   ✅ Created default admin user (admin/admin123)")
        else:
            print("   ℹ️  Admin user already exists")
        
        conn.commit()
        conn.close()
        print("✅ User database initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error initializing user database: {e}")
        return False

def init_api_keys_db():
    """Khởi tạo database API keys"""
    print("📊 Initializing API keys database...")
    
    try:
        conn = sqlite3.connect('api_keys.db')
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT UNIQUE NOT NULL,
            class_name TEXT NOT NULL,
            device_name TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1
        )''')
        
        conn.commit()
        conn.close()
        print("✅ API keys database initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error initializing API keys database: {e}")
        return False

def ensure_directories():
    """Tạo các thư mục cần thiết"""
    print("📁 Creating directories...")
    
    try:
        # Try to create classes directory
        if not os.path.exists('classes'):
            os.makedirs('classes', exist_ok=True)
            print("   ✅ Created 'classes' directory")
        else:
            print("   ℹ️  'classes' directory already exists")
        
        # Try to create DS subdirectory
        ds_path = 'classes/DS'
        if not os.path.exists(ds_path):
            try:
                os.makedirs(ds_path, exist_ok=True)
                print("   ✅ Created 'classes/DS' directory")
            except PermissionError:
                # Railway volume is mounted, may not have permission
                print("   ⚠️  Cannot create 'classes/DS' - Railway volume mounted (this is OK)")
        else:
            print("   ℹ️  'classes/DS' directory already exists")
        
        print("✅ Directories check completed")
        return True
        
    except Exception as e:
        # Don't fail initialization if directory creation fails
        # Railway might handle this differently
        print(f"⚠️  Directory creation warning: {e}")
        print("   ℹ️  Continuing anyway - directories may be managed by Railway")
        return True  # Return True to not block initialization

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🚀 DATABASE INITIALIZATION")
    print("="*70 + "\n")
    
    success = True
    
    # 1. Create directories
    if not ensure_directories():
        success = False
    
    # 2. Initialize user database
    if not init_user_db():
        success = False
    
    # 3. Initialize API keys database
    if not init_api_keys_db():
        success = False
    
    print("\n" + "="*70)
    if success:
        print("✅ ALL DATABASES INITIALIZED SUCCESSFULLY")
    else:
        print("❌ SOME DATABASES FAILED TO INITIALIZE")
    print("="*70 + "\n")
    
    exit(0 if success else 1)