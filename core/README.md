# SmartESP core

Ядро домашнего голосового ассистента (сервер на Mac): принимает речь с
колонок ESP32, распознаёт, отвечает через локальную модель и озвучивает.
Дизайн: `../docs/superpowers/specs/2026-11-18-core-design.md`.

## Установка

Нужны `uv` и Python 3.12 (`uv python install 3.12`).

```
cd core
uv sync
```

`mlx-whisper` тянет `torch` — установка долгая, это нормально.

## Проверка

```
uv run pytest
uv run ruff check && uv run ruff format --check
uv run pyright
```

## Голос

Голос Piper скачивается один раз (из корня репозитория):

```
tools/download_voice.sh                       # ru_RU-irina-medium
tools/download_voice.sh ru_RU-denis-medium    # или другой голос
```

Файлы ложатся в `~/SmartEsp/voices/<голос>.onnx`. Голос выбирается в
`config.yaml` (`tts.voice`); если файла нет, ядро не стартует и подскажет команду.

## Запуск

```
cd core
uv run python -m smartesp
```

Перед запуском должна работать Ollama (`ollama serve` или приложение) с моделью
из `config.yaml` (`ollama pull <модель>`). Если Ollama недоступна, ядро всё равно
стартует (в журнале «Ollama недоступна: …»), но на вопросы колонка будет
отвечать сигналом ошибки.

Первый запуск:
- создаётся `~/SmartEsp/config.yaml` с настройками по умолчанию — правьте его
  и перезапускайте ядро;
- mlx-whisper скачивает модель распознавания (~1,6 ГБ) в кеш Hugging Face —
  первый старт долгий, дальше модель берётся из кеша.

При старте ядро прогревает модели (в журнале «Исполнитель прогрет…»,
«STT прогрет…»), затем слушает колонки на `ws://<mac>:8765/device`
(адрес и порт — `server` в `config.yaml`). Остановка — Ctrl+C.

## Колонки

Колонка представляется ядру MAC-адресом Wi-Fi: `device_id` в `hello`,
заглавными через двоеточие (`AA:BB:CC:DD:EE:FF`). MAC видно в журнале ядра при
подключении: `device AA:BB:CC:DD:EE:FF connected from …`. Имя колонки (модель
его видит: «Колонка: Кухня») задаётся в `config.yaml`, ключ — MAC **в кавычках**:
MAC из одних цифр без кавычек YAML прочтёт как число, и колонка останется без имени.

```yaml
devices:
  "AA:BB:CC:DD:EE:FF":
    name: Кухня
  "11:22:33:44:55:66":
    name: Спальня
```

## Где что лежит

Папка данных — `~/SmartEsp` (или `$SMARTESP_HOME`):
- `config.yaml` — настройки (колонки, модели, голос, окна арбитража);
- `voices/` — голоса Piper;
- `logs/core.log` — журнал (5 файлов по 1 МБ, плюс вывод в консоль). Каждый
  ход — строка с вопросом, ответом и задержками `stt_ms`, `first_text_ms`,
  `first_audio_ms`.

## Проверка без колонки

Поддельная колонка задаёт вопрос из WAV (16 кГц, 16 бит, моно) и печатает
ответ ядра (из корня репозитория, при запущенном ядре):

```
uv run --project core python tools/fake_device.py --wav core/tests/data/privet.wav --out reply.wav
```
