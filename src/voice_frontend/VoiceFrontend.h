#pragma once

// voice_frontend — обработка звука ESP-SR (AFE): эхоподавление,
// слово-активатор «Hi, ESP» и детектор речи (VAD).
// На вход — пары «микрофон + образец динамика», на выход — события и
// очищенный от эха звук (только пока включён захват).

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include "../common/Types.h"
#include "SpeechTracker.h"

struct VoiceFrontendConfig {
  uint32_t vadSilenceMs = 500;  // сколько тишины считать концом фразы
};

class VoiceFrontend {
 public:
  // Загружает модели и запускает AFE. false + сообщение в Serial при ошибке
  // (нет PSRAM, нет моделей — см. Partition Scheme в README).
  bool begin(const VoiceFrontendConfig& config);

  // Подаёт пары «микрофон + образец» любыми кусками. Не блокирует.
  void feed(const int16_t* mic, const int16_t* ref, size_t samples);

  // Следующее событие, если есть: WakeWord; при захвате — SpeechStart, SpeechEnd.
  bool pollEvent(VoiceEvent& event);

  // Включает/выключает захват очищенного звука и событий речи.
  // Вызывать из той же задачи, что и readClean (loop()).
  void setCapture(bool on);

  // Очищенный звук (PCM 16 кГц, моно), только пока захват включён.
  // Не блокирует. Возвращает число отсчётов.
  size_t readClean(int16_t* dst, size_t maxSamples);

 private:
  static void feedTaskEntry(void* self);
  static void fetchTaskEntry(void* self);
  void feedTask();
  void fetchTask();
  void pushEvent(VoiceEventType type);
  void drainClean();

  // Интерфейс AFE (const esp_afe_sr_iface_t*). В заголовке — void*, потому что
  // тип в ESP-SR — анонимная структура и не объявляется заранее.
  const void* afe_ = nullptr;
  struct esp_afe_sr_data_t* afeData_ = nullptr;
  int chunk_ = 0;     // отсчётов на канал в кадре AFE
  int channels_ = 0;  // каналов в кадре AFE (ожидаем 2: M и R)

  int16_t* frame_ = nullptr;  // накапливаемый кадр для feed()
  int filled_ = 0;            // сколько отсчётов на канал уже в frame_
  StreamBufferHandle_t feedQueue_ = nullptr;   // целые кадры → задача подачи
  StreamBufferHandle_t cleanQueue_ = nullptr;  // очищенный звук → readClean
  QueueHandle_t events_ = nullptr;

  SpeechTracker speech_;  // используется только в задаче выборки
  volatile bool capture_ = false;
  volatile uint32_t captureGeneration_ = 0;  // меняется при каждом setCapture
  uint32_t droppedFrames_ = 0;
  uint32_t lastDropLogMs_ = 0;
};
