#pragma once

// Внутренний файл модуля wifi_link: когда пробовать подключиться и когда нужна точка настройки.
// Паузы между попытками 5, 10, 20, 30 с (дальше по 30 с). Сети нет — точка сразу; есть, но
// portalAfterMs без связи — точка, а сеть пробуется дальше. Связь продержалась lingerMs —
// точка закрывается (телефон успевает увидеть «Подключено»). Время — millis(), переполнение
// не мешает. Чистая логика без Arduino — тестируется на ноутбуке.

#include <stdint.h>

class LinkPlan {
 public:
  LinkPlan(uint32_t portalAfterMs = 120000, uint32_t lingerMs = 15000, uint32_t firstRetryMs = 5000,
           uint32_t maxRetryMs = 30000);

  // Начало работы: nowMs — millis(), hasNetwork — есть ли сеть для подключения.
  void begin(uint32_t nowMs, bool hasNetwork);

  // Новая сеть (с портала), первую попытку вызывающий сделал сам: следующая — через паузу,
  // паузы — с начала. Точка остаётся, пока не будет связи.
  void setNetwork(uint32_t nowMs);

  // Шаг из loop(): connected — есть ли связь. true — пора (пере)подключаться.
  bool update(uint32_t nowMs, bool connected);

  // Нужна ли сейчас точка настройки.
  bool portalOpen() const;

 private:
  uint32_t portalAfterMs_;
  uint32_t lingerMs_;
  uint32_t firstRetryMs_;
  uint32_t maxRetryMs_;
  bool hasNetwork_ = false;
  bool portal_ = false;
  bool connected_ = false;
  bool attemptNow_ = false;
  uint32_t retryMs_ = 0;
  uint32_t lastAttemptMs_ = 0;
  uint32_t downSinceMs_ = 0;       // с какого момента нет связи
  uint32_t connectedSinceMs_ = 0;  // с какого момента связь есть
};
