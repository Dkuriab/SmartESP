#pragma once

// Внутренний файл модуля voice_frontend: превращает состояние детектора
// речи (VAD) по кадрам в события «речь началась / закончилась».
// Без Arduino-зависимостей — тестируется на ноутбуке.
//
// Первые graceMs после включения захвата VAD игнорируется: он ещё «слышит»
// само слово-активатор (задержка VAD ≈ vadSilenceMs), и без паузы получился
// бы ложный конец фразы в паузе между словом и вопросом.

#include <stdint.h>

enum class SpeechChange : uint8_t { None, Start, End };

class SpeechTracker {
 public:
  explicit SpeechTracker(uint32_t graceMs = 600) : graceMs_(graceMs) {}

  // Новый захват: снова ждём graceMs, речь «не идёт».
  void reset();

  // Очередной кадр: speech — VAD слышит речь, frameMs — длительность кадра.
  SpeechChange update(bool speech, uint32_t frameMs);

 private:
  uint32_t graceMs_;
  uint32_t elapsedMs_ = 0;
  bool speaking_ = false;
};
