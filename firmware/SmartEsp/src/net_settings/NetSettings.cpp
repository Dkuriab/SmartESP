#include "NetSettings.h"

namespace {

constexpr const char* NAMESPACE = "net";
constexpr const char* KEY_SSID = "ssid";
constexpr const char* KEY_PASSWORD = "pass";
constexpr const char* KEY_CORE = "core";

}  // namespace

bool NetSettings::begin() {
  ready_ = prefs_.begin(NAMESPACE, false);
  if (!ready_) {
    Serial.println("net_settings: NVS недоступен — сеть не сохранится");
  }
  return ready_;
}

bool NetSettings::loadWifi(WifiCredentials& out) {
  memset(&out, 0, sizeof(out));
  if (!ready_ || !prefs_.isKey(KEY_SSID)) {
    return false;
  }
  prefs_.getString(KEY_SSID, out.ssid, sizeof(out.ssid));
  if (prefs_.isKey(KEY_PASSWORD)) {
    prefs_.getString(KEY_PASSWORD, out.password, sizeof(out.password));
  }
  return out.ssid[0] != '\0';
}

void NetSettings::saveWifi(const WifiCredentials& credentials) {
  if (!ready_ || credentials.ssid[0] == '\0') {
    return;
  }
  WifiCredentials saved;
  if (loadWifi(saved) && strcmp(saved.ssid, credentials.ssid) == 0 &&
      strcmp(saved.password, credentials.password) == 0) {
    return;
  }
  prefs_.putString(KEY_SSID, credentials.ssid);
  prefs_.putString(KEY_PASSWORD, credentials.password);
  Serial.printf("net_settings: сохранена сеть %s\n", credentials.ssid);
}

void NetSettings::loadCoreId(char* out, size_t size) {
  if (size == 0) {
    return;
  }
  out[0] = '\0';
  if (ready_ && prefs_.isKey(KEY_CORE)) {
    prefs_.getString(KEY_CORE, out, size);
  }
}

void NetSettings::saveCoreId(const char* id) {
  if (!ready_ || !id) {
    return;
  }
  char saved[33];
  loadCoreId(saved, sizeof(saved));
  if (strcmp(saved, id) == 0) {
    return;
  }
  prefs_.putString(KEY_CORE, id);
  Serial.printf("net_settings: своё ядро %s\n", id);
}
