#pragma once

// Внутренний файл модуля server_link: сообщения калибровки эха и частоты потоков (прошивка 0.7.0,
// возможность «echo» в hello; номер протокола тот же — 5). Без Arduino — тестируется на ноутбуке.
//
// Ядро → колонка: {"type":"echo_calibrate"} — калибровка; {"type":"echo_delay","delay_ms":0..300} —
// сдвиг образца вручную. Колонка → ядро: {"type":"echo_status","state":"current"|"running"|"done"|
// "failed","delay_ms":N,"previous_ms":N,"confidence":0..1,"error":""|"busy"|"quiet"|"weak"}.

#include <ArduinoJson.h>

#include "../common/Types.h"

// Частоты потоков, которые колонка играет (поле hello stream_rates).
constexpr uint32_t STREAM_RATES[] = {16000, 48000};

// Дописывает в hello возможность «echo» и stream_rates.
void addHelloExtras(JsonDocument& doc);

// echo_status — поля события (turn убирается).
void encodeEchoStatus(const ClientEvent& event, JsonDocument& doc);

// echo_calibrate / echo_delay → команда; false — не они или неверные поля.
bool decodeEchoCommand(const char* type, const JsonDocument& doc, ServerCommand& out);
