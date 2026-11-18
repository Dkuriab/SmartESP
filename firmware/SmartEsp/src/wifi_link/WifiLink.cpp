#include "WifiLink.h"

#include <WiFi.h>

namespace {

constexpr uint32_t FIRST_RETRY_MS = 1000;
constexpr uint32_t MAX_RETRY_MS = 30000;

}  // namespace

bool WifiLink::begin(const char* ssid, const char* password) {
  ssid_ = ssid;
  password_ = password;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(false);  // переподключением управляет loop()
  WiFi.begin(ssid_, password_);
  lastAttemptMs_ = millis();
  return true;
}

void WifiLink::loop() {
  const bool connected = isConnected();
  if (connected != wasConnected_) {
    wasConnected_ = connected;
    if (connected) {
      Serial.printf("wifi: connected %s\n", WiFi.localIP().toString().c_str());
      retryDelayMs_ = FIRST_RETRY_MS;
    } else {
      Serial.println("wifi: lost");
      lastAttemptMs_ = millis();
    }
  }
  if (connected || millis() - lastAttemptMs_ < retryDelayMs_) {
    return;
  }
  lastAttemptMs_ = millis();
  retryDelayMs_ = min(retryDelayMs_ * 2, MAX_RETRY_MS);
  WiFi.disconnect();
  WiFi.begin(ssid_, password_);
}

bool WifiLink::isConnected() const {
  return WiFi.status() == WL_CONNECTED;
}
