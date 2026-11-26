#include "WifiLink.h"

#include <WiFi.h>
#include "esp_mac.h"
#include "esp_wifi.h"

namespace {

constexpr uint32_t RESCAN_MS = 30000;      // список сетей старше — сканировать заново
constexpr uint32_t JOIN_TIMEOUT_MS = 20000;  // сеть с телефона не подключилась — сказать об этом
constexpr uint32_t SCAN_TRY_MS = 1000;     // сканирование не запустилось (идёт подключение) — повтор
constexpr uint32_t SERVE_STEP_MS = 5;
constexpr uint32_t IDLE_STEP_MS = 200;
constexpr const char* HTML = "text/html; charset=utf-8";
constexpr const char* TEXT = "text/plain; charset=utf-8";

// Сеть, которую хранит библиотека Wi-Fi (её записала прошивка 0.7.0). false — нет.
bool readLibraryNetwork(WifiCredentials& out) {
  wifi_config_t conf{};
  if (esp_wifi_get_config(WIFI_IF_STA, &conf) != ESP_OK || conf.sta.ssid[0] == 0) {
    return false;
  }
  memset(&out, 0, sizeof(out));
  memcpy(out.ssid, conf.sta.ssid, sizeof(out.ssid) - 1);  // 32 байта, нуля на конце может не быть
  memcpy(out.password, conf.sta.password, sizeof(out.password) - 1);
  return true;
}

}  // namespace

bool WifiLink::begin(const WifiLinkConfig& config, const WifiCredentials& saved) {
  config_ = config;
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  snprintf(hostname_, sizeof(hostname_), "%s-%02x%02x", config_.hostPrefix, mac[4], mac[5]);
  snprintf(apName_, sizeof(apName_), "%s-%02x%02x", config_.apPrefix, mac[4], mac[5]);
  plan_ = LinkPlan(config_.portalAfterMs);

  WiFi.setHostname(hostname_);  // до запуска станции: имя для DHCP
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(false);  // переподключением управляет loop()

  network_ = saved;
  network_.ssid[sizeof(network_.ssid) - 1] = '\0';
  network_.password[sizeof(network_.password) - 1] = '\0';
  if (network_.ssid[0]) {
    Serial.printf("wifi: сохранённая сеть %s\n", network_.ssid);
  } else if (readLibraryNetwork(network_)) {
    Serial.printf("wifi: своей сети нет, пробую сеть прошлой прошивки %s\n", network_.ssid);
  } else {
    Serial.println("wifi: сети нет — точка настройки");
  }
  plan_.begin(millis(), network_.ssid[0] != '\0');
  return xTaskCreatePinnedToCore(taskEntry, "wifi_portal", 8192, this, 1, nullptr, 0) == pdPASS;
}

void WifiLink::loop() {
  takeSubmitted();
  const uint32_t now = millis();
  const bool connected = isConnected();
  if (connected != connected_) {
    connected_ = connected;
    char text[sizeof(status_)];
    if (connected) {
      const String ip = WiFi.localIP().toString();
      Serial.printf("wifi: connected %s (%s)\n", ip.c_str(), network_.ssid);
      joined_ = network_;
      hasJoined_ = true;
      fromPortal_ = false;
      snprintf(text, sizeof(text), "Подключено к «%s», адрес колонки %s. Точка настройки скоро закроется.",
               network_.ssid, ip.c_str());
    } else {
      Serial.println("wifi: lost");
      snprintf(text, sizeof(text), "Нет связи с «%s», пробую снова…", network_.ssid);
    }
    if (connected || !fromPortal_) {  // сеть с телефона: «Подключаюсь…» до итога
      setStatus(text);
    }
  }
  if (fromPortal_ && !connected && now - submittedMs_ >= JOIN_TIMEOUT_MS) {
    fromPortal_ = false;
    char text[sizeof(status_)];
    snprintf(text, sizeof(text), "Не удаётся подключиться к «%s». Проверьте пароль и сохраните снова.",
             network_.ssid);
    setStatus(text);
  }
  if (plan_.update(now, connected)) {
    connect();
  }
  if (plan_.portalOpen() != portal_) {
    openPortal(plan_.portalOpen());
  }
  if (portal_) {
    pollScan();
  }
}

bool WifiLink::isConnected() const {
  return WiFi.status() == WL_CONNECTED;
}

const char* WifiLink::hostname() const {
  return hostname_;
}

bool WifiLink::pollJoined(WifiCredentials& out) {
  if (!hasJoined_) {
    return false;
  }
  out = joined_;
  hasJoined_ = false;
  return true;
}

void WifiLink::connect() {
  if (scanRunning_) {
    return;  // сканирование и подключение мешают друг другу; следующая попытка — по плану
  }
  WiFi.disconnect();
  WiFi.begin(network_.ssid, network_.password[0] ? network_.password : nullptr);
}

void WifiLink::openPortal(bool open) {
  portal_ = open;
  if (open) {
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP(apName_);  // открытая точка: пароль Wi-Fi вводится на её странице
    Serial.printf("wifi: точка настройки %s, http://%s\n", apName_, WiFi.softAPIP().toString().c_str());
    char text[sizeof(status_)];
    if (network_.ssid[0]) {
      snprintf(text, sizeof(text), "Не удаётся подключиться к «%s». Выберите сеть заново или подождите.",
               network_.ssid);
    } else {
      text[0] = '\0';
    }
    setStatus(text);
    taskENTER_CRITICAL(&lock_);
    scanRequest_ = true;
    scanning_ = true;
    taskEXIT_CRITICAL(&lock_);
    serveWanted_ = true;
  } else {
    serveWanted_ = false;
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    Serial.println("wifi: точка настройки закрыта");
  }
}

// Асинхронное сканирование по просьбе страницы: запуск и сбор результата, без ожидания.
void WifiLink::pollScan() {
  if (!scanRunning_) {
    taskENTER_CRITICAL(&lock_);
    const bool requested = scanRequest_;
    taskEXIT_CRITICAL(&lock_);
    if (!requested || millis() - lastScanTryMs_ < SCAN_TRY_MS) {
      return;
    }
    lastScanTryMs_ = millis();
    if (WiFi.scanNetworks(true, false) == WIFI_SCAN_RUNNING) {
      scanRunning_ = true;
      taskENTER_CRITICAL(&lock_);
      scanRequest_ = false;
      taskEXIT_CRITICAL(&lock_);
    }
    return;
  }
  const int16_t found = WiFi.scanComplete();
  if (found == WIFI_SCAN_RUNNING) {
    return;
  }
  scanRunning_ = false;
  ScanEntry nets[MAX_NETS] = {};
  size_t count = 0;
  for (int16_t i = 0; i < found && count < MAX_NETS; i++) {
    ScanEntry& net = nets[count++];
    WiFi.SSID(i).toCharArray(net.ssid, sizeof(net.ssid));
    net.rssi = static_cast<int8_t>(WiFi.RSSI(i));
    net.open = WiFi.encryptionType(i) == WIFI_AUTH_OPEN;
  }
  WiFi.scanDelete();
  count = mergeScan(nets, count);
  taskENTER_CRITICAL(&lock_);
  memcpy(nets_, nets, sizeof(nets_));
  netCount_ = count;
  scanning_ = false;
  scannedMs_ = millis();
  taskEXIT_CRITICAL(&lock_);
}

// Сеть с телефона: пробовать сразу (прежняя связь рвётся), паузы — с начала.
void WifiLink::takeSubmitted() {
  WifiCredentials submitted;
  taskENTER_CRITICAL(&lock_);
  const bool has = hasSubmitted_;
  hasSubmitted_ = false;
  submitted = submitted_;
  taskEXIT_CRITICAL(&lock_);
  if (!has) {
    return;
  }
  network_ = submitted;
  fromPortal_ = true;
  submittedMs_ = millis();
  Serial.printf("wifi: сеть с телефона %s\n", network_.ssid);
  if (scanRunning_) {  // подключение важнее списка сетей
    esp_wifi_scan_stop();
    WiFi.scanDelete();
    scanRunning_ = false;
    taskENTER_CRITICAL(&lock_);
    scanning_ = false;
    taskEXIT_CRITICAL(&lock_);
  }
  connect();
  plan_.setNetwork(submittedMs_);
}

void WifiLink::setStatus(const char* text) {
  taskENTER_CRITICAL(&lock_);
  strncpy(status_, text, sizeof(status_) - 1);
  status_[sizeof(status_) - 1] = '\0';
  taskEXIT_CRITICAL(&lock_);
}

// ---------- задача портала: DNS и страница ----------

void WifiLink::taskEntry(void* self) {
  static_cast<WifiLink*>(self)->run();
}

void WifiLink::run() {
  server_.on("/", HTTP_GET, [this]() { handleRoot(); });
  server_.on("/save", HTTP_POST, [this]() { handleSave(); });
  server_.on("/status", HTTP_GET, [this]() { handleStatus(); });
  server_.onNotFound([this]() { handleOther(); });
  for (;;) {
    const bool wanted = serveWanted_;
    if (wanted != serving_) {
      serve(wanted);
    }
    if (serving_) {
      dns_.processNextRequest();
      server_.handleClient();
      vTaskDelay(pdMS_TO_TICKS(SERVE_STEP_MS));
    } else {
      vTaskDelay(pdMS_TO_TICKS(IDLE_STEP_MS));
    }
  }
}

void WifiLink::serve(bool on) {
  serving_ = on;
  if (on) {
    dns_.setErrorReplyCode(DNSReplyCode::NoError);
    dns_.start(53, "*", WiFi.softAPIP());  // любое имя → колонка: телефон откроет страницу сам
    server_.begin();
  } else {
    server_.stop();
    dns_.stop();
  }
}

void WifiLink::handleRoot() {
  ScanEntry nets[MAX_NETS];
  char status[sizeof(status_)];
  const bool rescan = server_.hasArg("scan");
  taskENTER_CRITICAL(&lock_);
  if (rescan || (!scanning_ && millis() - scannedMs_ >= RESCAN_MS)) {
    scanRequest_ = true;
    scanning_ = true;
  }
  const bool scanning = scanning_;
  const size_t count = netCount_;
  memcpy(nets, nets_, sizeof(nets));
  memcpy(status, status_, sizeof(status));
  taskEXIT_CRITICAL(&lock_);
  const std::string page = setupPage(apName_, nets, count, scanning, status);
  server_.sendHeader("Cache-Control", "no-store");
  server_.send_P(200, HTML, page.data(), page.size());
}

void WifiLink::handleSave() {
  WifiCredentials credentials{};
  const String ssid = server_.arg("ssid");
  const String password = server_.arg("password");
  const FormError error = checkCredentials(ssid.c_str(), password.c_str(), credentials);
  if (error != FormError::None) {
    ScanEntry nets[MAX_NETS];
    taskENTER_CRITICAL(&lock_);
    const size_t count = netCount_;
    memcpy(nets, nets_, sizeof(nets));
    taskEXIT_CRITICAL(&lock_);
    const std::string page = setupPage(apName_, nets, count, false, formErrorText(error));
    server_.send_P(400, HTML, page.data(), page.size());
    return;
  }
  char text[sizeof(status_)];
  snprintf(text, sizeof(text), "Подключаюсь к «%s»…", credentials.ssid);
  taskENTER_CRITICAL(&lock_);
  submitted_ = credentials;
  hasSubmitted_ = true;
  strncpy(status_, text, sizeof(status_) - 1);
  taskEXIT_CRITICAL(&lock_);
  const std::string page = savedPage(credentials.ssid);
  server_.send_P(200, HTML, page.data(), page.size());
}

void WifiLink::handleStatus() {
  char status[sizeof(status_)];
  taskENTER_CRITICAL(&lock_);
  memcpy(status, status_, sizeof(status));
  taskEXIT_CRITICAL(&lock_);
  server_.sendHeader("Cache-Control", "no-store");
  server_.send(200, TEXT, status);
}

// Проверки «есть ли интернет» телефонов и любые другие адреса → на страницу настройки.
void WifiLink::handleOther() {
  server_.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/", true);
  server_.send(302, TEXT, "");
}
