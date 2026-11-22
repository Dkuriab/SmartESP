#pragma once

// echo_calibrator — сдвиг образца для эхоподавления: хранится в NVS, меняется калибровкой или
// вручную (команды echo_calibrate и echo_delay ядра).
// Калибровка: колонка играет 1,5 с шума (readSignal → audio_out) и пишет 2,8 с пар «микрофон +
// образец» (feed, из audio_in). Затем своя задача FreeRTOS ищет сдвиг взаимной корреляцией
// (Correlator.h): k > 0 — эхо в микрофоне позже образца, образец надо задержать ещё на k.
// Новый сдвиг = прежний + k − leadMs (образец чуть опережает эхо), 0…maxDelayMs. Уверенно —
// сохраняет в NVS и отдаёт audio_out (pollDelay); итог — событие echo_status (pollStatus).
// loop() не блокируется: счёт — в задаче, запись NVS — доли мс.

#include <Arduino.h>
#include <atomic>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "../common/Types.h"

struct EchoCalibratorConfig {
  uint32_t defaultDelayMs = 20;  // сдвиг без калибровки (48 кГц: DMA 30 мс − ~10 мс микрофона)
  uint32_t maxDelayMs = 300;
  uint32_t signalMs = 1500;      // длина шума
  uint32_t recordMs = 2800;      // сколько писать с начала калибровки
  uint32_t maxLagMs = 200;       // эхо позже образца — не больше
  uint32_t leadMs = 5;           // образец опережает эхо на столько
  int16_t amplitude = 8000;      // шум, до общей громкости (−12 дБFS)
  float minConfidence = 0.2f;    // меньше — «не услышал»
  float minRatio = 1.2f;         // пик выделяется меньше — «не услышал»
};

class EchoCalibrator {
 public:
  // Читает сохранённый сдвиг (нет — defaultDelayMs) и создаёт очереди. Звать до audio_out.begin().
  bool begin(const EchoCalibratorConfig& config);

  // Сдвиг образца сейчас, мс.
  uint32_t delayMs() const;

  // Начать калибровку (команда echo_calibrate). Идёт — итог failed/busy.
  void start();

  // Задать сдвиг вручную (команда echo_delay): сохранить, отдать audio_out, сообщить current.
  void setDelay(uint32_t ms);

  // Есть ли связь с ядром; при подключении — событие current со сдвигом. Каждый loop().
  void setConnected(bool connected);

  // Пары «микрофон + образец» (16 кГц) из audio_in; пишутся только во время калибровки.
  void feed(const int16_t* mic, const int16_t* ref, size_t samples);

  // Тестовый шум (16 кГц) для audio_out.write; 0 — нечего играть.
  size_t readSignal(int16_t* dst, size_t maxSamples);

  // Новый сдвиг для audio_out.setRefDelay; false — нет.
  bool pollDelay(uint32_t& ms);

  // Следующее событие echo_status для сервера.
  bool pollStatus(ClientEvent& event);

  // Вызывать из loop(): итог задачи счёта → NVS, audio_out, событие.
  void loop(uint32_t nowMs);

 private:
  enum Phase : uint8_t { Idle, Recording, Analyzing, Finished };

  static void taskEntry(void* self);
  void analyze();
  void finish();
  void store(uint32_t ms);
  void post(EchoState state, EchoError error, uint32_t previous, float confidence);
  void release();

  EchoCalibratorConfig config_{};
  QueueHandle_t events_ = nullptr;
  uint32_t delayMs_ = 0;
  uint32_t pendingDelay_ = 0;
  bool hasPending_ = false;
  bool connected_ = false;
  std::atomic<uint8_t> phase_{Idle};

  // Калибровка (буферы — в PSRAM на время калибровки).
  int16_t* mic_ = nullptr;
  int16_t* ref_ = nullptr;
  size_t recordSamples_ = 0;
  size_t recorded_ = 0;
  size_t signalSamples_ = 0;
  size_t signalPos_ = 0;
  uint32_t seed_ = 1;
  uint32_t startDelayMs_ = 0;  // сдвиг, с которым писали
  // Итог задачи счёта (пишет задача, читает loop() после Finished).
  int resultLag_ = 0;
  float resultConfidence_ = 0.0f;
  float resultRatio_ = 0.0f;
  bool resultQuiet_ = false;
};
