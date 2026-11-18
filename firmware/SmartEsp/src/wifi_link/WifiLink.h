#pragma once

// wifi_link — подключение к Wi-Fi и переподключение.
// Ничего не ждёт: begin() только запускает подключение, loop() следит за ним.

#include <Arduino.h>

class WifiLink {
 public:
  // Режим станции, без энергосбережения (иначе провалы 100–300 мс), запуск подключения.
  bool begin(const char* ssid, const char* password);

  // Переподключение с паузами 1, 2, 4 … 30 с. Вызывать из loop().
  void loop();

  bool isConnected() const;

 private:
  const char* ssid_ = nullptr;
  const char* password_ = nullptr;
  bool wasConnected_ = false;
  uint32_t retryDelayMs_ = 1000;
  uint32_t lastAttemptMs_ = 0;
};
