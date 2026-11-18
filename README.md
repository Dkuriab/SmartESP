# SmartESP

Умная колонка на ESP32-S3: ждёт слово «Hi, ESP», отправляет вопрос на сервер
с нейросетью по WebSocket и проигрывает ответ. Ответ можно перебить словом.

Устройство прошивки — `docs/superpowers/specs/2026-11-15-firmware-design.md`,
правила проекта — `CLAUDE.md`.

## Установка на новом Mac с нуля

Ядро работает только на Mac с Apple Silicon (M1 и новее): распознавание речи —
`mlx-whisper`. Прошивать плату можно с любой системы (разделы ниже).

1. Проект:
   ```bash
   git clone https://github.com/Dkuriab/SmartESP.git SmartEsp
   cd SmartEsp
   ```
   Скачать может любой; чтобы пушить — войдите своим аккаунтом GitHub или
   заведите на этом компьютере свой ключ доступа (чужой ключ не копируйте).
2. Программы (если нет Homebrew — сначала https://brew.sh):
   ```bash
   brew install uv
   brew install --cask ollama   # затем один раз открыть приложение Ollama
   ```
3. Модель для ответов (~6 ГБ):
   ```bash
   ollama pull fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive
   ```
4. Ядро (`uv sync` в первый раз долгий — ставится torch):
   ```bash
   uv python install 3.12
   (cd core && uv sync)
   ```
   Интерфейс (нужен Node.js):
   ```bash
   cd ui && npm ci && npm run build
   ```
5. Запуск:
   ```bash
   cd core && uv run python -m smartesp
   ```
   Первый старт долгий: скачиваются модель распознавания (~1,6 ГБ) и голос
   по умолчанию Silero (~145 МБ), создаётся
   `~/SmartEsp/config.yaml`. Готово, когда в журнале «Запускаю сервер на
   ws://0.0.0.0:8765/device». Если macOS спросит про входящие подключения —
   разрешить, иначе колонка не достучится.
6. Проверка без платы (второе окно терминала, из корня проекта) — должны прийти
   `reply_start`, звук и `reply_end`:
   ```bash
   uv run --project core python tools/fake_device.py --wav core/tests/data/privet.wav
   ```
7. Плата: в `firmware/SmartEsp/` выполнить `cp secrets.example.h secrets.h`
   (файл не в git — на новом компьютере его нет), вписать Wi-Fi и `SERVER_HOST` = IP этого Mac
   (`ipconfig getifaddr en0`), собрать и прошить — см. «Сборка в Arduino IDE».

## Подключение

| Устройство | Пин | GPIO |
|---|---|---|
| Микрофон INMP441 (L/R → GND) | SCK / WS / SD | 5 / 4 / 9 |
| Усилитель MAX98357A | BCLK / LRC / DIN | 7 / 6 / 8 |

Модуль: ESP32-S3-WROOM **N16R8** (16 МБ флеша, 8 МБ PSRAM).

## Сборка в Arduino IDE

Скетч — `firmware/SmartEsp/SmartEsp.ino` (открывать его, а не корень репозитория:
в корне лежит ядро, и Arduino IDE на нём спотыкается).

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

Перед первой сборкой скопируйте `firmware/SmartEsp/secrets.example.h` в
`firmware/SmartEsp/secrets.h` и заполните Wi-Fi и адрес сервера.

## Сборка из командной строки

```bash
tools/build.sh
```

Нужен `arduino-cli` с установленным ядром esp32 3.3.12. Библиотеки нужных
версий скрипт ставит сам.

## Как пользоваться

1. На ноутбуке запустите тестовый сервер (`tools/test_server/README.md`)
   или настоящий сервер с нейросетью.
2. В `firmware/SmartEsp/secrets.h` — Wi-Fi и IP ноутбука, прошейте плату.
3. Скажите **«Hi, ESP»** → короткий сигнал → задайте вопрос.
   Конец вопроса — 0,5 с тишины. С тестовым сервером колонка повторит
   вопрос вашим же голосом.
4. Во время ответа снова скажите «Hi, ESP» — ответ оборвётся, можно
   задать новый вопрос.

Звуки: один высокий сигнал — слово услышано; низкий длинный — ошибка
(нет связи с сервером или ответ не пришёл за 15 с).

## Ядро на Mac

Настоящий сервер — ядро в папке `core/` (Python): распознаёт речь, отвечает
локальной моделью через Ollama и озвучивает ответ. Установка, настройка колонок
и запуск — в [`core/README.md`](core/README.md). Без платы ядро проверяется
поддельной колонкой `tools/fake_device.py`: вопрос из WAV, ответ — в WAV.

## Тесты логики на ноутбуке

```bash
tools/host_tests/run.sh
```

Проверяют сценарий (`session`) и протокол (`server_link`) без платы.
Нужен clang++ и ArduinoJson (см. комментарий в `run.sh`).
