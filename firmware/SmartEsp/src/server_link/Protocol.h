#pragma once

// Внутренний файл модуля server_link: JSON-сообщения протокола WebSocket
// (см. дизайн, раздел 7). Без Arduino-зависимостей — тестируется на ноутбуке.

#include <stddef.h>

#include "../common/Types.h"

// {"type":"hello","fw":...,"device_id":...,"protocol":2,"sample_rate":16000,
//  "format":"pcm_s16le","channels":1}
// deviceId — MAC Wi-Fi строкой. Возвращает длину JSON без завершающего нуля;
// 0 — не хватило места.
size_t encodeHello(const char* fwVersion, const char* deviceId, char* out, size_t capacity);

// wake / utterance_end / barge_in / playback_done с полем turn
// (reason для utterance_end, level для wake). 0 — не хватило места.
size_t encodeClientEvent(const ClientEvent& event, char* out, size_t capacity);

// Разбирает команду сервера. false — не JSON, неизвестный type или не хватает полей.
bool decodeServerCommand(const char* json, size_t length, ServerCommand& out);
