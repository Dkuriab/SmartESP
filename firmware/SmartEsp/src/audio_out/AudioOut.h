#pragma once

// audio_out — динамик (MAX98357A по I2S), всегда 48 кГц (прошивка 0.7.0).
// Проигрывает очередь звука (ответ сервера) и звуки-сигналы: встроенные образцы или свои
// (присланные ядром, setSound) — всё это 16 кГц, на динамик идёт через многофазное ×3; музыка
// (setMusicSource) — 48 кГц напрямую или 16 кГц через ×3.
// Всё, что ушло на динамик, через фильтр ÷3 (до ~7 кГц) кладётся в буфер «образца» 16 кГц —
// по нему voice_frontend вычитает звук колонки из микрофона (эхоподавление).

#include <Arduino.h>
#include <atomic>
#include <functional>
#include "ESP_I2S.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/stream_buffer.h"
#include "../common/Types.h"
#include "Resampler.h"

// Источник музыки (stream_player): dst вмещает samples отсчётов 48 кГц (16 мс). Источник пишет
// в rate свою частоту (48000 или 16000) и отдаёт не больше samples · rate / 48000 отсчётов;
// вернуть сколько; 0 — тишина.
using MusicSource = std::function<size_t(int16_t* dst, size_t samples, uint32_t& rate)>;

struct AudioOutConfig {
  int bclkPin;
  int lrcPin;
  int dinPin;
  uint32_t refDelayMs = 20;     // сдвиг образца: задержка DMA динамика (48 кГц; меняется калибровкой)
  uint32_t queueSeconds = 30;   // ёмкость очереди ответа (в PSRAM)
  uint32_t prebufferMs = 100;   // сколько накопить перед началом воспроизведения
};

class AudioOut {
 public:
  // Запускает I2S и задачу воспроизведения. false — не удалось (I2S, память).
  bool begin(const AudioOutConfig& config);

  // Музыка под голосом и звуками (необязательно; вызывать до begin()). Звучит с общей
  // громкостью, попадает в образец эхоподавления; isPlaying() и playedBytes() её не считают.
  void setMusicSource(MusicSource source);

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

  // Новый сдвиг образца, мс (калибровка эха): больше — образцу добавится тишина, меньше —
  // пропустится лишнее. Безопасно вызывать из другой задачи.
  void setRefDelay(uint32_t ms);

  // Образец для эхоподавления (16 кГц): ровно samples отсчётов, нули там, где тишина.
  // Безопасно вызывать из другой задачи (audio_in). Возвращает samples.
  size_t readReference(int16_t* dst, size_t samples);

 private:
  static void taskEntry(void* self);
  void run();
  size_t renderTone(int16_t* dst, size_t samples);
  void applySounds();
  void pushRefSilence(uint32_t ms);
  size_t renderVoice(int16_t* voice);
  void mixMusic(int16_t* out);
  void pushReference(const int16_t* out);

  AudioOutConfig config_{};
  I2SClass i2s_;
  StreamBufferHandle_t queue_ = nullptr;
  StreamBufferHandle_t reference_ = nullptr;
  QueueHandle_t sounds_ = nullptr;  // подмены звуков: setSound → задача воспроизведения
  MusicSource music_;

  volatile float volume_ = 0.5f;
  volatile int toneRequest_ = -1;   // Tone, который надо начать; -1 — нет
  volatile bool stopRequest_ = false;
  volatile bool toneActive_ = false;
  volatile uint32_t lastWriteMs_ = 0;
  std::atomic<uint32_t> playedBytes_{0};  // пишет только задача воспроизведения
  std::atomic<bool> queueStarted_{false}; // очередь играет (пишет только задача)
  std::atomic<uint32_t> refDelayMs_{0};   // нужный сдвиг образца (setRefDelay)
  uint32_t lastOverflowLogMs_ = 0;

  // Состояние задачи воспроизведения (меняется только в ней).
  Tone tone_ = Tone::Wake;
  size_t tonePos_ = 0;  // сколько отсчётов образца уже отдано
  int16_t* custom_[5] = {};     // свои звуки по порядку Tone; nullptr — встроенный
  size_t customLen_[5] = {};
  Upsampler3 voiceUp_;          // голос и звуки 16 → 48 кГц
  Upsampler3 musicUp_;          // музыка 16 кГц → 48 кГц
  Decimator3 refDown_;          // смесь 48 → образец 16 кГц
  uint32_t refAppliedMs_ = 0;   // сдвиг, уже внесённый в образец
  size_t refSkip_ = 0;          // сколько отсчётов образца пропустить (сдвиг уменьшили)
  bool musicWasUp_ = false;     // прошлый кусок музыки шёл через ×3
};
