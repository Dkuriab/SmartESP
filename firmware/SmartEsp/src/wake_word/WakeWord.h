#pragma once

// wake_word — слово пробуждения на колонке: потоковая модель microWakeWord
// (TFLite Micro) на очищенном звуке из voice_frontend.
// Признаки — микрофронтенд TFLite (WakeFeatures), модель вызывается каждые
// 3 кадра (30 мс), вероятности усредняются по окну; выше порога — срабатывание,
// затем refractoryMs детектор молчит. Считает в своей задаче FreeRTOS.

#include <Arduino.h>

struct WakeWordConfig {
  const uint8_t* model;  // файл .tflite в памяти (выровнен на 16 байт)
  size_t modelSize;      // его длина, байт
  size_t arenaSize;      // память под тензоры модели (из манифеста), байт
  float cutoff;          // порог средней вероятности, 0..1
  uint8_t window;        // сколько последних вероятностей усреднять
  uint32_t refractoryMs = 1000;  // пауза после срабатывания
};

class WakeWord {
 public:
  WakeWord() = default;
  WakeWord(const WakeWord&) = delete;
  WakeWord& operator=(const WakeWord&) = delete;

  // Загружает модель (арена — в PSRAM) и запускает задачу распознавания.
  // false + сообщение в Serial при ошибке: модель не та (версия, операции,
  // форма входа/выхода), нет памяти.
  bool begin(const WakeWordConfig& config);

  // Подаёт звук: PCM 16 кГц, моно, любыми кусками. Не блокирует: если задача
  // не успевает, кусок отбрасывается (раз в секунду — сообщение в Serial).
  void feed(const int16_t* pcm, size_t samples);

  // true один раз на каждое срабатывание. Вызывать из одной задачи (loop()).
  bool poll();

 private:
  struct State;
  State* state_ = nullptr;  // всё внутреннее — в WakeWord.cpp
};
