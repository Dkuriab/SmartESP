#pragma once

// audio_in — микрофон (INMP441 по I2S).
// Отдаёт пары «микрофон + образец динамика», выровненные по времени:
// образец запрашивается сразу после чтения каждого кадра с микрофона.
// Это нужно эхоподавлению — если брать образец позже (в loop()),
// рассинхрон будет плавать вместе с загрузкой loop().

#include <Arduino.h>
#include <functional>
#include "ESP_I2S.h"
#include "freertos/FreeRTOS.h"

struct AudioInConfig {
  int sckPin;
  int wsPin;
  int sdPin;
  int shift = 14;           // 32-битный отсчёт >> shift → 16 бит
  bool printLevel = false;  // печатать пиковый уровень раз в секунду (отладка)
};

// Источник образца: заполнить dst ровно samples отсчётами, вернуть samples.
using ReferenceSource = std::function<size_t(int16_t* dst, size_t samples)>;

class AudioIn {
 public:
  // Запускает I2S и задачу чтения. false — не удалось (I2S, память).
  bool begin(const AudioInConfig& config, ReferenceSource reference);

  // Забирает до samples пар. Не блокирует. Возвращает число пар.
  size_t read(int16_t* mic, int16_t* ref, size_t samples);

 private:
  static void taskEntry(void* self);
  void run();
  void push(const int16_t* mic, const int16_t* ref, size_t samples);

  AudioInConfig config_{};
  ReferenceSource reference_;
  I2SClass i2s_;

  // Кольцевой буфер пар [mic, ref]; при переполнении затираются старые.
  int16_t* ring_ = nullptr;
  size_t capacity_ = 0;  // в парах
  size_t head_ = 0;      // куда писать
  size_t count_ = 0;     // сколько пар лежит
  portMUX_TYPE lock_ = portMUX_INITIALIZER_UNLOCKED;

  uint32_t dropped_ = 0;
  uint32_t lastDropLogMs_ = 0;
};
