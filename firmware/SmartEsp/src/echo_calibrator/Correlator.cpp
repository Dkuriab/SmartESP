#include "Correlator.h"

#include <math.h>

#include <vector>

namespace {

constexpr int COARSE = 4;     // отсчётов в грубом шаге
constexpr int FINE_SPAN = 8;  // точный поиск — ±столько отсчётов от грубого пика
constexpr int EXCLUDE = 2;    // соседние грубые сдвиги не считаются «другим пиком»

// Нормированная корреляция a[i + lag] и b[i], i ∈ [start, start + window). Acc — тип сумм:
// float на грубом шаге (на колонке double — программный и медленный), double — на точном.
template <typename Acc, typename T>
double correlation(const T* a, const T* b, size_t start, size_t window, int lag) {
  Acc ab = 0;
  Acc aa = 0;
  Acc bb = 0;
  for (size_t i = start; i < start + window; ++i) {
    const Acc x = a[static_cast<long>(i) + lag];
    const Acc y = b[i];
    ab += x * y;
    aa += x * x;
    bb += y * y;
  }
  return aa > 0 && bb > 0 ? static_cast<double>(ab) / sqrt(static_cast<double>(aa) * static_cast<double>(bb)) : 0.0;
}

// Средние по COARSE отсчётов (простой фильтр нижних частот и прореживание).
std::vector<float> coarse(const int16_t* x, size_t n) {
  std::vector<float> out(n / COARSE);
  for (size_t i = 0; i < out.size(); ++i) {
    float sum = 0.0f;
    for (int k = 0; k < COARSE; ++k) sum += x[i * COARSE + k];
    out[i] = sum / COARSE;
  }
  return out;
}

int floorDiv(int a, int b) {
  return a >= 0 ? a / b : -((-a + b - 1) / b);
}

}  // namespace

int16_t testNoise(uint32_t& seed, size_t position, size_t total, size_t fadeSamples, int16_t amplitude) {
  seed = seed * 1664525u + 1013904223u;  // LCG (Numerical Recipes)
  const float unit = static_cast<float>(seed >> 8) / static_cast<float>(1u << 24) * 2.0f - 1.0f;
  float gain = 1.0f;
  if (fadeSamples > 0 && position < fadeSamples) gain = static_cast<float>(position) / fadeSamples;
  if (fadeSamples > 0 && total - position <= fadeSamples) gain = static_cast<float>(total - position - 1) / fadeSamples;
  return static_cast<int16_t>(unit * amplitude * gain);
}

size_t findOnset(const int16_t* x, size_t n, int16_t threshold) {
  for (size_t i = 0; i < n; ++i) {
    if (x[i] >= threshold || x[i] <= -threshold) return i;
  }
  return n;
}

LagEstimate findLag(const int16_t* mic, const int16_t* ref, size_t n, size_t start, size_t window,
                    int minLag, int maxLag) {
  // Грубо: средние по 4, все сдвиги.
  const std::vector<float> micC = coarse(mic, n);
  const std::vector<float> refC = coarse(ref, n);
  const size_t startC = (start + COARSE - 1) / COARSE;
  const size_t windowC = window / COARSE > 1 ? window / COARSE - 1 : 1;
  const int minC = floorDiv(minLag, COARSE) + 1;
  const int maxC = maxLag / COARSE - 1;
  std::vector<double> rho(maxC >= minC ? maxC - minC + 1 : 0);
  int bestC = 0;
  double best = -1.0;
  for (int lag = minC; lag <= maxC; ++lag) {
    const double value = fabs(correlation<float>(micC.data(), refC.data(), startC, windowC, lag));
    rho[lag - minC] = value;
    if (value > best) {
      best = value;
      bestC = lag;
    }
  }
  double second = 0.0;
  for (int lag = minC; lag <= maxC; ++lag) {
    if (lag < bestC - EXCLUDE || lag > bestC + EXCLUDE) second = fmax(second, rho[lag - minC]);
  }
  // Точно: отсчёты рядом с грубым пиком.
  LagEstimate result{bestC * COARSE, 0.0f, second > 0.0 ? static_cast<float>(best / second) : 99.0f};
  const int from = bestC * COARSE - FINE_SPAN < minLag ? minLag : bestC * COARSE - FINE_SPAN;
  const int to = bestC * COARSE + FINE_SPAN > maxLag ? maxLag : bestC * COARSE + FINE_SPAN;
  for (int lag = from; lag <= to; ++lag) {
    const float value = static_cast<float>(fabs(correlation<double>(mic, ref, start, window, lag)));
    if (value > result.confidence) {
      result.confidence = value;
      result.lag = lag;
    }
  }
  return result;
}
