#pragma once

// core_finder — поиск ядра в сети: ядро объявляет службу _smartesp._tcp (Bonjour/mDNS),
// колонка ищет её и отдаёт адрес (pollFound). Ещё модуль объявляет имя колонки в сети
// (hostname.local). Запрос mDNS ждёт ответа до секунд, поэтому поиск — в своей задаче
// FreeRTOS; loop() только передаёт состояние связи и забирает результат.
// Ищет, пока есть Wi-Fi и нет связи с ядром: сразу, затем с паузами 5, 10, 20, 30 с.
// Несколько ядер — то, с которым колонка работала в прошлый раз (id из TXT); его нет
// три поиска подряд — первое найденное. Адрес — из подсети колонки (у Mac их бывает несколько).

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "../common/Types.h"
#include "CoreChoice.h"
#include "SearchTimer.h"

struct CoreFinderConfig {
  const char* hostname;           // имя колонки в сети (без .local), строка живёт всё время работы
  const char* preferredId = "";   // id своего ядра (сохранённый); пусто — нет
  uint32_t queryMs = 3000;        // сколько ждать ответов на запрос
};

class CoreFinder {
 public:
  // Запускает задачу поиска. false — нет памяти.
  bool begin(const CoreFinderConfig& config);

  // Есть ли Wi-Fi (станция подключена). Вызывать каждый loop().
  void setWifiConnected(bool connected);

  // Есть ли связь с ядром. Вызывать каждый loop().
  void setServerConnected(bool connected);

  // Найденное ядро (новый результат поиска), если есть. Отдать server_link, updater, stream_player.
  bool pollFound(CoreAddress& out);

  // id ядра, с которым только что установилась связь, если он не тот, что был своим.
  // Его сохраняют (net_settings): в следующий раз колонка предпочтёт это ядро.
  bool pollRemember(char* id, size_t size);

 private:
  static void taskEntry(void* self);
  void run();
  void search();
  void noteConnection(bool serverConnected);

  CoreFinderConfig config_{};
  QueueHandle_t found_ = nullptr;  // задача → loop(), длина 1 (новый результат заменяет старый)
  volatile bool wifiConnected_ = false;
  volatile bool serverConnected_ = false;

  char remember_[33] = {};  // доступ — под rememberLock_
  bool hasRemember_ = false;
  portMUX_TYPE rememberLock_ = portMUX_INITIALIZER_UNLOCKED;

  // Только задача поиска.
  CoreChoice choice_;
  SearchTimer timer_;
  char preferred_[33] = {};
  char offered_[33] = {};  // id последнего отданного ядра
  bool wasConnected_ = false;
  bool mdnsStarted_ = false;
};
