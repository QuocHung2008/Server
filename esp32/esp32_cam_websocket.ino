#include <Arduino.h>
#include "config.h"
#include "esp_camera.h"
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

using namespace websockets;

WebsocketsClient client;
unsigned long lastCapture = 0;
bool wsConnected = false;

// Callback khi nhận message từ server
void onMessageCallback(WebsocketsMessage message) {
  if (message.isText()) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, message.data());
    if (err) return;
    
    const char* status = doc["status"];
    if (strcmp(status, "recognized") == 0) {
      Serial.printf("[OK] %s (%s) - conf: %.2f\n",
        doc["name"].as<const char*>(),
        doc["student_id"].as<const char*>(),
        doc["confidence"].as<float>());
      // Bật LED GPIO33 (built-in LED active-low)
      digitalWrite(33, LOW);  // LOW = ON
      delay(800);             // Delay ngắn ok sau khi nhận result
      digitalWrite(33, HIGH);
    } else if (strcmp(status, "unknown") == 0) {
      Serial.println("[--] Unknown face detected");
    }
    // "no_face": bỏ qua
  }
}

void onEventsCallback(WebsocketsEvent event, String data) {
  if (event == WebsocketsEvent::ConnectionOpened) {
    wsConnected = true;
    Serial.println("[WS] Connected to server");
  } else if (event == WebsocketsEvent::ConnectionClosed) {
    wsConnected = false;
    Serial.println("[WS] Disconnected - will reconnect...");
  }
}

bool connectWebSocket() {
  String url = String("wss://") + SERVER_HOST + WS_PATH 
             + "?api_key=" + API_KEY 
             + "&device_id=" + DEVICE_ID;
  client.setInsecure();  // Bỏ qua verify TLS cert
  client.onMessage(onMessageCallback);
  client.onEvent(onEventsCallback);
  return client.connect(url);
}

void setup() {
  Serial.begin(115200);
  pinMode(33, OUTPUT);
  digitalWrite(33, HIGH);  // LED off
  
  // Khởi tạo camera
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  // Init với config nhỏ nếu PSRAM ko có
  if(psramFound()){
    config.frame_size = FRAME_SIZE;
    config.jpeg_quality = JPEG_QUALITY;
    config.fb_count = 1; // Giảm mem
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t camErr = esp_camera_init(&config);
  if (camErr != ESP_OK) {
    Serial.printf("[CAM] Init failed: 0x%x\n", camErr);
    esp_restart();
  }
  
  // Kết nối WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    Serial.print(".");
    retries++;
  }
  if (WiFi.status() != WL_CONNECTED) esp_restart();
  Serial.printf("\n[WIFI] Connected: %s\n", WiFi.localIP().toString().c_str());
  
  // Kết nối WebSocket
  if (!connectWebSocket()) {
    Serial.println("[WS] Initial connection failed - will retry in loop");
  }
}

void loop() {
  client.poll();  // BẮT BUỘC gọi mỗi loop
  
  if (!wsConnected) {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > 3000) {
      Serial.println("[WS] Reconnecting...");
      connectWebSocket();
      lastRetry = millis();
    }
    return;
  }
  
  if (millis() - lastCapture < CAPTURE_INTERVAL_MS) return;
  lastCapture = millis();
  
  // Kiểm tra heap trước khi chụp
  if (esp_get_free_heap_size() < 50000) {
    Serial.println("[MEM] Low heap - restarting");
    esp_restart();
  }
  
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] Capture failed");
    return;
  }
  
  // Gửi binary frame qua WebSocket
  bool sent = client.sendBinary((char*)fb->buf, fb->len);
  if (!sent) {
    Serial.println("[WS] Send failed");
    wsConnected = false;
  }
  
  esp_camera_fb_return(fb);  // PHẢI return ngay
}
