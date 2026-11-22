#pragma once

// Внутренний файл модуля server_link: JSON-сообщения протокола WebSocket
// (см. дизайн, раздел 7). Без Arduino-зависимостей — тестируется на ноутбуке.

#include <stddef.h>

#include "../common/Types.h"

// {"type":"hello","fw":...,"device_id":...,"protocol":5,"sample_rate":16000,
//  "format":"pcm_s16le","channels":1}
// deviceId — MAC Wi-Fi строкой. Возвращает длину JSON без завершающего нуля;
// 0 — не хватило места.
size_t encodeHello(const char* fwVersion, const char* deviceId, char* out, size_t capacity);

// wake / utterance_end / barge_in / playback_done / busy / played с полем turn
// (reason для utterance_end, level для wake, bytes для played). 0 — не хватило места.
// played — расширение протокола 3: старое ядро неизвестный type пропускает.
// update_status (протокол 4) — без turn: {"what":"firmware"|"model","state":"progress"|"done"|"failed",
// "done":байт,"total":байт,"error":""|"busy"|"download"|"size"|"hash"|"write"|"storage"}.
// stream_status (протокол 5) — без turn: {"stream":N,"state":"playing"|"ended"|"stopped"|"failed",
// "played":байт,"error":""|"download"|"rate"}.
size_t encodeClientEvent(const ClientEvent& event, char* out, size_t capacity);

// Разбирает команду сервера. false — не JSON, неизвестный type или не хватает полей.
// update (протокол 4): {"what":"firmware"|"model","path":"/…","size":N,"sha256":"<64 hex>"}, для модели
// ещё "cutoff" (0..1), "window" (1..32), "arena" (байт) и необязательное "word".
// Протокол 5: stream_start {"stream":N>0,"path":"/…","rate":Гц,"volume":0..1?,"live":bool?},
// stream_stop {"stream":N?} (нет — 0, любой), stream_volume {"value":0..1}.
bool decodeServerCommand(const char* json, size_t length, ServerCommand& out);
