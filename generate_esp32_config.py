#!/usr/bin/env python3
"""
Script tự động sinh cấu hình ESP32 dựa trên cấu hình server
Chạy script này sau khi tạo API key mới trên server
"""

import os
import json
import sqlite3
from typing import Dict, Any

def get_api_keys() -> Dict[str, Dict[str, Any]]:
    """Lấy danh sách API keys từ database"""
    api_keys = {}
    
    # Kết nối database
    system_dir = os.environ.get("SYSTEM_DIR", "classes/_system")
    db_path = os.path.join(system_dir, "api_keys.db")
    
    if not os.path.exists(db_path):
        print(f"⚠️ Database API keys không tồn tại: {db_path}")
        return api_keys
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT api_key, class_name, device_name, created_at FROM api_keys WHERE is_active=1"
        )
        
        for row in cursor.fetchall():
            api_key, class_name, device_name, created_at = row
            api_keys[api_key] = {
                'class_name': class_name,
                'device_name': device_name,
                'created_at': created_at
            }
        
        conn.close()
        print(f"✅ Đã tải {len(api_keys)} API keys từ database")
        
    except Exception as e:
        print(f"❌ Lỗi khi đọc database: {e}")
    
    return api_keys

def generate_esp32_config(api_key: str, class_name: str) -> str:
    """Tạo đoạn code cấu hình cho ESP32"""
    
    # Lấy thông tin từ environment variables
    server_url = os.environ.get("SERVER_URL", "https://attendance-system-production-1d75.up.railway.app/api/recognize")
    mqtt_broker = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_use_tls = os.environ.get("MQTT_USE_TLS", "").lower() in ("1", "true", "yes")
    mqtt_tls_insecure = os.environ.get("MQTT_TLS_INSECURE", "").lower() in ("1", "true", "yes")
    
    config_template = f"""
// ==================== CẤU HÌNH TỰ ĐỘNG ====================
// File này được sinh tự động từ server configuration
// Không chỉnh sửa thủ công - sẽ bị ghi đè

static const char* SERVER_URL = "{server_url}";
static const char* MQTT_HOST = "{mqtt_broker}";
static const uint16_t MQTT_PORT = {mqtt_port};
static const bool MQTT_USE_TLS = {'true' if mqtt_use_tls else 'false'};
static const bool MQTT_TLS_INSECURE = {'true' if mqtt_tls_insecure else 'false'};
static const char* MQTT_USERNAME = "{os.environ.get('MQTT_USERNAME', '')}";
static const char* MQTT_PASSWORD = "{os.environ.get('MQTT_PASSWORD', '')}";
static const char* MQTT_ROOT_CA = "";
static const char* CLASS_NAME = "{class_name}";
static const char* API_KEY = "{api_key}";

// ==================== CẤU HÌNH MẶC ĐỊNH (FALLBACK) ====================
static const char* DEFAULT_WIFI_SSID = "Ngoc Tram 2";
static const char* DEFAULT_WIFI_PASSWORD = "77779999";
"""
    
    return config_template

def main():
    """Hàm chính"""
    print("🔧 Script sinh cấu hình ESP32 tự động")
    print("=" * 50)
    
    # Lấy danh sách API keys
    api_keys = get_api_keys()
    
    if not api_keys:
        print("❌ Không có API keys nào trong database")
        print("👉 Vui lòng tạo API keys trên giao diện quản lý server trước")
        return
    
    # Tạo thư mục output nếu chưa tồn tại
    output_dir = "esp32_configs"
    os.makedirs(output_dir, exist_ok=True)
    
    # Tạo config cho từng API key
    for api_key, key_info in api_keys.items():
        class_name = key_info['class_name']
        device_name = key_info['device_name'] or "unknown"
        
        print(f"📁 Đang tạo config cho: {class_name} - {device_name}")
        
        # Tạo tên file an toàn
        safe_class_name = "".join(c for c in class_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_device_name = "".join(c for c in device_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = f"{safe_class_name}_{safe_device_name}.h"
        filepath = os.path.join(output_dir, filename)
        
        # Tạo nội dung config
        config_content = generate_esp32_config(api_key, class_name)
        
        # Ghi file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        print(f"✅ Đã tạo: {filepath}")
        
        # In thông tin để copy vào ESP32
        print(f"\n📋 Thông tin cho ESP32:")
        print(f"   Class: {class_name}")
        print(f"   API Key: {api_key}")
        print(f"   Server: {os.environ.get('SERVER_URL', 'https://attendance-system-production-1d75.up.railway.app/api/recognize')}")
        print("-" * 40)
    
    print(f"\n🎉 Đã tạo {len(api_keys)} file cấu hình trong thư mục '{output_dir}/'")
    print("👉 Copy nội dung từ file .h vào ESP32 code và thay thế phần cấu hình hiện tại")

if __name__ == "__main__":
    main()