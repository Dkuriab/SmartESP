# Тестовый сервер SmartESP

Эхо-сервер для проверки прошивки без нейросети: принимает вопрос и
проигрывает его обратно как ответ. Печатает все сообщения от ESP.

## Установка

```bash
cd tools/test_server
python3 -m pip install -r requirements.txt
```

## Запуск

```bash
python3 server.py            # эхо
python3 server.py --long     # ответ — 60 с тона в 4× темпе (переполнение очереди ESP)
python3 server.py --odd      # звук кусками по 4095 байт (нечётные куски)
```

В `secrets.h` прошивки: `SERVER_HOST` — IP ноутбука в локальной сети,
`SERVER_PORT` — 8765 (или свой `--port`).

## Команды в консоли

| Команда | Что отправит |
|---|---|
| `v 0.3` | громкость 0..1 |
| `t wake` / `t error` / `t thinking` | встроенный тон |
| `s` | `stop_playback` |
| `l` | `stop_listening` для текущего хода |
