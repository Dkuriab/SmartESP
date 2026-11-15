#pragma once

// Внутренний файл модуля server_link: JSON-сообщения протокола WebSocket
// (см. дизайн, раздел 7). Без Arduino-зависимостей — тестируется на ноутбуке.

#include <stddef.h>

#include "../common/Types.h"

// {"type":"hello","fw":...,"sample_rate":16000,"format":"pcm_s16le","channels":1}
// Возвращает длину JSON без завершающего нуля; 0 — не хватило места.
size_t encodeHello(const char* fwVersion, char* out, size_t capacity);

// wake / utterance_end / barge_in / playback_done с полем turn
// (и reason для utterance_end). 0 — не хватило места.
size_t encodeClientEvent(const ClientEvent& event, char* out, size_t capacity);

// Разбирает команду сервера. false — не JSON, неизвестный type или не хватает полей.
bool decodeServerCommand(const char* json, size_t length, ServerCommand& out);
