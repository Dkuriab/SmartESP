#pragma once

// Внутренний файл модуля core_finder: когда искать ядро.
// Ищем, только пока есть Wi-Fi и нет связи с ядром. Самый первый поиск — сразу; после
// потери связи — через firstMs (server_link сперва сам переподключается к прежнему адресу).
// Дальше паузы растут: 5, 10, 20, 30 с (предел maxMs). Время — millis(), переполнение
// не мешает. Чистая логика без Arduino — тестируется на ноутбуке.

#include <stdint.h>

class SearchTimer {
 public:
  explicit SearchTimer(uint32_t firstMs = 5000, uint32_t maxMs = 30000);

  // Шаг (из задачи поиска): true — пора искать; вызов отмечает поиск.
  bool due(uint32_t nowMs, bool wifiConnected, bool serverConnected);

 private:
  uint32_t firstMs_;
  uint32_t maxMs_;
  bool waiting_ = false;   // нужен поиск (Wi-Fi есть, ядра нет)
  bool searched_ = false;  // поиск уже был
  uint32_t lastMs_ = 0;
  uint32_t delayMs_ = 0;
};
