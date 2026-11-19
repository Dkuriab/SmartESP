#include "AudioOut.h"

#include <math.h>
#include <string.h>
#include "freertos/idf_additions.h"

namespace {

constexpr uint32_t SAMPLE_RATE = 16000;
constexpr size_t CHUNK = 256;  // отсчётов за одну запись в I2S (16 мс)
constexpr uint32_t IDLE_START_MS = 100;  // начать играть, если новых данных нет столько
constexpr uint32_t OVERFLOW_LOG_PERIOD_MS = 1000;
constexpr float TONE_LEVEL = 0.5f;  // тоны тише полной шкалы

// Тон — последовательность отрезков: частота (0 — пауза) и длительность.
struct ToneSegment {
  float hz;
  uint32_t ms;
};

const ToneSegment WAKE_TONE[] = {{1000.0f, 150}};
const ToneSegment ERROR_TONE[] = {{400.0f, 300}};
const ToneSegment THINKING_TONE[] = {{600.0f, 80}, {0.0f, 80}, {600.0f, 80}};

struct ToneShape {
  const ToneSegment* segments;
  uint32_t count;
};

ToneShape shapeOf(Tone tone) {
  switch (tone) {
    // Временно: Listen и Attention звучат как Wake (настоящие звуки — позже).
    case Tone::Wake:
    case Tone::Listen:
    case Tone::Attention: return {WAKE_TONE, sizeof(WAKE_TONE) / sizeof(WAKE_TONE[0])};
    case Tone::Error: return {ERROR_TONE, sizeof(ERROR_TONE) / sizeof(ERROR_TONE[0])};
    case Tone::Thinking: return {THINKING_TONE, sizeof(THINKING_TONE) / sizeof(THINKING_TONE[0])};
  }
  return {WAKE_TONE, 1};
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
  if (!queue_ || !reference_) {
    Serial.println("audio_out: нет памяти под буферы");
    return false;
  }

  i2s_.setPins(config_.bclkPin, config_.lrcPin, config_.dinPin);
  // Стерео 16 бит, оба канала одинаковые — так проверено на MAX98357A.
  if (!i2s_.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("audio_out: не удалось запустить I2S");
    return false;
  }

  return xTaskCreatePinnedToCore(taskEntry, "audio_out", 4096, this, 6, nullptr, 0) == pdPASS;
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
  return toneActive_ || toneRequest_ >= 0 || xStreamBufferBytesAvailable(queue_) > 0;
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

size_t AudioOut::renderTone(int16_t* dst, size_t samples) {
  const ToneShape shape = shapeOf(tone_);
  const float amplitude = volume_ * TONE_LEVEL * 32767.0f;
  size_t n = 0;
  while (n < samples && toneSegment_ < shape.count) {
    if (toneSegmentLeft_ == 0) {
      toneSegment_++;
      if (toneSegment_ >= shape.count) {
        break;
      }
      toneSegmentLeft_ = msToSamples(shape.segments[toneSegment_].ms);
      tonePhase_ = 0;
      continue;
    }
    const float hz = shape.segments[toneSegment_].hz;
    dst[n++] = hz > 0 ? (int16_t)(sinf(tonePhase_) * amplitude) : 0;
    tonePhase_ += 2.0f * PI * hz / SAMPLE_RATE;
    if (tonePhase_ > 2.0f * PI) {
      tonePhase_ -= 2.0f * PI;
    }
    toneSegmentLeft_--;
  }
  if (toneSegment_ >= shape.count) {
    toneActive_ = false;
  }
  return n;
}

void AudioOut::run() {
  static int16_t mono[CHUNK];
  static int16_t stereo[CHUNK * 2];

  // I2S пишется непрерывно (в паузах — тишиной), поэтому образец сдвигается
  // на задержку DMA один раз и дальше остаётся выровнен с динамиком.
  pushRefSilence(config_.refDelayMs);

  for (;;) {
    if (stopRequest_) {
      stopRequest_ = false;
      // Задачи не ждут на очереди (все вызовы с таймаутом 0), поэтому reset безопасен.
      xStreamBufferReset(queue_);
      toneActive_ = false;
      queueStarted_ = false;
    }

    const int request = toneRequest_;
    if (request >= 0) {
      toneRequest_ = -1;
      tone_ = static_cast<Tone>(request);
      toneSegment_ = 0;
      toneSegmentLeft_ = msToSamples(shapeOf(tone_).segments[0].ms);
      tonePhase_ = 0;
      toneActive_ = true;
    }

    size_t n = 0;
    if (toneActive_) {
      n = renderTone(mono, CHUNK);
    } else {
      const size_t available = xStreamBufferBytesAvailable(queue_) / sizeof(int16_t);
      if (!queueStarted_ && available > 0 &&
          (available >= msToSamples(config_.prebufferMs) || millis() - lastWriteMs_ >= IDLE_START_MS)) {
        queueStarted_ = true;
      }
      if (queueStarted_) {
        n = xStreamBufferReceive(queue_, mono, CHUNK * sizeof(int16_t), 0) / sizeof(int16_t);
        if (n == 0) {
          queueStarted_ = false;  // очередь кончилась — снова ждём предзаполнения
        } else {
          const float volume = volume_;
          for (size_t i = 0; i < n; i++) {
            mono[i] = (int16_t)(mono[i] * volume);
          }
        }
      }
    }

    if (n == 0) {
      // Играть нечего: пишем тишину. И в I2S, и в образец — так образец не
      // «уезжает» при каждой паузе в ответе (ревью №1).
      memset(mono, 0, sizeof(mono));
      n = CHUNK;
    }

    for (size_t i = 0; i < n; i++) {
      stereo[2 * i] = mono[i];
      stereo[2 * i + 1] = mono[i];
    }
    i2s_.write(stereo, n * 2 * sizeof(int16_t));  // блокируется, пока DMA не освободится
    xStreamBufferSend(reference_, mono, n * sizeof(int16_t), 0);
  }
}
