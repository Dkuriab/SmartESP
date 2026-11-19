#pragma once

// Признаки звука для модели слова (часть модуля wake_word, без Arduino —
// собирается и на ноутбуке в host-тестах). Микрофронтенд TFLite с теми же
// настройками, что у microWakeWord и pymicro-features: окно 30 мс, шаг 10 мс,
// 40 каналов 125–7500 Гц, шумоподавление, PCAN, логарифм.

#include <stddef.h>
#include <stdint.h>

class WakeFeatures {
 public:
  static constexpr size_t CHANNELS = 40;       // признаков в кадре
  static constexpr size_t STEP_SAMPLES = 160;  // шаг кадра: 10 мс при 16 кГц

  WakeFeatures() = default;
  WakeFeatures(const WakeFeatures&) = delete;
  WakeFeatures& operator=(const WakeFeatures&) = delete;
  ~WakeFeatures();

  // Готовит фронтенд (выделяет буферы). false — нет памяти.
  bool begin();

  // Берёт отсчёты (16 кГц, моно), пока не получится кадр признаков или не
  // кончится звук. frame — CHANNELS значений нового кадра (uint16, признак
  // float = значение × 0,0390625); ready — появился ли кадр.
  // Возвращает число взятых отсчётов: остаток подать следующим вызовом.
  size_t process(const int16_t* pcm, size_t samples, uint16_t* frame, bool& ready);

  // Квантует признак для входа модели int8: round(значение × 0,0390625 / scale)
  // + zeroPoint, с ограничением −128..127.
  static int8_t quantize(uint16_t value, float scale, int zeroPoint);

 private:
  struct FrontendState* state_ = nullptr;
};
