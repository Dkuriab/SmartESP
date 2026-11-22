#include "Resampler.h"

#include <math.h>

namespace {

constexpr float OUT_RATE = 48000.0f;
constexpr float CUTOFF_HZ = 7600.0f;  // середина перехода 7…8,2 кГц
constexpr float KAISER_BETA = 7.0f;   // ~70 дБ в полосе подавления

// Модифицированная функция Бесселя I0 (ряд) — для окна Кайзера.
float besselI0(float x) {
  float sum = 1.0f;
  float term = 1.0f;
  for (int k = 1; k < 30; ++k) {
    term *= (x / (2.0f * k)) * (x / (2.0f * k));
    sum += term;
  }
  return sum;
}

int16_t saturate(float value) {
  if (value > 32767.0f) return 32767;
  if (value < -32768.0f) return -32768;
  return static_cast<int16_t>(lrintf(value));
}

}  // namespace

void designLowpass(float* taps, size_t count, float cutoffHz, float rateHz, float beta) {
  const float center = (count - 1) / 2.0f;
  const float fc = cutoffHz / rateHz;  // доля частоты дискретизации
  const float norm = besselI0(beta);
  float sum = 0.0f;
  for (size_t i = 0; i < count; ++i) {
    const float t = i - center;
    const float sinc = t == 0.0f ? 2.0f * fc : sinf(2.0f * static_cast<float>(M_PI) * fc * t) / (static_cast<float>(M_PI) * t);
    const float r = t / center;
    const float window = besselI0(beta * sqrtf(fmaxf(0.0f, 1.0f - r * r))) / norm;
    taps[i] = sinc * window;
    sum += taps[i];
  }
  for (size_t i = 0; i < count; ++i) {
    taps[i] /= sum;
  }
}

Upsampler3::Upsampler3() {
  float taps[RESAMPLE_TAPS];
  designLowpass(taps, RESAMPLE_TAPS, CUTOFF_HZ, OUT_RATE, KAISER_BETA);
  for (size_t p = 0; p < 3; ++p) {
    for (size_t k = 0; k < RESAMPLE_PHASE; ++k) {
      phases_[p][k] = taps[3 * k + p] * 3.0f;  // ×3: вставленные нули съели две трети энергии
    }
  }
}

void Upsampler3::reset() {
  for (float& value : history_) value = 0.0f;
}

void Upsampler3::process(const int16_t* in, size_t n, int16_t* out) {
  for (size_t i = 0; i < n; ++i) {
    for (size_t k = RESAMPLE_PHASE - 1; k > 0; --k) {
      history_[k] = history_[k - 1];
    }
    history_[0] = in[i];
    for (size_t p = 0; p < 3; ++p) {
      float acc = 0.0f;
      for (size_t k = 0; k < RESAMPLE_PHASE; ++k) {
        acc += phases_[p][k] * history_[k];
      }
      out[3 * i + p] = saturate(acc);
    }
  }
}

Decimator3::Decimator3() {
  designLowpass(taps_, RESAMPLE_TAPS, CUTOFF_HZ, OUT_RATE, KAISER_BETA);
}

size_t Decimator3::process(const int16_t* in, size_t n, int16_t* out) {
  size_t produced = 0;
  for (size_t i = 0; i < n; ++i) {
    ring_[head_] = in[i];
    head_ = (head_ + 1) % RESAMPLE_TAPS;
    if (++phase_ < 3) {
      continue;
    }
    phase_ = 0;
    float acc = 0.0f;
    size_t index = head_;  // самый старый отсчёт
    for (size_t k = 0; k < RESAMPLE_TAPS; ++k) {
      acc += taps_[RESAMPLE_TAPS - 1 - k] * ring_[index];
      index = index + 1 == RESAMPLE_TAPS ? 0 : index + 1;
    }
    out[produced++] = saturate(acc);
  }
  return produced;
}
