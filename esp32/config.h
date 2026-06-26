#pragma once

// WiFi
#define WIFI_SSID       "your_wifi_ssid"
#define WIFI_PASSWORD   "your_wifi_password"

// Railway Server
#define SERVER_HOST     "your-app.railway.app"
#define SERVER_PORT     443                    // HTTPS/WSS trên Railway
#define WS_PATH         "/ws/camera"

// Device
#define API_KEY         "your_api_key_here"
#define DEVICE_ID       "ESP32_CAM_01"

// Camera (CHỌN ĐÚNG BOARD)
#define CAMERA_MODEL_AI_THINKER   // hoặc WROVER_KIT, M5STACK_WIDE...

// Capture settings
#define CAPTURE_INTERVAL_MS  1500  // ms giữa các lần chụp
#define JPEG_QUALITY         12    // 0-63, thấp hơn = chất lượng cao hơn
#define FRAME_SIZE           FRAMESIZE_VGA  // 640x480

// Pin definition cho CAMERA_MODEL_AI_THINKER
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
