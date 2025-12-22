#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <esp_camera.h>
#include <Arduino_GFX_Library.h>
#include <TJpg_Decoder.h>
#include <ArduinoJson.h>

// ==================== CẤU HÌNH MẶC ĐỊNH (FALLBACK) ====================
static const char* DEFAULT_WIFI_SSID = "Ngoc Tram 2";
static const char* DEFAULT_WIFI_PASSWORD = "77779999";

// ==================== CẤU HÌNH ĐỘNG (NVS) ====================
// Các giá trị này sẽ được ghi đè bởi loadConfigFromNvs()
static char SERVER_URL[256] = "https://attendance-system-production-1d75.up.railway.app/api/recognize";
static char MQTT_HOST[128] = "6575a30783c5453485012d4094a0db47.s1.eu.hivemq.cloud";
static uint16_t MQTT_PORT = 8883;
static bool MQTT_USE_TLS = true;
static bool MQTT_TLS_INSECURE = true;
static char MQTT_USERNAME[64] = "bill_cipher";
static char MQTT_PASSWORD[64] = "nohter-cuttih-1suNva";
static char MQTT_ROOT_CA[512] = "";
static char CLASS_NAME[32] = "12T1";
static char API_KEY[128] = "esp32_iDZNJVCtZrPVoWNl1a8jWoi61rAeZe-5a_v_8p6vOnQ";

// ==================== CẤU HÌNH CHÂN CẮM ====================
#define TFT_SCK 14
#define TFT_MOSI 13
#define TFT_CS 15
#define TFT_DC 2
#define TFT_RST -1
#define BUTTON_PIN 12
#define FLASH_PIN 4

// ==================== MÀU SẮC ====================
#define BLACK 0x0000
#define DARK_BG 0x1103
#define GRADIENT_1 0x2145
#define GRADIENT_2 0x1E5F
#define ACCENT_BLUE 0x04B0
#define SUCCESS_GREEN 0x27E0
#define WHITE 0xFFFF
#define YELLOW 0xFFE0
#define RED 0xF800
#define GRAY 0x8410

// ==================== MÀN HÌNH ====================
Arduino_ESP32SPI bus = Arduino_ESP32SPI(TFT_DC, TFT_CS, TFT_SCK, TFT_MOSI, -1);
Arduino_ILI9341 tft = Arduino_ILI9341(&bus);
static const int SCREEN_WIDTH = 240;
static const int SCREEN_HEIGHT = 320;

// ==================== FREE RTOS ====================
static EventGroupHandle_t g_eventGroup;
static const EventBits_t BIT_WIFI_OK = (1 << 0);
static const EventBits_t BIT_MQTT_OK = (1 << 1);
static const EventBits_t BIT_BTN_CAPTURE = (1 << 2);
static const EventBits_t BIT_RESULT_RX = (1 << 3);
static const EventBits_t BIT_AP_MODE = (1 << 4);

static TaskHandle_t g_taskNet = nullptr;
static TaskHandle_t g_taskUi = nullptr;
static TaskHandle_t g_taskApp = nullptr;

static SemaphoreHandle_t g_stateMutex;

// ==================== GPIO ISR SERVICE GUARD ====================
static bool g_gpio_isr_installed = false;

// ==================== TRẠNG THÁI ỨNG DỤNG ====================
enum AppState : uint8_t {
  APP_CONNECTING = 0,
  APP_STREAMING,
  APP_CAPTURING,
  APP_UPLOADING,
  APP_WAITING_RESULT,
  APP_SHOWING_RESULT,
  APP_ERROR
};

struct AppSharedState {
  AppState state = APP_CONNECTING;
  uint32_t stateEnterMs = 0;
  uint32_t tButtonMs = 0;
  uint32_t tCaptureMs = 0;
  uint32_t tUploadDoneMs = 0;
  uint32_t tResultMs = 0;

  char lastResult[128] = {0};
  bool lastResultUnknown = false;
  bool resultAvailable = false;
  bool flashEnabled = true;
};

static AppSharedState g_app;
static volatile bool g_pendingReboot = false;

static void setState(AppState s);
static AppSharedState getStateSnapshot();
static void buildTopics();
String utf8ToAscii(const String& utf8Str);
void displayNameWordWrap(const String& name, int yStart);
bool send_to_tft(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap);
void displayMessage(const char* msg, uint16_t color, uint16_t bgColor);
void drawResultScreenModern(const String& name);
static void loadWifiFromNvs();
static void saveWifiToNvs(const char* ssid, const char* pass);
static void wifiStartSta();
static void wifiStartApFallback();
static void wifiApplyNewCredentials(const char* ssid, const char* pass);
static void webSetupRoutes();
static void wifiUpdateStatusBits();
static void mqttPublishStatus(const char* status);
static void mqttPublishTelemetry();
static void handleIncomingCommand(const JsonDocument& doc);
static void mqttCallback(char* topic, uint8_t* payload, unsigned int length);
static bool mqttEnsureConnected(uint32_t nowMs);
static bool initCamera();
static bool cameraSetStreamMode();
static bool cameraSetCaptureMode();
static bool uploadFrameHttp(camera_fb_t* fb);
static void publishCaptureMeta(size_t jpegLen);
static void publishImageChunks(camera_fb_t* fb);
static void IRAM_ATTR onButtonIsr();
static void taskNetwork(void* pv);
static void taskApp(void* pv);
static void taskUi(void* pv);
static void serialPoll();
void setup();
void loop();

static void setState(AppState s) {
  xSemaphoreTake(g_stateMutex, portMAX_DELAY);
  g_app.state = s;
  g_app.stateEnterMs = millis();
  xSemaphoreGive(g_stateMutex);
}

static AppSharedState getStateSnapshot() {
  AppSharedState snap;
  xSemaphoreTake(g_stateMutex, portMAX_DELAY);
  snap = g_app;
  xSemaphoreGive(g_stateMutex);
  return snap;
}

// ==================== CẤU HÌNH RUNTIME (NVS) ====================
struct RuntimeConfig {
  char wifiSsid[64] = {0};
  char wifiPass[64] = {0};

  framesize_t streamFrameSize = FRAMESIZE_QVGA;
  framesize_t captureFrameSize = FRAMESIZE_VGA;
  uint8_t jpegQualityStream = 14;
  uint8_t jpegQualityCapture = 12;

  bool publishImageChunks = false;
  uint16_t mqttImageChunkSize = 1024;

  uint32_t resultTimeoutMs = 10000;
  uint32_t showResultMs = 3000;
  bool mirrorHorizontal = false;
};

static RuntimeConfig g_cfg;

// ==================== HÀM LOAD CẤU HÌNH TỪ NVS ====================
static void loadConfigFromNvs() {
  Preferences prefs;
  if (prefs.begin("esp32cam", true)) {
    // Load server configuration
    prefs.getString("server_url", SERVER_URL, sizeof(SERVER_URL));
    prefs.getString("mqtt_host", MQTT_HOST, sizeof(MQTT_HOST));
    MQTT_PORT = prefs.getUShort("mqtt_port", MQTT_PORT);
    MQTT_USE_TLS = prefs.getBool("mqtt_use_tls", MQTT_USE_TLS);
    MQTT_TLS_INSECURE = prefs.getBool("mqtt_tls_insecure", MQTT_TLS_INSECURE);
    prefs.getString("mqtt_username", MQTT_USERNAME, sizeof(MQTT_USERNAME));
    prefs.getString("mqtt_password", MQTT_PASSWORD, sizeof(MQTT_PASSWORD));
    prefs.getString("mqtt_root_ca", MQTT_ROOT_CA, sizeof(MQTT_ROOT_CA));
    prefs.getString("class_name", CLASS_NAME, sizeof(CLASS_NAME));
    prefs.getString("api_key", API_KEY, sizeof(API_KEY));
    
    prefs.end();
    Serial.println("✅ Loaded configuration from NVS");
  } else {
    Serial.println("⚠️ Could not open NVS for reading, using default config");
  }
}

static void saveConfigToNvs() {
  Preferences prefs;
  if (prefs.begin("esp32cam", false)) {
    // Save server configuration
    prefs.putString("server_url", SERVER_URL);
    prefs.putString("mqtt_host", MQTT_HOST);
    prefs.putUShort("mqtt_port", MQTT_PORT);
    prefs.putBool("mqtt_use_tls", MQTT_USE_TLS);
    prefs.putBool("mqtt_tls_insecure", MQTT_TLS_INSECURE);
    prefs.putString("mqtt_username", MQTT_USERNAME);
    prefs.putString("mqtt_password", MQTT_PASSWORD);
    prefs.putString("mqtt_root_ca", MQTT_ROOT_CA);
    prefs.putString("class_name", CLASS_NAME);
    prefs.putString("api_key", API_KEY);
    
    prefs.end();
    Serial.println("✅ Saved configuration to NVS");
  } else {
    Serial.println("❌ Could not open NVS for writing");
  }
}
static Preferences g_prefs;

// ==================== NETWORK CLIENTS ====================
static WiFiClient g_mqttTcp;
static WiFiClientSecure g_mqttTls;
static PubSubClient g_mqtt(g_mqttTcp);
static WiFiClientSecure g_https;
static WebServer g_web(80);

// ==================== MQTT TOPICS ====================
static char g_deviceId[32] = {0};
static char g_topicBase[96] = {0};
static char g_topicCmd[128] = {0};
static char g_topicCmdAll[128] = {0};
static char g_topicResult[128] = {0};
static char g_topicStatus[128] = {0};
static char g_topicTelemetry[128] = {0};
static char g_topicMeta[128] = {0};
static char g_topicImage[128] = {0};

static void buildTopics() {
  snprintf(g_topicBase, sizeof(g_topicBase), "esp32cam/%s/%s", CLASS_NAME, g_deviceId);
  snprintf(g_topicCmd, sizeof(g_topicCmd), "%s/cmd", g_topicBase);
  snprintf(g_topicCmdAll, sizeof(g_topicCmdAll), "esp32cam/%s/all/cmd", CLASS_NAME);
  snprintf(g_topicResult, sizeof(g_topicResult), "%s/result", g_topicBase);
  snprintf(g_topicStatus, sizeof(g_topicStatus), "%s/status", g_topicBase);
  snprintf(g_topicTelemetry, sizeof(g_topicTelemetry), "%s/telemetry", g_topicBase);
  snprintf(g_topicMeta, sizeof(g_topicMeta), "%s/meta", g_topicBase);
  snprintf(g_topicImage, sizeof(g_topicImage), "%s/image", g_topicBase);
}

// ==================== HÀM CHUYỂN ĐỔI UTF-8 -> ASCII (VI) ====================

// ==================== HÀM CHUYỂN ĐỔI UTF-8 ====================
String utf8ToAscii(const String& utf8Str) {
    String result = "";
    result.reserve(utf8Str.length());
    
    for (unsigned int i = 0; i < utf8Str.length(); i++) {
        uint8_t c = utf8Str[i];
        
        if (c < 128) {
            result += (char)c;
            continue;
        }
        
        uint32_t codepoint = 0;
        int extraBytes = 0;
        
        if ((c & 0xE0) == 0xC0) {
            codepoint = c & 0x1F;
            extraBytes = 1;
        } else if ((c & 0xF0) == 0xE0) {
            codepoint = c & 0x0F;
            extraBytes = 2;
        } else if ((c & 0xF8) == 0xF0) {
            codepoint = c & 0x07;
            extraBytes = 3;
        } else {
            continue;
        }
        
        for (int j = 0; j < extraBytes; j++) {
            if (i + 1 >= utf8Str.length()) break;
            i++;
            uint8_t cont = utf8Str[i];
            if ((cont & 0xC0) != 0x80) break;
            codepoint = (codepoint << 6) | (cont & 0x3F);
        }
        
        char ascii = 0;
        
        // Vietnamese character mapping (simplified version)
        if (codepoint >= 0x00E0 && codepoint <= 0x00E3) ascii = 'a';
        else if (codepoint == 0x1EA1) ascii = 'a';
        else if (codepoint >= 0x1EA3 && codepoint <= 0x1EAD) ascii = 'a';
        else if (codepoint == 0x0103) ascii = 'a';
        else if (codepoint >= 0x1EAF && codepoint <= 0x1EB7) ascii = 'a';
        else if (codepoint >= 0x00E8 && codepoint <= 0x00EA) ascii = 'e';
        else if (codepoint >= 0x1EB9 && codepoint <= 0x1EC7) ascii = 'e';
        else if (codepoint >= 0x00EC && codepoint <= 0x00ED) ascii = 'i';
        else if (codepoint == 0x0129) ascii = 'i';
        else if (codepoint >= 0x1EC9 && codepoint <= 0x1ECB) ascii = 'i';
        else if (codepoint >= 0x00F2 && codepoint <= 0x00F5) ascii = 'o';
        else if (codepoint >= 0x1ECD && codepoint <= 0x1ED9) ascii = 'o';
        else if (codepoint == 0x01A1) ascii = 'o';
        else if (codepoint >= 0x1EDB && codepoint <= 0x1EE3) ascii = 'o';
        else if (codepoint >= 0x00F9 && codepoint <= 0x00FA) ascii = 'u';
        else if (codepoint == 0x0169) ascii = 'u';
        else if (codepoint >= 0x1EE5 && codepoint <= 0x1EE7) ascii = 'u';
        else if (codepoint == 0x01B0) ascii = 'u';
        else if (codepoint >= 0x1EE9 && codepoint <= 0x1EF1) ascii = 'u';
        else if (codepoint == 0x00FD) ascii = 'y';
        else if (codepoint >= 0x1EF3 && codepoint <= 0x1EF9) ascii = 'y';
        else if (codepoint == 0x0111) ascii = 'd';
        // Uppercase
        else if (codepoint >= 0x00C0 && codepoint <= 0x00C3) ascii = 'A';
        else if (codepoint == 0x1EA0) ascii = 'A';
        else if (codepoint >= 0x1EA2 && codepoint <= 0x1EAC) ascii = 'A';
        else if (codepoint == 0x0102) ascii = 'A';
        else if (codepoint >= 0x1EAE && codepoint <= 0x1EB6) ascii = 'A';
        else if (codepoint >= 0x00C8 && codepoint <= 0x00CA) ascii = 'E';
        else if (codepoint >= 0x1EB8 && codepoint <= 0x1EC6) ascii = 'E';
        else if (codepoint >= 0x00CC && codepoint <= 0x00CD) ascii = 'I';
        else if (codepoint == 0x0128) ascii = 'I';
        else if (codepoint >= 0x1EC8 && codepoint <= 0x1ECA) ascii = 'I';
        else if (codepoint >= 0x00D2 && codepoint <= 0x00D5) ascii = 'O';
        else if (codepoint >= 0x1ECC && codepoint <= 0x1ED8) ascii = 'O';
        else if (codepoint == 0x01A0) ascii = 'O';
        else if (codepoint >= 0x1EDA && codepoint <= 0x1EE2) ascii = 'O';
        else if (codepoint >= 0x00D9 && codepoint <= 0x00DA) ascii = 'U';
        else if (codepoint == 0x0168) ascii = 'U';
        else if (codepoint >= 0x1EE4 && codepoint <= 0x1EE6) ascii = 'U';
        else if (codepoint == 0x01AF) ascii = 'U';
        else if (codepoint >= 0x1EE8 && codepoint <= 0x1EF0) ascii = 'U';
        else if (codepoint == 0x00DD) ascii = 'Y';
        else if (codepoint >= 0x1EF2 && codepoint <= 0x1EF8) ascii = 'Y';
        else if (codepoint == 0x0110) ascii = 'D';
        
        if (ascii != 0) {
            result += ascii;
        }
    }
    
    return result;
}

// ==================== HIỂN THỊ TÊN WORD WRAP ====================
void displayNameWordWrap(const String& name, int yStart) {
    tft.setTextSize(2);
    tft.setTextColor(WHITE);
    
    int lineHeight = 40;
    int currentY = yStart;
    int maxWidth = 220;
    
    String currentLine = "";
    String word = "";
    String tempName = name + " ";
    
    for (unsigned int i = 0; i < tempName.length(); i++) {
        char c = tempName[i];
        
        if (c == ' ') {
            String testLine = currentLine;
            if (currentLine.length() > 0) testLine += " ";
            testLine += word;
            
            int textWidth = testLine.length() * 12;
            
            if (textWidth > maxWidth && currentLine.length() > 0) {
                int xPos = (SCREEN_WIDTH - currentLine.length() * 12) / 2;
                tft.setCursor(xPos, currentY);
                tft.println(currentLine);
                currentY += lineHeight;
                currentLine = word;
            } else {
                if (currentLine.length() > 0) currentLine += " ";
                currentLine += word;
            }
            word = "";
        } else {
            word += c;
        }
    }
    
    if (currentLine.length() > 0) {
        int xPos = (SCREEN_WIDTH - currentLine.length() * 12) / 2;
        tft.setCursor(xPos, currentY);
        tft.println(currentLine);
    }
}

// ==================== CALLBACK VẼ ẢNH ====================
bool send_to_tft(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
    if (y >= SCREEN_HEIGHT) return 0;
    int16_t x_offset = -40; 
    int16_t y_offset = 40; 
    int16_t draw_x = x + x_offset;
    int16_t draw_y = y + y_offset;
    tft.draw16bitRGBBitmap(draw_x, draw_y, bitmap, w, h);
    return 1;
}

// ==================== HIỂN THỊ MESSAGE ====================
void displayMessage(const char* msg, uint16_t color, uint16_t bgColor) {
    tft.fillRect(0, 150, 240, 40, bgColor); 
    tft.setTextSize(2);
    int len = strlen(msg);
    int x = (SCREEN_WIDTH - (len * 12)) / 2;
    if (x < 0) x = 0;
    tft.setCursor(x, 160);
    tft.setTextColor(color);
    tft.println(msg);
}

// ==================== GIAO DIỆN KẾT QUẢ ====================
void drawResultScreenModern(const String& name) {
    tft.fillRect(0, 0, SCREEN_WIDTH, 120, GRADIENT_1);
    tft.fillRect(0, 120, SCREEN_WIDTH, SCREEN_HEIGHT - 120, DARK_BG);
    
    tft.drawRect(0, 0, SCREEN_WIDTH, 120, ACCENT_BLUE);
    tft.drawLine(0, 115, SCREEN_WIDTH, 115, ACCENT_BLUE);
    
    tft.setTextColor(WHITE);
    tft.setTextSize(2);
    tft.setCursor(65, 20);
    tft.println("KET QUA");
    
    tft.drawLine(50, 50, 190, 50, ACCENT_BLUE);
    
    if (name == "Unknown") {
        tft.setTextColor(RED);
        int xPos = (SCREEN_WIDTH - String("KHONG NHAN DIEN").length() * 12) / 2;
        tft.setCursor(xPos, 140);
        tft.println("KHONG NHAN DIEN");
    } else {
        tft.setTextColor(SUCCESS_GREEN);
        displayNameWordWrap(name, 140);
    }
    
    tft.drawLine(20, 300, 220, 300, ACCENT_BLUE);
    tft.fillRect(100, 305, 40, 2, ACCENT_BLUE);
}

// ==================== WIFI MODULE ====================
static void loadWifiFromNvs() {
  g_prefs.begin("cfg", true);
  String ssid = g_prefs.getString("ssid", "");
  String pass = g_prefs.getString("pass", "");
  g_prefs.end();

  if (ssid.length() == 0) ssid = DEFAULT_WIFI_SSID;
  if (pass.length() == 0) pass = DEFAULT_WIFI_PASSWORD;

  strlcpy(g_cfg.wifiSsid, ssid.c_str(), sizeof(g_cfg.wifiSsid));
  strlcpy(g_cfg.wifiPass, pass.c_str(), sizeof(g_cfg.wifiPass));
}

static void saveWifiToNvs(const char* ssid, const char* pass) {
  g_prefs.begin("cfg", false);
  g_prefs.putString("ssid", ssid);
  g_prefs.putString("pass", pass);
  g_prefs.end();
}

static void wifiStartSta() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.setSleep(false);
  WiFi.begin(g_cfg.wifiSsid, g_cfg.wifiPass);
}

static void wifiStartApFallback() {
  char apSsid[48];
  snprintf(apSsid, sizeof(apSsid), "ESP32CAM-%s", g_deviceId);
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apSsid, "12345678");
  xEventGroupSetBits(g_eventGroup, BIT_AP_MODE);
}

static void wifiApplyNewCredentials(const char* ssid, const char* pass) {
  saveWifiToNvs(ssid, pass);
  strlcpy(g_cfg.wifiSsid, ssid, sizeof(g_cfg.wifiSsid));
  strlcpy(g_cfg.wifiPass, pass, sizeof(g_cfg.wifiPass));

  xEventGroupClearBits(g_eventGroup, BIT_WIFI_OK);
  xEventGroupClearBits(g_eventGroup, BIT_MQTT_OK);
  WiFi.disconnect(true, true);
  wifiStartSta();
}

static void webSetupRoutes() {
  g_web.on("/", HTTP_GET, []() {
    String html;
    html.reserve(800);
    html += "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'/>";
    html += "<title>ESP32-CAM WiFi</title></head><body style='font-family:Arial;padding:16px'>";
    html += "<h3>WiFi Config</h3>";
    html += "<p>Device: ";
    html += g_deviceId;
    html += "</p>";
    html += "<form method='POST' action='/save'>";
    html += "SSID<br/><input name='ssid' maxlength='63' style='width:100%;padding:8px'/><br/><br/>";
    html += "Password<br/><input name='pass' maxlength='63' type='password' style='width:100%;padding:8px'/><br/><br/>";
    html += "<button type='submit' style='padding:10px 16px'>Save & Connect</button>";
    html += "</form>";
    html += "<p>AP password: 12345678</p>";
    html += "</body></html>";
    g_web.send(200, "text/html", html);
  });

  g_web.on("/save", HTTP_POST, []() {
    String ssid = g_web.arg("ssid");
    String pass = g_web.arg("pass");
    ssid.trim();
    pass.trim();
    if (ssid.length() == 0) {
      g_web.send(400, "text/plain", "SSID required");
      return;
    }
    saveWifiToNvs(ssid.c_str(), pass.c_str());
    g_web.send(200, "text/plain", "Saved. Reconnecting...");
    wifiApplyNewCredentials(ssid.c_str(), pass.c_str());
  });
}

static void wifiUpdateStatusBits() {
  if (WiFi.status() == WL_CONNECTED) {
    xEventGroupSetBits(g_eventGroup, BIT_WIFI_OK);
  } else {
    xEventGroupClearBits(g_eventGroup, BIT_WIFI_OK);
    xEventGroupClearBits(g_eventGroup, BIT_MQTT_OK);
  }
}

// ==================== MQTT MODULE ====================
static void mqttPublishStatus(const char* status) {
  if (!g_mqtt.connected()) return;
  g_mqtt.publish(g_topicStatus, status, true);
}

static void mqttPublishTelemetry() {
  if (!g_mqtt.connected()) return;
  AppSharedState s = getStateSnapshot();
  StaticJsonDocument<384> doc;
  doc["id"] = g_deviceId;
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  doc["heap"] = ESP.getFreeHeap();
  doc["psram"] = ESP.getFreePsram();
  doc["state"] = (uint8_t)s.state;
  JsonObject lat = doc["latency"].to<JsonObject>();
  if (s.tButtonMs && s.tResultMs && s.tResultMs >= s.tButtonMs) {
    lat["button_to_result_ms"] = (uint32_t)(s.tResultMs - s.tButtonMs);
  }
  char out[512];
  size_t n = serializeJson(doc, out, sizeof(out));
  g_mqtt.publish(g_topicTelemetry, (const uint8_t*)out, n, false);
}

static void handleIncomingCommand(const JsonDocument& doc) {
  if (doc.containsKey("capture") && doc["capture"].as<bool>()) {
    xEventGroupSetBits(g_eventGroup, BIT_BTN_CAPTURE);
  }

  if (doc.containsKey("pubImage")) {
    g_cfg.publishImageChunks = doc["pubImage"].as<bool>();
  }

  if (doc.containsKey("flash")) {
    bool en = doc["flash"].as<bool>();
    xSemaphoreTake(g_stateMutex, portMAX_DELAY);
    g_app.flashEnabled = en;
    xSemaphoreGive(g_stateMutex);
  }

  if (doc.containsKey("reboot") && doc["reboot"].as<bool>()) {
    mqttPublishStatus("rebooting");
    g_pendingReboot = true;
  }

  if (doc.containsKey("wifi")) {
    JsonVariantConst wifiV = doc["wifi"];
    if (wifiV.is<JsonObjectConst>()) {
      JsonObjectConst w = wifiV.as<JsonObjectConst>();
      const char* ssid = w["ssid"] | "";
      const char* pass = w["pass"] | "";
      if (ssid && strlen(ssid) > 0) {
        wifiApplyNewCredentials(ssid, pass ? pass : "");
      }
    }
  }

  if (doc.containsKey("camera")) {
    JsonVariantConst camV = doc["camera"];
    if (camV.is<JsonObjectConst>()) {
      JsonObjectConst c = camV.as<JsonObjectConst>();
      if (c.containsKey("captureQuality")) g_cfg.jpegQualityCapture = (uint8_t)c["captureQuality"].as<int>();
      if (c.containsKey("streamQuality")) g_cfg.jpegQualityStream = (uint8_t)c["streamQuality"].as<int>();
      if (c.containsKey("resultTimeoutMs")) g_cfg.resultTimeoutMs = (uint32_t)c["resultTimeoutMs"].as<uint32_t>();
      if (c.containsKey("mqttChunkSize")) g_cfg.mqttImageChunkSize = (uint16_t)c["mqttChunkSize"].as<int>();
      if (c.containsKey("mirror")) g_cfg.mirrorHorizontal = c["mirror"].as<bool>();
    }
  }
}

static void mqttCallback(char* topic, uint8_t* payload, unsigned int length) {
  if (length == 0) return;

  StaticJsonDocument<768> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) return;

  if (strcmp(topic, g_topicResult) == 0) {
    const char* name = doc["name"] | "";
    const char* error = doc["error"] | "";
    xSemaphoreTake(g_stateMutex, portMAX_DELAY);
    if (name && strlen(name)) {
      strlcpy(g_app.lastResult, name, sizeof(g_app.lastResult));
      g_app.lastResultUnknown = false;
    } else {
      strlcpy(g_app.lastResult, (error && strlen(error)) ? "Unknown" : "Unknown", sizeof(g_app.lastResult));
      g_app.lastResultUnknown = true;
    }
    g_app.tResultMs = millis();
    g_app.resultAvailable = true;
    xSemaphoreGive(g_stateMutex);
    xEventGroupSetBits(g_eventGroup, BIT_RESULT_RX);
    return;
  }

  if (strcmp(topic, g_topicCmd) == 0 || strcmp(topic, g_topicCmdAll) == 0) {
    handleIncomingCommand(doc);
    return;
  }
}

static bool mqttEnsureConnected(uint32_t nowMs) {
  static uint32_t nextAttemptMs = 0;
  static uint32_t backoffMs = 1000;

  if (g_mqtt.connected()) return true;
  if (nowMs < nextAttemptMs) return false;

  char clientId[64];
  snprintf(clientId, sizeof(clientId), "ESP32CAM-%s", g_deviceId);

  bool ok = false;
  if (MQTT_USERNAME && MQTT_USERNAME[0]) {
    ok = g_mqtt.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD, g_topicStatus, 0, true, "offline");
  } else {
    ok = g_mqtt.connect(clientId, g_topicStatus, 0, true, "offline");
  }

  if (ok) {
    backoffMs = 1000;
    nextAttemptMs = nowMs + 1000;
    xEventGroupSetBits(g_eventGroup, BIT_MQTT_OK);
    g_mqtt.subscribe(g_topicCmd);
    g_mqtt.subscribe(g_topicCmdAll);
    g_mqtt.subscribe(g_topicResult);
    mqttPublishStatus("online");
    return true;
  }

  xEventGroupClearBits(g_eventGroup, BIT_MQTT_OK);
  nextAttemptMs = nowMs + backoffMs;
  backoffMs = (backoffMs < 30000) ? (backoffMs * 2) : 30000;
  return false;
}

// ==================== CAMERA MODULE ====================
static bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5;  config.pin_d1 = 18; config.pin_d2 = 19; config.pin_d3 = 21;
  config.pin_d4 = 36; config.pin_d5 = 39; config.pin_d6 = 34; config.pin_d7 = 35;
  config.pin_xclk = 0;
  config.pin_pclk = 22;
  config.pin_vsync = 25;
  config.pin_href = 23;
  config.pin_sccb_sda = 26;
  config.pin_sccb_scl = 27;
  config.pin_pwdn = 32;
  config.pin_reset = -1;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  bool hasPsram = psramFound();
  config.fb_location = hasPsram ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.frame_size = g_cfg.streamFrameSize;
  config.jpeg_quality = g_cfg.jpegQualityStream;
  config.fb_count = hasPsram ? 2 : 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) return false;

  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_framesize(s, g_cfg.streamFrameSize);
    s->set_quality(s, g_cfg.jpegQualityStream);
    s->set_hmirror(s, g_cfg.mirrorHorizontal ? 1 : 0);
  }
  return true;
}

static bool cameraSetStreamMode() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return false;
  s->set_framesize(s, g_cfg.streamFrameSize);
  s->set_quality(s, g_cfg.jpegQualityStream);
  s->set_hmirror(s, g_cfg.mirrorHorizontal ? 1 : 0);
  return true;
}

static bool cameraSetCaptureMode() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return false;
  s->set_framesize(s, g_cfg.captureFrameSize);
  s->set_quality(s, g_cfg.jpegQualityCapture);
  s->set_hmirror(s, g_cfg.mirrorHorizontal ? 1 : 0);
  return true;
}

// ==================== HTTP MODULE ====================
static bool uploadFrameHttp(camera_fb_t* fb) {
  if (!fb || !fb->buf || fb->len == 0) return false;

  g_https.setInsecure();
  g_https.setTimeout(8000);

  HTTPClient http;
  bool ok = http.begin(g_https, SERVER_URL);
  if (!ok) {
    http.end();
    return false;
  }

  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-API-Key", API_KEY);
  http.addHeader("X-Class-Name", CLASS_NAME);
  http.addHeader("X-Device-Id", g_deviceId);

  int code = http.POST(fb->buf, fb->len);
  http.end();
  return (code > 0 && code < 300);
}

static void publishCaptureMeta(size_t jpegLen) {
  if (!g_mqtt.connected()) return;
  AppSharedState s = getStateSnapshot();
  StaticJsonDocument<384> doc;
  doc["id"] = g_deviceId;
  doc["len"] = (uint32_t)jpegLen;
  doc["rssi"] = WiFi.RSSI();
  doc["t_button_ms"] = s.tButtonMs;
  doc["t_capture_ms"] = s.tCaptureMs;
  doc["t_upload_done_ms"] = s.tUploadDoneMs;
  char out[512];
  size_t n = serializeJson(doc, out, sizeof(out));
  g_mqtt.publish(g_topicMeta, (const uint8_t*)out, n, false);
}

static void publishImageChunks(camera_fb_t* fb) {
  if (!fb || !fb->buf || fb->len == 0) return;
  if (!g_mqtt.connected()) return;
  if (!g_cfg.publishImageChunks) return;

  uint16_t chunkSize = g_cfg.mqttImageChunkSize;
  if (chunkSize < 256) chunkSize = 256;
  if (chunkSize > 1400) chunkSize = 1400;

  uint16_t total = (uint16_t)((fb->len + chunkSize - 1) / chunkSize);
  uint8_t packet[1406];
  for (uint16_t seq = 0; seq < total; seq++) {
    size_t offset = (size_t)seq * chunkSize;
    size_t len = fb->len - offset;
    if (len > chunkSize) len = chunkSize;

    packet[0] = (uint8_t)(seq & 0xFF);
    packet[1] = (uint8_t)(seq >> 8);
    packet[2] = (uint8_t)(total & 0xFF);
    packet[3] = (uint8_t)(total >> 8);
    packet[4] = (uint8_t)(len & 0xFF);
    packet[5] = (uint8_t)(len >> 8);
    memcpy(packet + 6, fb->buf + offset, len);

    if (!g_mqtt.publish(g_topicImage, packet, (unsigned)(len + 6), false)) break;
    g_mqtt.loop();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

// ==================== BUTTON MODULE (ISR + DEBOUNCE) ====================
static void IRAM_ATTR onButtonIsr() {
  static uint32_t lastTick = 0;
  uint32_t nowTick = xTaskGetTickCountFromISR();
  if (nowTick - lastTick < pdMS_TO_TICKS(200)) return;
  lastTick = nowTick;

  BaseType_t higherWoken = pdFALSE;
  xEventGroupSetBitsFromISR(g_eventGroup, BIT_BTN_CAPTURE, &higherWoken);
  if (higherWoken) portYIELD_FROM_ISR();
}

// ==================== TASKS ====================
static void taskNetwork(void* pv) {
  (void)pv;
  uint32_t lastTelemetryMs = 0;
  uint32_t staAttemptStartMs = millis();
  uint32_t lastStaBeginMs = 0;
  bool captureWorkPending = false;

  for (;;) {
    uint32_t now = millis();
    wifiUpdateStatusBits();
    EventBits_t bits = xEventGroupGetBits(g_eventGroup);
    bool wifiOk = (bits & BIT_WIFI_OK);

    if (!wifiOk) {
      if (now - lastStaBeginMs > 5000) {
        wifiStartSta();
        lastStaBeginMs = now;
      }

      if (!(bits & BIT_AP_MODE) && (now - staAttemptStartMs > 30000)) {
        wifiStartApFallback();
        staAttemptStartMs = now;
      }
    } else {
      staAttemptStartMs = now;
    }

    g_web.handleClient();

    if (wifiOk) {
      if (bits & BIT_AP_MODE) {
        WiFi.softAPdisconnect(true);
        xEventGroupClearBits(g_eventGroup, BIT_AP_MODE);
      }
      mqttEnsureConnected(now);
      if (g_mqtt.connected()) g_mqtt.loop();

      if (now - lastTelemetryMs > 5000) {
        mqttPublishTelemetry();
        lastTelemetryMs = now;
      }
    }

    if (!captureWorkPending) {
      AppSharedState s = getStateSnapshot();
      if (s.state == APP_CAPTURING) captureWorkPending = true;
    }

    if (captureWorkPending) {
      AppSharedState s = getStateSnapshot();
      if (s.state != APP_CAPTURING) {
        captureWorkPending = false;
      } else {
        setState(APP_UPLOADING);

        xSemaphoreTake(g_stateMutex, portMAX_DELAY);
        g_app.tCaptureMs = now;
        bool flashOn = g_app.flashEnabled;
        xSemaphoreGive(g_stateMutex);

        if (flashOn) digitalWrite(FLASH_PIN, HIGH);
        vTaskDelay(pdMS_TO_TICKS(120));

        cameraSetCaptureMode();
        camera_fb_t* fb = esp_camera_fb_get();
        cameraSetStreamMode();

        if (flashOn) digitalWrite(FLASH_PIN, LOW);

        if (!fb) {
          setState(APP_STREAMING);
          captureWorkPending = false;
        } else {
          bool ok = false;
          if (wifiOk) ok = uploadFrameHttp(fb);

          xSemaphoreTake(g_stateMutex, portMAX_DELAY);
          g_app.tUploadDoneMs = millis();
          xSemaphoreGive(g_stateMutex);

          if (wifiOk && g_mqtt.connected()) {
            publishCaptureMeta(fb->len);
            publishImageChunks(fb);
          }
          esp_camera_fb_return(fb);

          if (ok) {
            setState(APP_WAITING_RESULT);
          } else {
            setState(APP_STREAMING);
          }
          captureWorkPending = false;
        }
      }
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

static void taskApp(void* pv) {
  (void)pv;
  for (;;) {
    EventBits_t bits = xEventGroupWaitBits(
      g_eventGroup,
      BIT_BTN_CAPTURE | BIT_RESULT_RX,
      pdTRUE,
      pdFALSE,
      pdMS_TO_TICKS(50)
    );

    AppSharedState s = getStateSnapshot();
    uint32_t now = millis();

    if (g_pendingReboot) {
      vTaskDelay(pdMS_TO_TICKS(80));
      ESP.restart();
    }

    bool wifiOk = ((xEventGroupGetBits(g_eventGroup) & BIT_WIFI_OK) != 0);
    if (wifiOk && s.state == APP_CONNECTING) {
      setState(APP_STREAMING);
      s = getStateSnapshot();
    } else if (!wifiOk && s.state == APP_STREAMING) {
      setState(APP_CONNECTING);
      s = getStateSnapshot();
    }

    if (bits & BIT_BTN_CAPTURE) {
      if (s.state == APP_STREAMING) {
        xSemaphoreTake(g_stateMutex, portMAX_DELAY);
        g_app.tButtonMs = now;
        g_app.tResultMs = 0;
        g_app.lastResult[0] = '\0';
        g_app.lastResultUnknown = false;
        g_app.resultAvailable = false;
        xSemaphoreGive(g_stateMutex);
        setState(APP_CAPTURING);
      }
    }

    if (s.state == APP_WAITING_RESULT) {
      bool hasResult = false;
      xSemaphoreTake(g_stateMutex, portMAX_DELAY);
      hasResult = g_app.resultAvailable;
      xSemaphoreGive(g_stateMutex);

      if ((bits & BIT_RESULT_RX) || hasResult) {
        setState(APP_SHOWING_RESULT);
      } else if (now - s.stateEnterMs > g_cfg.resultTimeoutMs) {
        xSemaphoreTake(g_stateMutex, portMAX_DELAY);
        strlcpy(g_app.lastResult, "Timeout", sizeof(g_app.lastResult));
        g_app.lastResultUnknown = true;
        g_app.resultAvailable = true;
        xSemaphoreGive(g_stateMutex);
        setState(APP_SHOWING_RESULT);
      }
    }

    if (s.state == APP_SHOWING_RESULT) {
      if (now - s.stateEnterMs > g_cfg.showResultMs) {
        setState(APP_STREAMING);
      }
    }

    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

// ==================== UI TASK ====================
static void taskUi(void* pv) {
  (void)pv;
  const TickType_t period = pdMS_TO_TICKS(120);
  TickType_t lastWake = xTaskGetTickCount();
  AppState lastState = APP_ERROR;

  for (;;) {
    AppSharedState s = getStateSnapshot();
    if (s.state != lastState) {
      lastState = s.state;
      if (s.state == APP_CONNECTING) {
        tft.fillScreen(BLACK);
        displayMessage("Connecting...", YELLOW, BLACK);
      } else if (s.state == APP_UPLOADING) {
        tft.fillRect(0, 0, 240, 40, GRADIENT_2);
        tft.drawRect(0, 0, 240, 40, ACCENT_BLUE);
        tft.setCursor(50, 10);
        tft.setTextSize(2);
        tft.setTextColor(WHITE);
        tft.print("DANG GUI...");
      } else if (s.state == APP_WAITING_RESULT) {
        displayMessage("Waiting...", YELLOW, BLACK);
      } else if (s.state == APP_SHOWING_RESULT) {
        String cleanName = utf8ToAscii(String(s.lastResult));
        if (cleanName == "Timeout") cleanName = "Unknown";
        drawResultScreenModern(cleanName);
      } else if (s.state == APP_STREAMING) {
        tft.fillScreen(BLACK);
      }
    }

    if (s.state == APP_STREAMING) {
      camera_fb_t* fb = esp_camera_fb_get();
      if (fb) {
        TJpgDec.drawJpg(0, 0, fb->buf, fb->len);
        esp_camera_fb_return(fb);
      }
    }

    vTaskDelayUntil(&lastWake, period);
  }
}

// ==================== SERIAL COMMAND (TÙY CHỌN) ====================
static void serialPoll() {
  static char buf[160];
  static size_t idx = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[idx] = '\0';
      idx = 0;

      if (strncmp(buf, "CAPTURE", 7) == 0) {
        xEventGroupSetBits(g_eventGroup, BIT_BTN_CAPTURE);
      } else if (strncmp(buf, "WIFI ", 5) == 0) {
        char ssid[64] = {0};
        char pass[64] = {0};
        int n = sscanf(buf + 5, "%63s %63s", ssid, pass);
        if (n >= 1) wifiApplyNewCredentials(ssid, (n >= 2) ? pass : "");
      } else if (strncmp(buf, "STATUS", 6) == 0) {
        AppSharedState s = getStateSnapshot();
        Serial.printf("state=%u wifi=%d mqtt=%d rssi=%d heap=%u psram=%u\n",
                      (unsigned)s.state,
                      (int)((xEventGroupGetBits(g_eventGroup) & BIT_WIFI_OK) != 0),
                      (int)((xEventGroupGetBits(g_eventGroup) & BIT_MQTT_OK) != 0),
                      WiFi.RSSI(),
                      (unsigned)ESP.getFreeHeap(),
                      (unsigned)ESP.getFreePsram());
      }
      continue;
    }

    if (idx + 1 < sizeof(buf)) buf[idx++] = c;
  }
}

// ==================== SETUP/LOOP ====================
void setup() {
  Serial.begin(115200);
  Serial.println();

  uint64_t mac = ESP.getEfuseMac();
  snprintf(g_deviceId, sizeof(g_deviceId), "%02X%02X%02X",
           (uint8_t)(mac >> 16), (uint8_t)(mac >> 8), (uint8_t)(mac));
  buildTopics();

  g_eventGroup = xEventGroupCreate();
  g_stateMutex = xSemaphoreCreateMutex();

  // Load configuration from NVS
  loadConfigFromNvs();

  bus.begin(40000000);
  tft.begin();
  tft.setRotation(2);
  tft.fillScreen(BLACK);
  TJpgDec.setJpgScale(2);
  TJpgDec.setCallback(send_to_tft);

  pinMode(FLASH_PIN, OUTPUT);
  digitalWrite(FLASH_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  
  // Ensure GPIO ISR service is only installed once
  if (!g_gpio_isr_installed) {
    gpio_install_isr_service(0);
    g_gpio_isr_installed = true;
  }
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), onButtonIsr, FALLING);

  loadWifiFromNvs();
  webSetupRoutes();
  wifiStartSta();

  if (MQTT_USE_TLS) {
    if (MQTT_TLS_INSECURE) {
      g_mqttTls.setInsecure();
    } else if (MQTT_ROOT_CA && MQTT_ROOT_CA[0]) {
      g_mqttTls.setCACert(MQTT_ROOT_CA);
    } else {
      g_mqttTls.setInsecure();
    }
    g_mqttTls.setTimeout(8000);
    g_mqtt.setClient(g_mqttTls);
  } else {
    g_mqtt.setClient(g_mqttTcp);
  }

  g_mqtt.setServer(MQTT_HOST, MQTT_PORT);
  g_mqtt.setCallback(mqttCallback);
  g_mqtt.setSocketTimeout(5);
  g_mqtt.setKeepAlive(30);
  g_mqtt.setBufferSize(2048);

  if (!initCamera()) {
    setState(APP_ERROR);
    displayMessage("Cam Error", RED, BLACK);
  } else {
    setState(APP_CONNECTING);
  }

  xTaskCreatePinnedToCore(taskNetwork, "net", 8192, nullptr, 3, &g_taskNet, 0);
  xTaskCreatePinnedToCore(taskApp, "app", 4096, nullptr, 2, &g_taskApp, 1);
  xTaskCreatePinnedToCore(taskUi, "ui", 8192, nullptr, 1, &g_taskUi, 1);
}

void loop() {
  serialPoll();
  vTaskDelay(pdMS_TO_TICKS(20));
}
