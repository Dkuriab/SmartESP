#include "AudioIn.h"

namespace {

constexpr uint32_t SAMPLE_RATE = 16000;
constexpr size_t FRAME = 256;  // отсчётов за одно чтение I2S (16 мс)
constexpr uint32_t LOG_PERIOD_MS = 1000;

}  // namespace

bool AudioIn::begin(const AudioInConfig& config, ReferenceSource reference) {
  config_ = config;
  reference_ = reference;

  capacity_ = SAMPLE_RATE;  // 1 с пар
  ring_ = (int16_t*)heap_caps_malloc(capacity_ * 2 * sizeof(int16_t), MALLOC_CAP_SPIRAM);
  if (!ring_) {
    Serial.println("audio_in: нет памяти под буфер");
    return false;
  }

  i2s_.setPins(config_.sckPin, config_.wsPin, -1, config_.sdPin);
  // INMP441: 24 бита в 32-битном слоте, левый канал (L/R → GND).
  if (!i2s_.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("audio_in: не удалось запустить I2S");
    return false;
  }
  i2s_.setTimeout(1000);

  return xTaskCreatePinnedToCore(taskEntry, "audio_in", 4096, this, 7, nullptr, 0) == pdPASS;
}

size_t AudioIn::read(int16_t* mic, int16_t* ref, size_t samples) {
  taskENTER_CRITICAL(&lock_);
  const size_t n = samples < count_ ? samples : count_;
  size_t tail = (head_ + capacity_ - count_) % capacity_;
  for (size_t i = 0; i < n; i++) {
    mic[i] = ring_[2 * tail];
    ref[i] = ring_[2 * tail + 1];
    tail = (tail + 1) % capacity_;
  }
  count_ -= n;
  taskEXIT_CRITICAL(&lock_);
  return n;
}

void AudioIn::push(const int16_t* mic, const int16_t* ref, size_t samples) {
  taskENTER_CRITICAL(&lock_);
  for (size_t i = 0; i < samples; i++) {
    ring_[2 * head_] = mic[i];
    ring_[2 * head_ + 1] = ref[i];
    head_ = (head_ + 1) % capacity_;
    if (count_ < capacity_) {
      count_++;
    } else {
      dropped_++;  // затёрли самую старую пару
    }
  }
  taskEXIT_CRITICAL(&lock_);
}

void AudioIn::taskEntry(void* self) {
  static_cast<AudioIn*>(self)->run();
}

void AudioIn::run() {
  static int32_t raw[FRAME];
  static int16_t mic[FRAME];
  static int16_t ref[FRAME];
  int32_t peak = 0;
  uint32_t lastLevelMs = millis();

  for (;;) {
    const size_t got = i2s_.readBytes((char*)raw, sizeof(raw)) / sizeof(int32_t);
    if (got == 0) {
      continue;
    }
    for (size_t i = 0; i < got; i++) {
      int32_t s = raw[i] >> config_.shift;
      if (s > 32767) s = 32767;
      if (s < -32768) s = -32768;
      mic[i] = (int16_t)s;
      const int32_t a = s < 0 ? -s : s;
      if (a > peak) peak = a;
    }
    // Образец — сразу после чтения микрофона, чтобы пара совпадала по времени.
    reference_(ref, got);
    push(mic, ref, got);

    const uint32_t now = millis();
    if (dropped_ > 0 && now - lastDropLogMs_ >= LOG_PERIOD_MS) {
      lastDropLogMs_ = now;
      Serial.printf("audio_in: буфер переполнен, потеряно %u отсчётов (loop() не успевает)\n", (unsigned)dropped_);
      dropped_ = 0;
    }
    if (config_.printLevel && now - lastLevelMs >= LOG_PERIOD_MS) {
      lastLevelMs = now;
      Serial.printf("mic peak: %ld\n", (long)peak);
      peak = 0;
    }
  }
}
