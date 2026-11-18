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

## Запуск

Точка входа `smartesp.main` появится в следующих задачах этапа 1.

## Голос

Голос Piper (русский, например `ru_RU-irina-medium`) загружается в папку
моделей; команда загрузки и путь появятся вместе с модулем `tts`.
