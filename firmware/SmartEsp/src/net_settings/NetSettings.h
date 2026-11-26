#pragma once

// net_settings — настройки сети во флеше колонки (NVS, пространство «net»): сеть Wi-Fi,
// заданная с телефона (или перенесённая из 0.7.0), и id ядра, с которым колонка работала
// в прошлый раз. Пишет во флеш только изменившееся. Вызывать из loop() (запись — миллисекунды,
// и только когда что-то сменилось).

#include <Arduino.h>
#include <Preferences.h>
#include "../common/Types.h"

class NetSettings {
 public:
  // Открывает пространство NVS. false — флеш недоступен (сеть не сохранится).
  bool begin();

  // Сохранённая сеть в out. false — её нет (out — пустой ssid).
  bool loadWifi(WifiCredentials& out);

  // Сохраняет сеть, если она отличается от сохранённой. Пустой ssid — не сохраняет.
  void saveWifi(const WifiCredentials& credentials);

  // id ядра в out (size байт, с нулём на конце); нет — пустая строка.
  void loadCoreId(char* out, size_t size);

  // Сохраняет id ядра, если он отличается от сохранённого.
  void saveCoreId(const char* id);

 private:
  Preferences prefs_;
  bool ready_ = false;
};
