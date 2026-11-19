#pragma once

// Звуки колонки (внутренний заголовок audio_out). Значения — в SoundData.cpp,
// его создаёт tools/make_sounds.py. PCM 16 кГц, 16 бит, моно, уровень уже в образце.

#include <stddef.h>
#include <stdint.h>

extern const int16_t SOUND_WAKE[];
extern const size_t SOUND_WAKE_LEN;
extern const int16_t SOUND_LISTEN[];
extern const size_t SOUND_LISTEN_LEN;
extern const int16_t SOUND_THINKING[];
extern const size_t SOUND_THINKING_LEN;
extern const int16_t SOUND_ERROR[];
extern const size_t SOUND_ERROR_LEN;
extern const int16_t SOUND_ATTENTION[];
extern const size_t SOUND_ATTENTION_LEN;
