#pragma once

// Внутренний файл модуля echo_calibrator: тестовый шум и поиск задержки эха взаимной
// корреляцией микрофона и образца. Чистая логика без Arduino — тестируется на ноутбуке.
//
// Поиск в два шага, чтобы не считать минутами на колонке: грубо — по средним из 4 отсчётов
// (все сдвиги), точно — по самим отсчётам рядом с грубым пиком (±8). Мера совпадения —
// нормированная корреляция |ρ| (0..1); второй пик дальше ±8 отсчётов от главного — для
// «насколько пик выделяется» (ratio).

#include <stddef.h>
#include <stdint.h>

struct LagEstimate {
  int lag;           // отсчётов 16 кГц: > 0 — эхо в микрофоне позже образца
  float confidence;  // |ρ| в найденном сдвиге, 0..1
  float ratio;       // главный пик / лучший из остальных (грубо); ≥ 1
};

// Шум для калибровки: равномерный, ±amplitude, с плавными краями fadeSamples (без щелчков).
// position — номер отсчёта от начала, total — длина всего сигнала; seed — состояние генератора.
int16_t testNoise(uint32_t& seed, size_t position, size_t total, size_t fadeSamples, int16_t amplitude);

// Первый отсчёт, где |x| ≥ threshold; n — не нашлось.
size_t findOnset(const int16_t* x, size_t n, int16_t threshold);

// Сдвиг k в [minLag, maxLag], при котором mic[i + k] лучше всего совпадает с ref[i] на окне
// i ∈ [start, start + window). Вызывающий гарантирует start + minLag ≥ 0 и
// start + window + maxLag ≤ n.
LagEstimate findLag(const int16_t* mic, const int16_t* ref, size_t n, size_t start, size_t window,
                    int minLag, int maxLag);
