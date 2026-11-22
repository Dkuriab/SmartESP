#include "AudioOut.h"

#include <string.h>
#include "SoundData.h"
#include "esp_heap_caps.h"
#include "freertos/idf_additions.h"

namespace {

constexpr uint32_t SAMPLE_RATE = 16000;  // голос, звуки, очередь ответа и образец
constexpr uint32_t OUT_RATE = 48000;     // динамик
constexpr size_t CHUNK = 256;            // отсчётов 16 кГц за проход (16 мс)
constexpr size_t OUT_CHUNK = CHUNK * 3;  // те же 16 мс на 48 кГц
constexpr uint32_t IDLE_START_MS = 100;  // начать играть, если новых данных нет столько
constexpr uint32_t OVERFLOW_LOG_PERIOD_MS = 1000;
constexpr size_t TONES = 5;         // сигналов в Tone (размер custom_ в AudioOut.h)
constexpr UBaseType_t SWAPS = 10;   // подмен в очереди: пять при загрузке и запас

// Подмена звука сигнала (setSound → задача воспроизведения).
struct Swap {
  uint8_t tone;
  int16_t* pcm;
  size_t samples;
};

// Звук — образец из SoundData.cpp (уровень уже внутри).
struct Sound {
  const int16_t* pcm;
  size_t len;
};

Sound builtinOf(Tone tone) {
  switch (tone) {
    case Tone::Wake: return {SOUND_WAKE, SOUND_WAKE_LEN};
    case Tone::Listen: return {SOUND_LISTEN, SOUND_LISTEN_LEN};
    case Tone::Error: return {SOUND_ERROR, SOUND_ERROR_LEN};
    case Tone::Thinking: return {SOUND_THINKING, SOUND_THINKING_LEN};
    case Tone::Attention: return {SOUND_ATTENTION, SOUND_ATTENTION_LEN};
  }
  return {SOUND_WAKE, SOUND_WAKE_LEN};
}

uint32_t msToSamples(uint32_t ms) {
  return SAMPLE_RATE * ms / 1000;
}

}  // namespace

bool AudioOut::begin(const AudioOutConfig& config) {
  config_ = config;

  const size_t queueBytes = msToSamples(config_.queueSeconds * 1000) * sizeof(int16_t);
  queue_ = xStreamBufferCreateWithCaps(queueBytes, 1, MALLOC_CAP_SPIRAM);
  reference_ = xStreamBufferCreate(SAMPLE_RATE * sizeof(int16_t), 1);  // 1 с образца
  sounds_ = xQueueCreate(SWAPS, sizeof(Swap));
  if (!queue_ || !reference_ || !sounds_) {
    Serial.println("audio_out: нет памяти под буферы");
    return false;
  }

  i2s_.setPins(config_.bclkPin, config_.lrcPin, config_.dinPin);
  // Стерео 16 бит, оба канала одинаковые — так проверено на MAX98357A. Всегда 48 кГц: частота на
  // лету не меняется (щелчки и сбой выравнивания образца).
  if (!i2s_.begin(I2S_MODE_STD, OUT_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("audio_out: не удалось запустить I2S");
    return false;
  }

  refDelayMs_ = config_.refDelayMs;
  return xTaskCreatePinnedToCore(taskEntry, "audio_out", 4096, this, 6, nullptr, 0) == pdPASS;
}

void AudioOut::setMusicSource(MusicSource source) {
  music_ = source;
}

// Музыка 48 кГц (или 16 кГц через ×3) — под голосом, с общей громкостью.
void AudioOut::mixMusic(int16_t* out) {
  static int16_t music[OUT_CHUNK];
  static int16_t low[CHUNK];
  uint32_t rate = OUT_RATE;
  size_t m = music_ ? music_(music, OUT_CHUNK, rate) : 0;
  if (m == 0) {
    if (musicWasUp_) musicUp_.reset();  // следующий поток — без хвоста прошлого
    musicWasUp_ = false;
    return;
  }
  if (rate != OUT_RATE) {
    m = m < CHUNK ? m : CHUNK;
    memcpy(low, music, m * sizeof(int16_t));
    memset(low + m, 0, (CHUNK - m) * sizeof(int16_t));
    musicUp_.process(low, CHUNK, music);
    musicWasUp_ = true;
    m = OUT_CHUNK;
  }
  const float volume = volume_;
  for (size_t i = 0; i < m; i++) {
    const int32_t mixed = out[i] + static_cast<int32_t>(music[i] * volume);
    out[i] = static_cast<int16_t>(mixed > 32767 ? 32767 : (mixed < -32768 ? -32768 : mixed));
  }
}

void AudioOut::setRefDelay(uint32_t ms) {
  refDelayMs_ = ms;
}

// Смесь 48 кГц → ÷3 → образец 16 кГц; новый сдвиг вносится здесь же (тишина или пропуск).
void AudioOut::pushReference(const int16_t* out) {
  static int16_t ref[CHUNK];
  const uint32_t target = refDelayMs_;
  if (target > refAppliedMs_) {
    pushRefSilence(target - refAppliedMs_);
  } else if (target < refAppliedMs_) {
    refSkip_ += msToSamples(refAppliedMs_ - target);
  }
  refAppliedMs_ = target;
  const size_t n = refDown_.process(out, OUT_CHUNK, ref);
  const size_t skip = refSkip_ < n ? refSkip_ : n;
  refSkip_ -= skip;
  if (n > skip) {
    xStreamBufferSend(reference_, ref + skip, (n - skip) * sizeof(int16_t), 0);
  }
}

size_t AudioOut::write(const int16_t* pcm, size_t samples) {
  const size_t accepted = xStreamBufferSend(queue_, pcm, samples * sizeof(int16_t), 0) / sizeof(int16_t);
  lastWriteMs_ = millis();
  if (accepted < samples && millis() - lastOverflowLogMs_ >= OVERFLOW_LOG_PERIOD_MS) {
    lastOverflowLogMs_ = millis();
    Serial.printf("audio_out: очередь полна, отброшено %u отсчётов\n", (unsigned)(samples - accepted));
  }
  return accepted;
}

void AudioOut::playTone(Tone tone) {
  toneRequest_ = static_cast<int>(tone);
}

bool AudioOut::setSound(Tone tone, int16_t* pcm, size_t samples) {
  const Swap swap{static_cast<uint8_t>(tone), pcm, pcm ? samples : 0};
  if (swap.tone >= TONES || !sounds_ || xQueueSend(sounds_, &swap, 0) != pdTRUE) {
    heap_caps_free(pcm);  // nullptr — ничего не делает
    return false;
  }
  return true;
}

void AudioOut::stop() {
  // Отменяем тон здесь, а не в задаче: иначе тон, заказанный сразу после
  // stop() (сигнал при перебивании), задача сбросила бы вместе со стопом.
  toneRequest_ = -1;
  stopRequest_ = true;
}

void AudioOut::setVolume(float volume) {
  volume_ = constrain(volume, 0.0f, 1.0f);
}

bool AudioOut::isPlaying() const {
  // Порядок важен: сначала очередь, потом queueStarted_. Задача сбрасывает queueStarted_
  // только после того, как учла в playedBytes_ последний взятый из очереди кусок, —
  // поэтому «не играет» гарантирует, что счётчик уже полный.
  const bool queued = xStreamBufferBytesAvailable(queue_) > 0;
  return queued || queueStarted_ || toneActive_ || toneRequest_ >= 0;
}

uint32_t AudioOut::playedBytes() const {
  return playedBytes_;
}

size_t AudioOut::readReference(int16_t* dst, size_t samples) {
  const size_t got = xStreamBufferReceive(reference_, dst, samples * sizeof(int16_t), 0) / sizeof(int16_t);
  for (size_t i = got; i < samples; i++) {
    dst[i] = 0;
  }
  return samples;
}

void AudioOut::taskEntry(void* self) {
  static_cast<AudioOut*>(self)->run();
}

void AudioOut::pushRefSilence(uint32_t ms) {
  static const int16_t zeros[CHUNK] = {0};
  uint32_t left = msToSamples(ms);
  while (left > 0) {
    const uint32_t n = left < CHUNK ? left : CHUNK;
    xStreamBufferSend(reference_, zeros, n * sizeof(int16_t), 0);
    left -= n;
  }
}

// Подмены звуков — только в задаче воспроизведения и пока тон не звучит: читает custom_ тоже
// только она, поэтому старый буфер освобождается без гонок.
void AudioOut::applySounds() {
  Swap swap;
  while (xQueueReceive(sounds_, &swap, 0) == pdTRUE) {
    heap_caps_free(custom_[swap.tone]);
    custom_[swap.tone] = swap.samples > 0 ? swap.pcm : nullptr;
    customLen_[swap.tone] = swap.samples;
    if (swap.pcm && swap.samples == 0) heap_caps_free(swap.pcm);
  }
}

size_t AudioOut::renderTone(int16_t* dst, size_t samples) {
  const size_t index = static_cast<size_t>(tone_);
  const Sound sound = index < TONES && custom_[index] ? Sound{custom_[index], customLen_[index]} : builtinOf(tone_);
  const float volume = volume_;
  size_t n = 0;
  while (n < samples && tonePos_ < sound.len) {
    dst[n++] = (int16_t)(sound.pcm[tonePos_++] * volume);
  }
  if (tonePos_ >= sound.len) {
    toneActive_ = false;
  }
  return n;
}

// Голос 16 кГц этого прохода: тон или очередь ответа (с громкостью), остаток — тишина.
size_t AudioOut::renderVoice(int16_t* voice) {
  if (stopRequest_) {
    stopRequest_ = false;
    // Задачи не ждут на очереди (все вызовы с таймаутом 0), поэтому reset безопасен.
    xStreamBufferReset(queue_);
    toneActive_ = false;
    queueStarted_ = false;
  }
  if (!toneActive_) {
    applySounds();
  }
  const int request = toneRequest_;
  if (request >= 0) {
    toneRequest_ = -1;
    tone_ = static_cast<Tone>(request);
    tonePos_ = 0;
    toneActive_ = true;
  }
  size_t n = 0;
  if (toneActive_) {
    n = renderTone(voice, CHUNK);
  } else {
    const size_t available = xStreamBufferBytesAvailable(queue_) / sizeof(int16_t);
    if (!queueStarted_ && available > 0 &&
        (available >= msToSamples(config_.prebufferMs) || millis() - lastWriteMs_ >= IDLE_START_MS)) {
      queueStarted_ = true;
    }
    if (queueStarted_) {
      n = xStreamBufferReceive(queue_, voice, CHUNK * sizeof(int16_t), 0) / sizeof(int16_t);
      playedBytes_ += static_cast<uint32_t>(n * sizeof(int16_t));  // кусок уйдёт в I2S в этом же проходе
      if (n == 0) {
        queueStarted_ = false;  // очередь кончилась — снова ждём предзаполнения
      }
      const float volume = volume_;
      for (size_t i = 0; i < n; i++) {
        voice[i] = (int16_t)(voice[i] * volume);
      }
    }
  }
  memset(voice + n, 0, (CHUNK - n) * sizeof(int16_t));
  return n;
}

void AudioOut::run() {
  static int16_t voice[CHUNK];
  static int16_t out[OUT_CHUNK];
  static int16_t stereo[OUT_CHUNK * 2];

  // I2S пишется непрерывно (в паузах — тишиной) и всегда целыми кусками по 16 мс, поэтому образец
  // сдвигается на задержку DMA один раз и дальше остаётся выровнен с динамиком (ревью №1).
  refAppliedMs_ = refDelayMs_;
  pushRefSilence(refAppliedMs_);

  for (;;) {
    renderVoice(voice);
    voiceUp_.process(voice, CHUNK, out);  // всегда: фильтр не рвётся между кусками
    mixMusic(out);                        // музыка — под голосом; образец ниже — уже смесь
    for (size_t i = 0; i < OUT_CHUNK; i++) {
      stereo[2 * i] = out[i];
      stereo[2 * i + 1] = out[i];
    }
    i2s_.write(stereo, sizeof(stereo));  // блокируется, пока DMA не освободится
    pushReference(out);
  }
}
