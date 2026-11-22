#pragma once

// Внутренний файл модуля updater: свои звуки сигналов в LittleFS.
// /sounds/<tone>.pcm — PCM 16 кГц моно s16le, /sounds/<tone>.sha — его SHA-256 (64 символа);
// /sounds/<tone>.tmp — скачивается, пока не проверен. LittleFS должна быть смонтирована.

#include <stddef.h>
#include "../common/Types.h"

constexpr size_t MAX_SOUND_BYTES = 96000;  // 3 с: 48 000 отсчётов

// Создаёт папку звуков, если её нет.
void prepareSoundFolder();

// Путь временного файла звука tone (строка живёт до следующего вызова).
const char* soundTempPath(Tone tone);

// Читает сохранённый звук tone в PSRAM (освобождать — heap_caps_free). false — его нет;
// испорченный (размер, хэш-файл, нет памяти) удаляется.
bool loadSoundFile(Tone tone, StoredSound& out);

// Проверенный временный файл — на место звука tone, рядом его SHA-256. false — не вышло (всё удалено).
bool commitSoundFile(Tone tone, const char* sha256);

// Удаляет свой звук tone (и временный файл): дальше играет встроенный.
void removeSoundFile(Tone tone);
