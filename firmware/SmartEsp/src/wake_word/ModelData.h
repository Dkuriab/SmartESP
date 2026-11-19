#pragma once

// Модель слова пробуждения, встроенная в прошивку.
// Значения — в ModelData.cpp, его создаёт tools/embed_model.py из
// tools/models/<модель>/*.json + .tflite (как сменить модель — README).

#include <stddef.h>
#include <stdint.h>

extern const uint8_t WAKE_MODEL_DATA[];     // файл .tflite, выровнен на 16 байт
extern const size_t WAKE_MODEL_SIZE;        // длина WAKE_MODEL_DATA, байт
extern const float WAKE_MODEL_CUTOFF;       // порог средней вероятности, 0..1
extern const uint8_t WAKE_MODEL_WINDOW;     // сколько последних вероятностей усреднять
extern const size_t WAKE_MODEL_ARENA_SIZE;  // память под тензоры модели, байт
extern const char WAKE_MODEL_WORD[];        // слово (UTF-8), для журнала
