#pragma once

// Внутренний файл модуля audio_out: смена частоты ровно в 3 раза (16 ↔ 48 кГц) многофазным
// КИХ-фильтром. Один фильтр-прототип на 48 кГц (окно Кайзера): полоса пропускания до ~7 кГц,
// подавление от 8 кГц. Upsampler3 — голос и звуки 16 кГц на динамик 48 кГц (зеркала спектра выше
// 8 кГц гасятся); Decimator3 — смесь 48 кГц в образец эхоподавления 16 кГц (то, чего микрофон
// 16 кГц не слышит, в образец не попадает). Чистая логика без Arduino — тестируется на ноутбуке.

#include <stddef.h>
#include <stdint.h>

constexpr size_t RESAMPLE_TAPS = 96;              // отводов прототипа (кратно 3)
constexpr size_t RESAMPLE_PHASE = RESAMPLE_TAPS / 3;  // отводов на фазу
// Задержка фильтра: (RESAMPLE_TAPS - 1) / 2 отсчёта 48 кГц ≈ 0,99 мс.
constexpr float RESAMPLE_DELAY_MS = (RESAMPLE_TAPS - 1) / 2.0f / 48.0f;

// Коэффициенты прототипа (сумма — 1): sinc со срезом cutoffHz на rateHz под окном Кайзера beta.
void designLowpass(float* taps, size_t count, float cutoffHz, float rateHz, float beta);

class Upsampler3 {
 public:
  Upsampler3();

  // in — n отсчётов 16 кГц; out — 3·n отсчётов 48 кГц. Состояние переходит между вызовами.
  void process(const int16_t* in, size_t n, int16_t* out);

  // Забыть прошлый звук (новый поток).
  void reset();

 private:
  float phases_[3][RESAMPLE_PHASE];  // фаза p: taps[3k + p] · 3
  float history_[RESAMPLE_PHASE] = {};  // последние входные отсчёты, новый — в [0]
};

class Decimator3 {
 public:
  Decimator3();

  // in — n отсчётов 48 кГц; out — каждый третий после фильтра (16 кГц). Возвращает сколько.
  // Деление на кадры любое: счёт фазы переходит между вызовами.
  size_t process(const int16_t* in, size_t n, int16_t* out);

 private:
  float taps_[RESAMPLE_TAPS];
  float ring_[RESAMPLE_TAPS] = {};  // последние входные отсчёты по кругу
  size_t head_ = 0;                 // куда писать следующий
  size_t phase_ = 0;                // сколько отсчётов с последнего выхода
};
