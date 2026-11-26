#pragma once

// wifi_link — подключение к Wi-Fi и точка настройки с телефона.
// Станция подключается к сохранённой сети и переподключается (паузы 5, 10, 20, 30 с).
// Своей сохранённой сети нет — сначала пробует сеть, которую хранит библиотека Wi-Fi
// (так работала прошивка 0.7.0), иначе сразу точка. Нет сети или 2 минуты без подключения —
// открытая точка «Kuzya-xxxx» (xxxx — конец MAC) со страницей настройки: телефон сам
// открывает её (все имена DNS ведут на колонку). Пока точка открыта, сеть пробуется дальше;
// подключилась — через 15 с точка закрывается. Сеть, к которой колонка подключилась,
// отдаёт pollJoined() — её сохраняют (net_settings).
// Ничего не ждёт: loop() только решает, что делать; страницу и DNS обслуживает своя
// задача FreeRTOS, сканирование сетей — асинхронное.

#include <Arduino.h>
#include <DNSServer.h>
#include <WebServer.h>
#include "freertos/FreeRTOS.h"
#include "../common/Types.h"
#include "LinkPlan.h"
#include "SetupForm.h"

struct WifiLinkConfig {
  const char* hostPrefix = "kuzya";  // имя в сети: kuzya-xxxx (.local — у core_finder)
  const char* apPrefix = "Kuzya";    // точка настройки: Kuzya-xxxx
  uint32_t portalAfterMs = 120000;   // столько без связи — и точка открывается
};

class WifiLink {
 public:
  // Станция без энергосбережения (иначе провалы 100–300 мс), имя хоста, первая попытка.
  // saved — своя сохранённая сеть (пустой ssid — нет). Задача портала.
  bool begin(const WifiLinkConfig& config, const WifiCredentials& saved);

  // Попытки подключения, точка настройки, сканирование, сеть с телефона. Вызывать из loop().
  void loop();

  bool isConnected() const;

  // Имя колонки в сети, «kuzya-xxxx». Готово после begin().
  const char* hostname() const;

  // Сеть, к которой колонка только что подключилась (её стоит сохранить), если есть.
  bool pollJoined(WifiCredentials& out);

 private:
  static constexpr size_t MAX_NETS = 24;

  static void taskEntry(void* self);
  void run();
  void serve(bool on);
  void handleRoot();
  void handleSave();
  void handleStatus();
  void handleOther();
  void connect();
  void openPortal(bool open);
  void pollScan();
  void takeSubmitted();
  void setStatus(const char* text);

  WifiLinkConfig config_{};
  LinkPlan plan_;
  WifiCredentials network_{};  // сеть, к которой подключаемся (только loop())
  char hostname_[24] = {};
  char apName_[24] = {};
  bool connected_ = false;     // только loop()
  bool portal_ = false;        // точка поднята (только loop())
  bool fromPortal_ = false;    // network_ пришла с телефона и ещё не подключалась
  uint32_t submittedMs_ = 0;
  bool scanRunning_ = false;   // только loop()
  uint32_t lastScanTryMs_ = 0;

  // Общее для loop() и задачи портала — под lock_.
  portMUX_TYPE lock_ = portMUX_INITIALIZER_UNLOCKED;
  volatile bool serveWanted_ = false;  // loop() → задача: точка поднята, обслуживать
  bool scanRequest_ = false;
  bool scanning_ = false;
  ScanEntry nets_[MAX_NETS] = {};
  size_t netCount_ = 0;
  uint32_t scannedMs_ = 0;
  WifiCredentials submitted_{};
  bool hasSubmitted_ = false;
  char status_[256] = {};
  WifiCredentials joined_{};  // только loop()
  bool hasJoined_ = false;

  // Только задача портала.
  WebServer server_{80};
  DNSServer dns_;
  bool serving_ = false;
};
