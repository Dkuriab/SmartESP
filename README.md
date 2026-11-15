# SmartESP

Умная колонка на ESP32-S3: ждёт слово «Hi, ESP», отправляет вопрос на сервер
с нейросетью по WebSocket и проигрывает ответ. Ответ можно перебить словом.

Устройство прошивки — `docs/superpowers/specs/2026-11-15-firmware-design.md`,
правила проекта — `CLAUDE.md`.

## Подключение

| Устройство | Пин | GPIO |
|---|---|---|
| Микрофон INMP441 (L/R → GND) | SCK / WS / SD | 5 / 4 / 9 |
| Усилитель MAX98357A | BCLK / LRC / DIN | 7 / 6 / 8 |

Модуль: ESP32-S3-WROOM **N16R8** (16 МБ флеша, 8 МБ PSRAM).

## Сборка в Arduino IDE

Ядро: **esp32 by Espressif 3.3.12** (Boards Manager).

Библиотеки (Library Manager, точные версии):

| Библиотека | Автор | Версия |
|---|---|---|
| WebSockets | Markus Sattler | 2.7.2 |
| ArduinoJson | Benoit Blanchon | 7.4.3 |

Tools:

| Пункт | Значение |
|---|---|
| Board | ESP32S3 Dev Module |
| Flash Size | 16MB (128Mb) |
| Partition Scheme | ESP SR 16M (3MB APP/6MB SPIFFS/3.9MB MODEL) |
| PSRAM | OPI PSRAM |
| USB CDC On Boot | Enabled — если подключены к порту «USB», а не «UART» |

Перед первой сборкой скопируйте `secrets.example.h` в `secrets.h` и
заполните Wi-Fi и адрес сервера.

## Сборка из командной строки

```bash
tools/build.sh
```

Нужен `arduino-cli` с установленным ядром esp32 3.3.12. Библиотеки нужных
версий скрипт ставит сам.
