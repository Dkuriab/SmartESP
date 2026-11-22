#pragma once

// audio_out — динамик (MAX98357A по I2S).
// Проигрывает очередь звука (ответ сервера) и звуки-сигналы: встроенные образцы или свои
// (присланные ядром, setSound).
// Всё, что ушло на динамик, параллельно кладётся в буфер «образца» —
// по нему voice_frontend вычитает звук колонки из микрофона (эхоподавление).

#include <Arduino.h>
#include <atomic>
#include "ESP_I2S.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include "../common/Types.h"

struct AudioOutConfig {
  int bclkPin;
  int lrcPin;
  int dinPin;
  uint32_t refDelayMs = 80;     // сдвиг образца: задержка DMA динамика
  uint32_t queueSeconds = 30;   // ёмкость очереди ответа (в PSRAM)
  uint32_t prebufferMs = 100;   // сколько накопить перед началом воспроизведения
};

class AudioOut {
 public:
  // Запускает I2S и задачу воспроизведения. false — не удалось (I2S, память).
  bool begin(const AudioOutConfig& config);

  // Кладёт звук (PCM 16 кГц, 16 бит, моно) в очередь. Не блокирует.
  // Возвращает, сколько отсчётов принято; остальное отброшено (очередь полна).
  size_t write(const int16_t* pcm, size_t samples);

  // Сразу проигрывает тон (свой звук, если задан, иначе встроенный). Очередь на время тона —
  // на паузе.
  void playTone(Tone tone);

  // Свой звук сигнала tone вместо встроенного: pcm — PCM 16 кГц моно, выделенный
  // heap_caps_malloc (обычно в PSRAM); AudioOut становится его владельцем и освободит, когда
  // звук заменят. pcm == nullptr — снова встроенный. Подмена — когда тон не звучит (звучащий
  // доигрывается прежним). false — очередь подмен полна: pcm уже освобождён, звук прежний.
  bool setSound(Tone tone, int16_t* pcm, size_t samples);

  // Очищает очередь и обрывает тон — тишина сразу.
  void stop();

  // Громкость 0..1 (по умолчанию 0.5).
  void setVolume(float volume);

  // true, пока в очереди есть звук, последний кусок очереди ещё пишется в I2S
  // или звучит тон.
  bool isPlaying() const;

  // Сколько байт звука из очереди (PCM write(), не тоны) отдано в I2S с запуска.
  // Счётчик переполняется по кругу. Безопасно вызывать из другой задачи.
  // Читать после isPlaying(): если тот вернул false, весь доигранный звук уже учтён.
  uint32_t playedBytes() const;

  // Образец для эхоподавления: ровно samples отсчётов, нули там, где тишина.
  // Безопасно вызывать из другой задачи (audio_in). Возвращает samples.
  size_t readReference(int16_t* dst, size_t samples);

 private:
  static void taskEntry(void* self);
  void run();
  size_t renderTone(int16_t* dst, size_t samples);
  void applySounds();
  void pushRefSilence(uint32_t ms);

  AudioOutConfig config_{};
  I2SClass i2s_;
  StreamBufferHandle_t queue_ = nullptr;
  StreamBufferHandle_t reference_ = nullptr;
  QueueHandle_t sounds_ = nullptr;  // подмены звуков: setSound → задача воспроизведения

  volatile float volume_ = 0.5f;
  volatile int toneRequest_ = -1;   // Tone, который надо начать; -1 — нет
  volatile bool stopRequest_ = false;
  volatile bool toneActive_ = false;
  volatile uint32_t lastWriteMs_ = 0;
  std::atomic<uint32_t> playedBytes_{0};  // пишет только задача воспроизведения
  std::atomic<bool> queueStarted_{false}; // очередь играет (пишет только задача)
  uint32_t lastOverflowLogMs_ = 0;

  // Состояние задачи воспроизведения (меняется только в ней).
  Tone tone_ = Tone::Wake;
  size_t tonePos_ = 0;  // сколько отсчётов образца уже отдано
  int16_t* custom_[5] = {};     // свои звуки по порядку Tone; nullptr — встроенный
  size_t customLen_[5] = {};
};
