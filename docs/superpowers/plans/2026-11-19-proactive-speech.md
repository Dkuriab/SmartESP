# Речь по инициативе Кузи — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кузя сам говорит на колонке (запоздавший ответ), колонка слушает после вопроса Кузи, ядро умеет включить микрофон командой `listen`, звуки колонки — мягкие.

**Architecture:** Прошивка получает протокол v3 (`listen`, `busy`, тоны `listen`/`attention`) и звуки-образцы вместо синусоид. В ядре `devices` учится объявлениям и прослушиванию с итогом доставки, новый модуль `notify/` держит очередь объявлений, `conversation` при истечении 90 с отдаёт поток цели фоновой задаче и после вопроса включает прослушивание. Интерфейс — два переключателя и пометки в ленте.

**Tech Stack:** C++17 / Arduino (ESP32-S3), host-тесты на clang++; Python 3.12, asyncio, pydantic, FastAPI; React + TS.

**Spec:** `docs/superpowers/specs/2026-11-19-proactive-speech-design.md`

## Global Constraints

- Правила `CLAUDE.md`, `core/CLAUDE.md`, `ui/CLAUDE.md`: модули не импортируют друг друга (ядро — только `smartesp.contracts`), связка без логики; файл ≤ 300 строк, функция ≤ 50, сложность ≤ 10; комментарии на русском, имена на английском.
- Выполнение плана — прямо в `main` (решение владельца), коммиты на английском.
- Протокол: `hello.protocol = 3`. Номера ходов ядра для `announce`/`listen` — `0x80000000 | n`, n с 1 на сессию колонки.
- Имена тонов в протоколе: `wake`, `error`, `thinking`, `listen`, `attention`.
- Фразы дословно:
  - `LATER_PHRASE = "{name} долго думает. Скажу, когда будет готово."`
  - начало объявления: `"{name} отвечает: "` + ответ цели. (В дизайне «Ответ от <Имени>» — имя в конфиге в именительном падеже, «Ответ от Большая модель» неграмотно; поэтому так.)
- Числа: повтор объявления каждые 5 с (`RETRY_S = 5.0`); срок доставки 600 с (`EXPIRE_S`); предел запоздавшего ответа 600 с от начала хода (`LATE_LIMIT_S`); ожидание `playback_done` перед `listen` ≤ 30 с (`LISTEN_WAIT_S`); итог объявления — `lost`, если нет `playback_done` за длительность звука + 15 с.
- Настройки: `speech.proactive: true`, `speech.listen_after_question: true`; `CONFIG_VERSION` не меняется (новый раздел со значениями по умолчанию).
- Колонка с протоколом < 3: ни `announce`, ни `listen`; запоздавший ответ — как сейчас, `TIMEOUT_PHRASE`.
- Тесты ядра без железа и моделей; host-тесты прошивки — `tools/host_tests/run.sh`.
- Здесь нет Arduino IDE/arduino-cli: прошивку собрать нельзя. ArduinoJson 7.4.3 для host-тестов — `git clone --depth 1 --branch v7.4.3 https://github.com/bblanchon/ArduinoJson <scratchpad>/ArduinoJson`, запуск `ARDUINOJSON_DIR=<scratchpad>/ArduinoJson/src tools/host_tests/run.sh`. Сборка на плате — чек-лист владельцу в README.

## Review Focus

1. **Колонка отключилась / переподключилась, пока ядро ждёт итог объявления или `playback_done` перед `listen`** — ожидание заканчивается сразу (`lost` / ничего), ничего не виснет. Тесты — задача 3.
2. **Ядро останавливается, пока ждёт запоздавший ответ или держит очередь** — фоновые задачи отменяются в пределах честной остановки, поток исполнителя закрывается (`aclose`), Ollama не держит запрос. Тесты — задачи 5 и 6.
3. **Колонка v2** — никаких `listen`/`announce`; при 90 с звучит прежняя `TIMEOUT_PHRASE`. Тесты — задачи 3 и 5.
4. **Слово «Кузя» между `playback_done` и `listen`** — колонка отвечает `busy`, ядро выбрасывает пустую запись прослушивания, новый ход по слову идёт как обычно. Тест — задача 3 (и host-тест задачи 1).
5. **Владелец выключил «Кузя может заговорить сам», пока ответ ещё ждётся** — обещанный ответ всё равно звучит (человеку сказали «скажу»); новые запоздавшие ответы — уже `TIMEOUT_PHRASE`. Тест — задача 5.

---

### Task 1: Прошивка — протокол v3, `listen` и `busy` в Session

**Files:**
- Modify: `firmware/SmartEsp/src/common/Types.h` — `ClientEventType::Busy`, `ServerCommandType::Listen`, `Tone::Listen`, `Tone::Attention`.
- Modify: `firmware/SmartEsp/src/server_link/Protocol.cpp`, `Protocol.h` (комментарий hello) — `PROTOCOL_VERSION 3`, `encodeClientEvent` для `busy`, `decodeServerCommand` для `listen`, `readTone` для `listen`/`attention`.
- Modify: `firmware/SmartEsp/src/session/Session.cpp`, `Session.h`.
- Test: `tools/host_tests/session_test.cpp`, `tools/host_tests/protocol_test.cpp`.

**Interfaces:**
- Produces (JSON): `{"type":"listen","turn":N}` → `ServerCommand{Listen, turn}`; `ClientEvent{Busy, turn}` → `{"type":"busy","turn":N}`; `{"type":"tone","name":"listen"|"attention"}`.

- [ ] **Step 1: Failing protocol tests:** `decode_listen` (`{"type":"listen","turn":2147483650}` → `Listen`, `turn==0x80000002`; без `turn` → `false`), `encode_busy` (`{"type":"busy","turn":7}`), `decode_tone_listen_attention`, `hello_protocol_3` (`"protocol":3`).
- [ ] **Step 2: Failing session tests:**
  - `listen_from_idle`: connected, `Listen{0x80000001}` → `SetActiveTurn(0x80000001)`, `PlayTone(Listen)`, `StartCapture`, состояние `Listening`; без события `wake`.
  - `listen_then_speech`: дальше `SpeechStart`/`SpeechEnd` → `StopCapture`, `SendEvent(UtteranceEnd, 0x80000001, Vad)`, `Waiting`.
  - `listen_no_speech`: 5 с тишины → `UtteranceEnd(NoSpeech)` для `0x80000001`, `SetActiveTurn(0)`, `Idle`.
  - `listen_when_busy_sends_busy`: в `Speaking` → только `SendEvent(Busy, turn=команды)`, состояние не меняется.
  - `announce_when_busy_sends_busy`: в `Listening` → `SendEvent(Busy, turn=команды)`.
  - `listen_when_disconnected_ignored`: не connected → нет действий.
  - `wake_after_listen_turn_uses_local_counter`: ход по listen закончен → слово → `Wake` с `turn == localTurn_+1`.
- [ ] **Step 3: Run** `ARDUINOJSON_DIR=… tools/host_tests/run.sh` — новые тесты падают.
- [ ] **Step 4: Implement.** `Session::onServerCommand` — ветка `Listen` (из `Idle` при связи: `turn_ = command.turn`, `pushTone(Tone::Listen)`, `SetActiveTurn`, `StartCapture`, `enter(Listening)`), `busy` для `Announce`/`Listen` не в `Idle`. `pushEvent` сейчас берёт `turn_` — для `busy` нужен номер из команды (отдельная функция, например `pushEventFor(type, turn)`). `SmartEsp.ino` не меняется: `SendEvent` и `PlayTone` уже проходят через него. Комментарий в `Session.h` дополнить.
- [ ] **Step 5: Run** host-тесты — все проходят.
- [ ] **Step 6: Commit** `feat(firmware): protocol v3 — listen command and busy reply`.

### Task 2: Прошивка — звуки-образцы

**Files:**
- Create: `tools/make_sounds.py` — синтез звуков, запись `SoundData.cpp`.
- Create: `firmware/SmartEsp/src/audio_out/SoundData.h` (внутренний: объявления массивов и длин), `SoundData.cpp` (сгенерированный, шапка «не править руками, см. tools/make_sounds.py»).
- Modify: `firmware/SmartEsp/src/audio_out/AudioOut.cpp`, `AudioOut.h` — проигрывание образца вместо синусоиды.
- Test: `tools/test_make_sounds.py` (рядом с программой), запуск `uv run --project core pytest tools/test_make_sounds.py`.
- Modify: `README.md` — протокол v3, звуки, как пересоздать `SoundData.cpp`, чек-лист на плате.

**Interfaces:**
- Produces: `make_sounds.render(name: str) -> numpy.ndarray[int16]` (16 кГц моно) для `wake`, `listen`, `thinking`, `error`, `attention`; `make_sounds.write_cpp(path: Path) -> None`.

- [ ] **Step 1: Failing tests** `tools/test_make_sounds.py`:
  - `test_all_sounds_exist_and_short`: пять имён; длина ≤ 0,6 с (≤ 9600 отсчётов), `thinking` ≤ 0,35 с.
  - `test_no_clicks`: первые и последние 16 отсчётов по модулю ≤ 64 (плавные края).
  - `test_peak_below_full_scale`: пик ≤ 0,5 × 32767 (как `TONE_LEVEL`).
  - `test_listen_equals_wake`: `listen` и `wake` совпадают (дизайн 5.3).
  - `test_cpp_written`: `write_cpp(tmp)` → файл с `const int16_t` массивами пяти звуков и их длинами; второй запуск даёт тот же файл (детерминизм).
- [ ] **Step 2: Run** — падают.
- [ ] **Step 3: Implement** `tools/make_sounds.py`: мягкие колокольчики — сумма 2–3 гармоник с быстрой атакой (≥ 5 мс) и экспоненциальным затуханием, косинусный спад в конце. Вкус на усмотрение исполнителя: `wake/listen` — восходящий двухнотный звон, `thinking` — короткая тихая капля, `error` — нисходящий мягкий звон, `attention` — трёхнотный «динь-динь-дон» перед речью. Сгенерировать `SoundData.cpp`.
- [ ] **Step 4: Implement** `AudioOut`: `renderTone` копирует образец со сдвигом позиции и умножает на `volume_` (уровень уже в образце); `ToneSegment`/синусоиды удаляются. Публичный интерфейс `AudioOut.h` не меняется. Проверка синтаксиса без платы: `clang++ -std=c++17 -fsyntax-only -I firmware/SmartEsp/src firmware/SmartEsp/src/audio_out/SoundData.cpp`.
- [ ] **Step 5: Run** тесты программы и host-тесты — проходят.
- [ ] **Step 6: README** — раздел про протокол v3 и звуки, чек-лист на плате: слово → новый звон; «Кузя, спроси меня что-нибудь» → вопрос → звук «слушаю» → ответ без слова; тишина 5 с → молча в ожидание; громкость меняет и звуки.
- [ ] **Step 7: Commit** `feat(firmware): soft sample-based sounds generated by tools/make_sounds.py`.

### Task 3: Ядро — колонки: объявление, прослушивание, итог доставки

**Files:**
- Modify: `core/smartesp/contracts/device.py` — `Delivery`, новые методы `DevicePort`, `DeviceInfo.protocol`; `contracts/__init__.py`.
- Modify: `core/smartesp/devices/messages.py` — `Busy`, `announce(turn)`, `listen(turn)`; `session.py` — `protocol`, счётчик ходов ядра, ожидания итога хода; `registry.py` — протокол в `DeviceInfo`.
- Create: `core/smartesp/devices/proactive.py` — объявление и прослушивание поверх `Session` (держит `hub.py` ≤ 300 строк; если всё равно не помещается — перенести применение решений арбитра `_apply/_accept/_cancel` в отдельный файл).
- Modify: `core/smartesp/devices/hub.py`, `core/fakes/fake_device_port.py`, `core/smartesp/api/schemas.py` (`DeviceOut.protocol`).
- Test: `core/tests/devices/test_proactive.py` (новый), `test_messages.py`.

**Interfaces:**
- Produces (contracts):
  - `Delivery = Literal["delivered", "interrupted", "busy", "lost"]`
  - `DevicePort.supports_proactive(device_id: str) -> bool` — подключена и `protocol >= 3`.
  - `DevicePort.announce(device_id: str, audio: AsyncIterator[bytes]) -> Awaitable[Delivery]` — `announce` → `tone attention` → `reply_start` → звук → `reply_end`, ход ядра; ждёт итог.
  - `DevicePort.listen(device_id: str) -> Awaitable[bool]` — шлёт `listen` свободной колонке v3; `True` — команда ушла (ход ядра создан; `busy` позже снимает его).
  - `DevicePort.listen_after(device_id: str, turn: int) -> Awaitable[None]` — ждёт `playback_done` хода хаба `turn` (≤ `LISTEN_WAIT_S`), затем `listen`; ход кончился иначе — ничего.
  - `DevicePort.last_active_device() -> str | None` — колонка последнего принятого хода (по слову или прослушиванию), если подключена.
  - `DeviceInfo.protocol: int`.
- Ход прослушивания: хаб сразу выдаёт номер хода хаба, создаёт `Recording` с `turn_id` и `ActiveTurn`, арбитра не спрашивает; конец речи — обычный `_emit` в `next_utterance` с `Utterance.origin = "listen"` (новое поле `Utterance.origin: str = "wake"` в `contracts/audio.py`). Ход объявления в арбитраже не участвует.

- [ ] **Step 1: Failing tests** (`FakeConnection`, без сети):
  - `test_announce_delivered`: v3, свободна → кадры `announce{0x80000001}`, `tone attention`, `reply_start{0x80000001}`, звук, `reply_end`; колонка шлёт `playback_done{0x80000001}` → `"delivered"`.
  - `test_announce_busy`: колонка отвечает `busy{0x80000001}` → `"busy"`, ход снят, звук дальше не шлётся.
  - `test_announce_barge_in_is_interrupted`: `barge_in{0x80000001}` → `"interrupted"`.
  - `test_announce_lost_on_disconnect`: соединение закрылось посреди → `"lost"` сразу.
  - `test_announce_lost_without_playback_done`: нет `playback_done` за длительность + 15 с (часы подделкой / малый предел) → `"lost"`.
  - `test_announce_not_arbitrated`: `wake` на другой колонке во время объявления не шлёт `cancel_turn` объявляющей.
  - `test_v2_not_proactive`: `protocol 2` → `supports_proactive` False, `listen` → False без кадров, `announce` → `"lost"` без кадров.
  - `test_listen_emits_utterance`: `listen` → кадр `listen{0x80000001}`; звук + `utterance_end{0x80000001}` → `next_utterance()` с `origin == "listen"`.
  - `test_listen_busy_drops_recording`: `busy` на `listen` → запись выброшена, `next_utterance` пуст; следующий `wake` колонки идёт обычным ходом.
  - `test_listen_no_speech`: `utterance_end no_speech` → ничего.
  - `test_listen_after_waits_playback_done`: после `playback_done` нужного хода — кадр `listen`; после `barge_in` — нет кадра; колонка отключилась — возврат без кадра.
  - `test_last_active_device`: последний принятый ход; отключилась → None.
  - `test_core_turn_numbers_per_session`: новые сессии начинают снова с `0x80000001`.
  - `test_messages`: разбор `busy`, кодирование `announce`/`listen`.
- [ ] **Step 2: Run** `cd core && uv run pytest tests/devices -q` — падают.
- [ ] **Step 3: Implement.** Итог хода — ожидание (future) в `Session` по номеру хода колонки, которое разрешают `playback_done`/`barge_in`/`busy`/`cancel_turn` ядра/закрытие сессии. `FakeDevicePort` — новые методы с записью вызовов и настраиваемым итогом `announce`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check && uv run pyright` — всё зелёное.
- [ ] **Step 5: Commit** `feat(core): devices announce/listen with delivery result (protocol v3)`.

### Task 4: Ядро — настройки `speech` и место в связке

**Files:**
- Modify: `core/smartesp/config/models.py` — `SpeechConfig(proactive: bool = True, listen_after_question: bool = True)`, `Config.speech`.
- Create: `core/smartesp/sections.py` (связка) — перенести `_sections` и его помощники из `wiring.py` (там 298 строк), без изменения поведения; добавить раздел `speech` позже, в задаче 6.
- Modify: `core/smartesp/wiring.py`, `core/CLAUDE.md` (структура: `sections.py`), `core/README.md` (раздел `speech`).
- Test: `core/tests/config/test_models.py` (или существующий файл настроек), `core/tests/test_lifecycle_changes.py` — без изменений, должны проходить.

- [ ] **Step 1: Failing test** `test_speech_defaults`: `Config().speech.proactive is True and Config().speech.listen_after_question is True`; правка `{"speech": {"proactive": False}}` через `ConfigFile.merge` принимается; неизвестный ключ в `speech` отвергается.
- [ ] **Step 2: Implement** модель и перенос `_sections` (чистый перенос; `wiring.py` импортирует из `sections.py`).
- [ ] **Step 3: Run** `uv run pytest -q`, `ruff`, `pyright`; `wc -l smartesp/wiring.py` < 280.
- [ ] **Step 4: Commit** `feat(core): speech settings; move live sections out of wiring`.

### Task 5: Ядро — запоздавший ответ и прослушивание после вопроса (`conversation/`)

**Files:**
- Create: `core/smartesp/contracts/notify.py` — `class Announcer(Protocol): def say(self, device_id: str, text: str, source: str) -> None`.
- Create: `core/smartesp/conversation/late.py` — фоновые задачи запоздавших ответов.
- Modify: `core/smartesp/conversation/streams.py` — ожидание первого куска без отмены `anext` при пределе.
- Modify: `core/smartesp/conversation/handoffs.py`, `orchestrator.py` (≤ 300 строк — выносить в `late.py`/новые файлы), `turn.py`, `turn_events.py`.
- Modify: `core/smartesp/api/schemas.py` — `TurnOut.origin: Literal["wake","listen","core"] = "wake"`, `TurnOut.kind: Literal["turn","announcement"] = "turn"`, статус `undelivered`.
- Test: `core/tests/conversation/test_late_answer.py`, `test_listen_after.py` (новые), `core/tests/test_end_to_end.py` (сквозной случай).

**Interfaces:**
- Consumes: `DevicePort.supports_proactive`, `DevicePort.listen_after` (задача 3); `Announcer` (contracts).
- Produces:
  - `Orchestrator.set_speech(proactive: bool, listen_after_question: bool) -> None`.
  - `Orchestrator.use_announcer(announcer: Announcer) -> None`.
  - `Orchestrator.speech(text: str) -> AsyncIterator[bytes]` — озвучка текущим TTS стилем по умолчанию (для `notify`); TTS не готов — `RuntimeError`.
  - `streams.first_part_or_late(parts, keep_waiting, interval_s, limit_s) -> ReplyPart | None`, по пределу бросает `LateFirstPart(pending: asyncio.Task[ReplyPart | None])` — ожидание `anext` не отменено.
  - `handoffs.LATER_PHRASE`, `handoffs.Waiting.defer: Callable[[Handoff, asyncio.Task[ReplyPart | None], AsyncIterator[ReplyPart]], bool] | None` — `True`: поток взят фоновой задачей.

Поведение:
- Предел 90 с истёк, `defer` вернул `True` (включено `proactive`, колонка `supports_proactive`, есть `Announcer`) → кусок `LATER_PHRASE.format(name=target_name)` без `failure`, ход заканчивается как `ok`; поток исполнителя оркестратор при выходе **не закрывает** — он у фоновой задачи. Иначе — прежняя `TIMEOUT_PHRASE`.
- Фоновая задача: ждёт `pending`, дальше куски с `PART_IDLE_S`, общий предел `LATE_LIMIT_S` от начала хода; собирает текст ответа цели (метка стиля снимается, `clean_for_speech`); пусто, сбой или предел → событие ленты `undelivered`, вслух ничего; иначе `history.add_messages([ChatMessage("assistant", f"{name} отвечает: {text}")])` и `announcer.say(device_id хода, f"{name} отвечает: {text}", source=target_id)`. Поток закрывается в `finally`.
- `Orchestrator.drain`/`cancel_all`: фоновые задачи запоздавших ответов отменяются сразу, без ожидания.
- После хода: `listen_after_question` включено, ход `completed`, не `failed`, последнее озвученное предложение после `clean_for_speech` кончается на `?` → `await devices.listen_after(device_id, turn)`. В истории уже есть вопрос Кузи — ход по прослушиванию идёт обычным путём.
- `turn_finished`: `origin` из `Utterance.origin`.

- [ ] **Step 1: Failing tests** (`FakeDevicePort`, `FakeOllama`/поддельная сеть, малые пределы):
  - `test_late_answer_announced`: цель молчит дольше предела → сказано `LATER_PHRASE` с именем, `status == "ok"`; цель потом отвечает «Готово. Ответ сорок два.» → `announcer.say(dev, "Большая модель отвечает: Готово. Ответ сорок два.", "big")`, история содержит это сообщение.
  - `test_late_disabled_keeps_timeout_phrase`: `set_speech(False, True)` → `TIMEOUT_PHRASE`, `failed`, поток закрыт.
  - `test_late_v2_device_keeps_timeout_phrase`: `supports_proactive` False → `TIMEOUT_PHRASE`.
  - `test_late_pending_survives_setting_off`: отложили, затем `set_speech(False, …)` → ответ всё равно объявлен.
  - `test_late_target_fails_quietly`: цель упала / ничего не сказала / `LATE_LIMIT_S` → `say` не вызван, событие `undelivered`, поток закрыт.
  - `test_late_cancelled_on_drain`: `drain(0)` во время ожидания → задача отменена, поток закрыт (`aclose` вызван).
  - `test_first_part_or_late_keeps_pending`: предел → `LateFirstPart`, `pending` не отменён и потом даёт кусок.
  - `test_listen_after_question`: ответ «Какой город?» → `listen_after(dev, turn)`; «Готово.» → нет; ход прерван → нет; настройка выключена → нет.
  - `test_listen_turn_origin`: `Utterance(origin="listen")` → `turn_finished.origin == "listen"`.
  - `test_end_to_end_late_answer` в `tests/test_end_to_end.py`: поддельная колонка v3 → «долго думает» → объявление на ту же колонку.
- [ ] **Step 2: Run** — падают.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run pyright`.
- [ ] **Step 5: Commit** `feat(core): late answers are announced; listen after Kuzya's question`.

### Task 6: Ядро — очередь речи `notify/` и связка

**Files:**
- Create: `core/smartesp/notify/__init__.py`, `core/smartesp/notify/announcer.py`.
- Modify: `core/smartesp/sections.py` (раздел `speech`), `core/smartesp/wiring.py` (создание, остановка), `core/CLAUDE.md` (модуль `notify/` есть), `core/README.md`.
- Test: `core/tests/notify/test_announcer.py`, `core/tests/test_lifecycle_changes.py` (правка `speech` на лету).

**Interfaces:**
- Consumes: `DevicePort.announce/listen/supports_proactive/last_active_device` (задача 3); `Orchestrator.speech`, `set_speech`, `use_announcer` (задача 5).
- Produces: `class Announcer` (реализует `contracts.Announcer`):
  - `__init__(devices: DevicePort, speak: Callable[[str], AsyncIterator[bytes]], *, events: EventSink | None, retry_s: float = 5.0, expire_s: float = 600.0, clock=time.monotonic)`;
  - `say(device_id, text, source) -> None` — в очередь, событие не публикуется до итога;
  - `set_listen_after(on: bool) -> None`;
  - `async aclose() -> None` — отменяет доставку, очередь бросается.

Поведение: по одной доставке на колонку, порядок сохраняется. Колонка: заданная, если `supports_proactive`; иначе `last_active_device()` (если `supports_proactive`); иначе ждать. `delivered` → если текст кончается на `?` и `listen_after` включено — `devices.listen(колонка)`; `interrupted` — снято как услышанное; `busy`/`lost` — повтор через `retry_s`; не доставлено за `expire_s` — снято. Итог — событие `turn_finished` с `kind: "announcement"`, `origin: "core"`, `turn_id: "a<n>"`, `text: ""`, `answer: text`, `status`: `ok` / `interrupted` / `undelivered`, `path: [source]`.

- [ ] **Step 1: Failing tests:**
  - `test_delivered_once`: `say` → `announce` один раз, событие `ok`.
  - `test_busy_then_delivered`: `busy`, `busy`, `delivered` → три попытки через `retry_s`.
  - `test_interrupted_not_repeated`.
  - `test_expired`: всё время `lost` → после `expire_s` снято, событие `undelivered`.
  - `test_fallback_to_last_active`: заданная колонка не подключена → объявление на `last_active_device()`.
  - `test_waits_for_any_device`: колонок нет → ждёт; подключилась → доставлено.
  - `test_order_per_device`: два `say` на одну колонку — по порядку, второе после итога первого.
  - `test_question_opens_listen`: текст на `?`, `delivered` → `listen`; выключено — нет.
  - `test_aclose_cancels`: `aclose` во время доставки → задачи отменены, ничего не висит.
  - `test_speech_section_live` (lifecycle): правка `{"speech": {"listen_after_question": false}}` применяется без перезапуска.
- [ ] **Step 2: Run** — падают.
- [ ] **Step 3: Implement** модуль и связку: `wiring` создаёт `Announcer(hub, orchestrator.speech, events=bus)`, `orchestrator.use_announcer(...)`, раздел `speech` → `orchestrator.set_speech` + `announcer.set_listen_after`; остановка: `announcer.aclose()` до закрытия колонок.
- [ ] **Step 4: Run** весь набор + `ruff` + `pyright`; `uv run python -m smartesp --openapi` → обновить `ui/src/api/openapi.json` и `schema.ts` (как в прошлых планах).
- [ ] **Step 5: Commit** `feat(core): notify module — announcement queue with retries`.

### Task 7: Интерфейс — переключатели и лента

**Files:**
- Create: `ui/src/components/settings/SpeechSettings.tsx` (+ тест).
- Modify: `ui/src/components/settings/ExecutorSettings.tsx` (для входного исполнителя показывает `SpeechSettings`), `ui/src/state/actions.ts` (PATCH `speech`), `ui/src/components/feed/TurnCard.tsx`, `TurnRow.tsx`, `ui/src/components/settings/DeviceSettings.tsx`, `ui/README.md`.
- Test: `SpeechSettings.test.tsx`, `Feed.test.tsx`, `DeviceSettings` тест.

- [ ] **Step 1: Failing tests:**
  - переключатели «Кузя может заговорить сам» и «Слушать после вопроса» отражают `config.speech` и шлют `{"speech": {"proactive": false}}` / `{"speech": {"listen_after_question": false}}`; во время применения заблокированы.
  - лента: `kind: "announcement"` → строка с пометкой «сам» и текстом ответа без вопроса; `status: "undelivered"` → «не доставлено»; `origin: "listen"` → пометка «ответ на вопрос Кузи».
  - колонка с `protocol < 3` и подключена → тихая подсказка «Обновите прошивку, чтобы Кузя мог говорить сам».
- [ ] **Step 2: Run** `cd ui && npm test -- --run` — падают.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test -- --run && npm run lint && npm run build`.
- [ ] **Step 5: Commit** `feat(ui): proactive speech toggles and feed marks`.

### Task 8: Поддельная колонка v3 и живая проверка

**Files:**
- Modify: `tools/fake_device.py` — `--protocol 3`: отвечает на `announce` (играет, шлёт `playback_done`), на `listen` (шлёт звук из `--answer-wav` и `utterance_end`), `--busy` (на всё отвечает `busy`).
- Modify: `core/README.md` — как проверить вручную.

- [ ] **Step 1:** Расширить `fake_device.py`.
- [ ] **Step 2: Живая проверка** по правилам проекта (порт 8765 занят — не запускать там; копия `~/SmartEsp/config.yaml`, `config.yaml.bak`, `config.defaults.yaml` и восстановление с `cmp`; ничего не оставлять запущенным; настройки владельца не править): ядро на свободном порту, `tools/make_wav.py` делает вопрос «Спроси меня, какой мой любимый цвет» и ответ «Синий»; поддельная колонка v3 → Кузя спрашивает → приходит `listen` → ответ «Синий» → ход с `origin listen`. Записать задержки в отчёт.
- [ ] **Step 3: Commit** `test(tools): fake device speaks protocol v3`.
