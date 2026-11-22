#pragma once

// Внутренний файл модуля server_link: JSON-сообщения протокола WebSocket
// (см. дизайн, раздел 7). Без Arduino-зависимостей — тестируется на ноутбуке.

#include <stddef.h>

#include "../common/Types.h"

// {"type":"hello","fw":...,"device_id":...,"protocol":4,"sample_rate":16000,
//  "format":"pcm_s16le","channels":1,"caps":["sounds"],"sounds":{"wake":"<sha256>",...}}
// deviceId — MAC Wi-Fi строкой. sounds — SHA-256 своих звуков по порядку Tone (TONE_COUNT строк;
// пустая — встроенный, в JSON не попадает); nullptr — своих нет. Возвращает длину JSON без
// завершающего нуля; 0 — не хватило места.
// caps — возможности сверх протокола: «sounds» — понимает update со звуком (прошивка 0.6.0).
constexpr size_t TONE_COUNT = 5;  // сигналов в Tone
size_t encodeHello(const char* fwVersion, const char* deviceId, char* out, size_t capacity,
                   const char (*sounds)[65] = nullptr);

// wake / utterance_end / barge_in / playback_done / busy / played с полем turn
// (reason для utterance_end, level для wake, bytes для played). 0 — не хватило места.
// played — расширение протокола 3: старое ядро неизвестный type пропускает.
// update_status (протокол 4) — без turn: {"what":"firmware"|"model","state":"progress"|"done"|"failed",
// "done":байт,"total":байт,"error":""|"busy"|"download"|"size"|"hash"|"write"|"storage"}.
size_t encodeClientEvent(const ClientEvent& event, char* out, size_t capacity);

// Разбирает команду сервера. false — не JSON, неизвестный type или не хватает полей.
// update (протокол 4): {"what":"firmware"|"model","path":"/…","size":N,"sha256":"<64 hex>"}, для модели
// ещё "cutoff" (0..1), "window" (1..32), "arena" (байт) и необязательное "word".
// Звук (возможность sounds): what "sound" и "tone"; "size":0 без path и sha256 — вернуть встроенный.
bool decodeServerCommand(const char* json, size_t length, ServerCommand& out);
