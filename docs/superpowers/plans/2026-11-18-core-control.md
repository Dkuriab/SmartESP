# Ядро для приложения — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ядро умеет всё, что нужно приложению:
- ленту событий;
- применение настроек на лету;
- HTTP API с токеном;
- честную остановку и перезапуск;
- старт «сервер сразу, прогрев в фоне»;
- раздачу собранного интерфейса.

**Architecture:**
- Новые модули:
  - `events/` — шина событий и память последних ходов;
  - `control/` — состояние ядра, очередь изменений, сводка `status`;
  - `api/` — FastAPI-роутер `/api/v1`, токен, раздача `ui/dist`.
- Новые договоры в `contracts/`:
  - `events.py`;
  - `control.py` с `CorePort`, который реализует `control`, а потребляет
    `api`.
- Существующие модули получают методы подмены частей:
  - оркестратор — голос, исполнитель, обработчики, плюс события хода;
  - хаб — имена, сведения о колонках, события, остановка;
  - история — пределы;
  - `tts` — менеджер голосов с фоновым скачиванием;
  - `executors` — выгрузка модели и список моделей;
  - `config` — хранилище изменений владельца.
- `main.py` остаётся связкой: собирает части через реестры и отдаёт
  `control` тройки «собрать / подменить / освободить» по разделам настроек.

**Tech Stack:**
- Python 3.12, asyncio;
- FastAPI 0.163.2 и uvicorn 0.54.0 (уже стоят);
- httpx для тестов API (`ASGITransport`), `starlette.testclient` для
  WebSocket.

Новых зависимостей нет.

**Spec:** `docs/superpowers/specs/2026-11-18-app-voices-design.md`:
- разделы 5.2–5.6;
- раздел 5.1 — фоновое скачивание голоса при старте;
- разделы 6, 8.

Правила — `core/CLAUDE.md`.

## Global Constraints

- Все команды запускаются из `core/`.
- Перед каждым коммитом зелёные:
  - `uv run pytest`;
  - `uv run ruff check`;
  - `uv run ruff format --check`;
  - `uv run pyright`.
- Модули импортируют только `smartesp.contracts`. В `contracts` — только
  dataclass'ы и протоколы, без логики, pyright strict. `main.py` — только
  связка.
- Размеры: файл ≤ 300 строк, функция ≤ 50 строк, сложность ≤ 10. Имена —
  по-английски, комментарии и docstring'и — по-русски.
- Тесты — на подделках из `core/fakes/`, без сети, моделей и Ollama.
- Коммиты:
  - по-английски;
  - заканчиваются строкой
    `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - пушим сразу в `main`.
- Значения из дизайна:
  - лента хранит **100** последних ходов в памяти;
  - звучащим ответам при остановке даётся **10 с**;
  - выгрузка модели из Ollama ждёт не больше **1 с**;
  - вся остановка — не дольше **15 с**;
  - прогрев новой модели — до **120 с** (`WARM_UP_TIMEOUT_S`);
  - повторы скачивания голоса при старте — через **30 с, 2 мин, 5 мин**,
    дальше каждые 5 мин.
- Разделы настроек:
  - **На лету:** `devices`, `tts`, `executors`, `stages`, `history`.
  - **Требуют перезапуска:** `server`, `stt`, `arbitration`.
- Токен:
  - лежит в `<data>/token`, права `0600`;
  - `secrets.token_urlsafe(32)`;
  - HTTP — `Authorization: Bearer <token>`;
  - WebSocket — `?token=<token>`;
  - нужен и с `127.0.0.1`;
  - `/device` — без токена.
- Файл запуска `<data>/run/core.json`:
  - содержит `{"port": int, "pid": int, "started_at": float}`;
  - пишется сразу после подъёма сервера;
  - удаляется при остановке.
- Состояния ядра: `warming`, `ready`, `stopping`.

### Имена событий (на них опирается план интерфейса — не менять)

Событие — `CoreEvent(kind: str, data: dict[str, object], at: float)`, где
`at` — `time.time()`. По WebSocket уходит JSON
`{"kind": …, "data": {…}, "at": …}`.

| kind | data |
|---|---|
| `core_state` | `state` |
| `device_connected` | `device_id`, `name`, `remote`, `fw` |
| `device_disconnected` | `device_id` |
| `wake` | `device_id`, `level` |
| `arbitration` | `device_id`, `decision` (`accept` или `cancel`) |
| `turn_started` | `turn_id`, `device_id`, `device_name` |
| `turn_heard` | `turn_id`, `text`, `stt_ms` |
| `turn_finished` | см. ниже |
| `change_applied` | `change_id`, `ok`, `error`, `sections` |
| `voice_download` | `kind`, `voice`, `done`, `total` |
| `voice_ready` | `kind`, `voice`, `ok`, `error` |

`turn_finished` несёт поля:
- `turn_id`, `device_id`, `device_name`;
- `text`;
- `annotations` — список `{source, text}`;
- `style`, `answer`;
- `status` — `ok`, `error`, `interrupted` или `meaningless`;
- `stt_ms`, `first_text_ms`, `first_audio_ms` (каждое — число или `null`).

### Ресурсы API (на них опирается план интерфейса — не менять)

Все пути начинаются с `/api/v1`, все требуют токен.

- **`GET /status`** →
  - `version`, `uptime_s`, `state`;
  - `ollama {reachable, loaded: [str]}`;
  - `devices` — список `{device_id, name, connected, remote, fw, last_seen}`;
  - `voice {kind, voice, state: ready|downloading|failed|missing, error}`;
  - `applying: bool`, `restart_required: bool`.
- **`GET /config`** →
  - `effective` — настройки целиком, как `config.yaml`;
  - `overridden` — ключи через точку, например `tts.kind`;
  - `restart_sections`.
- **`PATCH /config`**:
  - тело — частичный словарь в форме `config.yaml`;
  - словари сливаются вглубь;
  - списки заменяются целиком;
  - `null` сбрасывает ключ к умолчанию.

  Ответ — `{change_id, status, error}`:
  - `status: accepted` или `restart_required` — HTTP 200;
  - ошибка проверки — HTTP 422 и `status: invalid`.
- **`GET /models`** → список `{name, size_bytes}`.
- **`GET /voices`** → список `{kind, voice, title, size_mb, downloaded, current}`.
- **`POST /voices/download`** `{kind, voice}` → `{change_id, status: "accepted"}`.
- **`POST /voices/preview`** `{kind, voice, style="normal", text=null}` →
  `audio/wav` (16 кГц, 16 бит, моно).
  - Голос не скачан → 409.
  - Текст по умолчанию: «Привет! Я буду отвечать этим голосом.»
- **`GET /turns?limit=100`** → список `data` событий `turn_finished`, от новых
  к старым.
- **`POST /restart`** → 202.
- **`WS /events?token=`** → поток событий. Неверный токен → закрытие с кодом
  4401.

## Review Focus

1. **Голос или модель меняются, пока звучит ответ.** Звучащий ход
   договаривает старыми частями, следующий берёт новые. Старая модель
   выгружается только после конца хода. Тест — в задаче 2 (оркестратор) и в
   задаче 7 (`control`).
2. **Новое изменение приходит, пока применяется прошлое** (два быстрых
   `PATCH`). Изменения применяются по очереди, ни одно не теряется, в
   `config.yaml` — последнее успешное. Тест — в задаче 7.
3. **Медленный или отключившийся подписчик ленты.** Шина не копит память без
   конца и не тормозит ход: у очереди подписчика есть предел, старые события
   выбрасываются. Тест — в задаче 1.
4. **`wake` во время прогрева или остановки.** Колонка получает сигнал
   ошибки и пустой ответ, а не тишину. Тест — в задаче 2.
5. **Неверный или отсутствующий токен, токен в чужом формате, WebSocket без
   токена.** Ответ 401 или 4401, без утечки текста ошибки. Тест — в задаче 8.

---

### Task 1: События — договор и шина

**Files:**
- Create: `core/smartesp/contracts/events.py`; экспорт в
  `contracts/__init__.py`
- Create: `core/smartesp/events/__init__.py`, `core/smartesp/events/bus.py`
- Create: `core/fakes/fake_events.py`
- Test: `core/tests/events/test_bus.py`

**Interfaces:**
- Produces (`contracts`):
  - `@dataclass(frozen=True) class CoreEvent: kind: str; data: dict[str, object]; at: float`;
  - `class EventSink(Protocol): def publish(self, kind: str, data: dict[str, object]) -> None`;
  - `class EventFeed(Protocol)` с двумя методами:
    - `def subscribe(self) -> AsyncIterator[CoreEvent]`;
    - `def recent_turns(self, limit: int) -> list[dict[str, object]]`.
- Produces (`events`): `EventBus(max_turns: int = 100, queue_size: int = 1000, clock=time.time)` реализует оба протокола.
- Produces (`fakes`): `RecordingSink` с полем
  `events: list[tuple[str, dict[str, object]]]`.

- [ ] **Step 1: Написать падающие тесты** в `tests/events/test_bus.py`:
  - `test_subscriber_gets_events_in_order` — два `publish` → подписчик
    получает оба в том же порядке.
  - `test_publish_never_blocks_and_drops_oldest` — подписчик ничего не
    читает, опубликовано `queue_size + 5` событий → `publish` ни разу не
    ждал, а в очереди последние `queue_size` событий.
  - `test_unsubscribe_on_exit` — после выхода из `async for` подписчиков 0.
  - `test_recent_turns_keeps_last_100_newest_first` — 105 событий
    `turn_finished` → `recent_turns(100)` отдаёт 100, первым — `turn_id=105`;
    `recent_turns(3)` отдаёт три.
  - `test_publish_without_subscribers_is_fine`.

- [ ] **Step 2: Запустить.** `uv run pytest tests/events -v` → FAIL.

- [ ] **Step 3: Реализовать.**
  - Подписка — асинхронный генератор с `asyncio.Queue(maxsize=queue_size)`.
    При переполнении: `get_nowait()`, потом `put_nowait()`.
  - Память ходов — `deque(maxlen=max_turns)` из `data` событий
    `turn_finished`.
  - `publish` синхронный, вызывается из цикла событий.

- [ ] **Step 4: Запустить.** `uv run pytest tests/events -v` → PASS, плюс полный
  прогон.

- [ ] **Step 5: Commit** `feat(core): event bus with bounded subscribers and recent turns`.

### Task 2: Оркестратор — подмена частей, «не готов» и события хода

**Files:**
- Modify: `core/smartesp/conversation/orchestrator.py`,
  `core/smartesp/conversation/history.py`
- Modify (если нужно): `core/tests/conversation/conversation_helpers.py`
- Test: `core/tests/conversation/test_live_parts.py`,
  `core/tests/conversation/test_turn_events.py`,
  `core/tests/conversation/test_history.py`

**Interfaces:**
- Consumes: `EventSink`, `RecordingSink` (задача 1).
- Produces:
  - `Orchestrator(devices, stt: SpeechToText | None, analyze: Analyzer | None, executor: Executor | None, tts: TextToSpeech | None, history, *, events: EventSink | None = None, ...)`.
    Прежний порядок аргументов сохраняется, вместо любой части можно передать
    `None`.
  - Методы оркестратора:
    - `use_stt(stt)`;
    - `use_tts(tts)`;
    - `use_executor(executor)`;
    - `use_analyzer(analyze)`;
    - `ready -> bool` — все четыре части заданы;
    - `stop_accepting()` — новые ходы получают сигнал ошибки и пустой
      ответ;
    - `async drain(timeout_s: float) -> None` — ждёт идущие ходы до
      `timeout_s`, затем отменяет их.
  - `History.set_limits(max_turns: int, max_age_s: float) -> None` —
    сохраняет последние ходы, которые влезают.

- [ ] **Step 1: Написать падающие тесты.**
  - `test_running_turn_keeps_old_tts`:
    1. первый ход стартует;
    2. пока исполнитель отдаёт куски, вызывается `use_tts(new)`;
    3. все предложения этого хода озвучены старым TTS;
    4. следующий ход озвучен новым.
  - То же для исполнителя: `test_running_turn_keeps_old_executor`.
  - `test_not_ready_turn_gets_error_tone` — оркестратор без `executor` →
    `tones == [(device, "error")]`, отыграно одно пустое воспроизведение,
    STT не вызывался.
  - `test_stop_accepting_rejects_new_turns`.
  - `test_drain_waits_then_cancels` — ход, который длится 0,2 с, при
    `drain(1.0)` заканчивается сам; ход, который висит, при `drain(0.1)`
    отменяется.
  - `test_turn_events_sequence` — `RecordingSink` получает:
    1. `turn_started`;
    2. `turn_heard` с `text`;
    3. `turn_finished` со `status="ok"`, `answer`, `style`, `annotations`
       в виде `[{"source":…, "text":…}]` и тремя задержками.
  - `turn_finished` со `status="error"` при ошибке исполнителя и
    `"meaningless"` при бессмысленном тексте.
  - `test_set_limits_keeps_newest` в `test_history.py`.

- [ ] **Step 2: Запустить.** Новые тесты → FAIL, прежние → PASS.

- [ ] **Step 3: Реализовать.**
  - Ход в начале `_handle` делает снимок частей: локальная
    `dataclass(frozen=True) _Parts(stt, analyze, executor, tts)`. Дальше по
    ходу используется только снимок, а `self._tts` и прочие внутри хода не
    читаются.
  - Ход при `not ready` или после `stop_accepting` идёт через `_recover`
    (сигнал ошибки и пустой ответ) и даёт событие
    `turn_finished(status="error")`.
  - `status` для события: `failed` → `error`, `meaningless` → `meaningless`,
    `completed` → `ok`, иначе `interrupted`.

- [ ] **Step 4: Запустить.** Полный прогон → PASS.

- [ ] **Step 5: Commit**
  `feat(core): orchestrator swaps parts between turns and publishes turn events`.

### Task 3: Хаб — сведения о колонках, имена, события, остановка

**Files:**
- Modify: `core/smartesp/contracts/device.py` (добавить `DeviceInfo`),
  `contracts/__init__.py`
- Modify: `core/smartesp/devices/hub.py`. Если файл вырастет больше 300 строк,
  вынести сведения о колонках в `devices/registry.py`.
- Test: `core/tests/devices/test_hub_info.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class DeviceInfo: device_id: str; name: str; connected: bool; remote: str; fw: str; last_seen: float | None`.
  - `DeviceHub(..., events: EventSink | None = None)`.
  - Методы хаба:
    - `set_names(names: dict[str, str])`;
    - `devices() -> list[DeviceInfo]` — подключённые плюс известные по
      именам из настроек, но не подключённые; отсортированы по имени;
    - `stop_accepting()` — новые `wake` сразу отменяются через
      `cancel_turn`;
    - `async close_all()` — закрывает все соединения.

- [ ] **Step 1: Написать падающие тесты** на поддельных соединениях из
  `tests/devices/hub_helpers.py`:
  - `devices()` после `hello` с `fw="0.2.0"`: колонка подключена, есть
    `remote` и `last_seen`;
  - после отключения — `connected=False` и прежний `fw`;
  - колонка из `names`, которая не подключалась, есть в списке с
    `connected=False`, `fw=""`, `last_seen=None`;
  - `set_names` меняет `device_name()` и `devices()`;
  - события: `device_connected`, `device_disconnected`, `wake` (с
    `level`), `arbitration` (`accept`, `cancel`);
  - после `stop_accepting()` `wake` получает `cancel_turn`, а вопрос не
    попадает в `next_utterance`;
  - `close_all()` закрывает каждое соединение.

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  **Step 4: Запустить** полный прогон → PASS.

- [ ] **Step 5: Commit**
  `feat(core): hub device info, live names, events and shutdown hooks`.

### Task 4: Хранилище настроек

**Files:**
- Create: `core/smartesp/config/store.py`; экспорт в `config/__init__.py`.
  Повторно использовать `_prune` и `_write_overrides` из `loader.py`
  (перенести в общий внутренний модуль пакета, если так чище).
- Test: `core/tests/config/test_store.py`

**Interfaces:**
- Produces: `ConfigFile(path: Path)`.
  - `load() -> Config` — то же, что `load_config`, включая перевод старого
    формата. Попутно поправить `load_config`: переводить только `version`
    отсутствует или `2`. Версия больше текущей или не число — `ValueError`
    «файл настроек от более новой версии ядра», файл не трогать. Тест на
    это.
  - `config -> Config` — текущие настройки.
  - `effective() -> dict[str, Any]` — `model_dump(mode="json")`.
  - `overridden() -> list[str]` — ключи через точку из файла изменений, без
    `version`. Внутрь списков не заходим: `executors` — один ключ.
  - `merge(patch: dict[str, Any]) -> Config` — сливает с текущими
    изменениями владельца по правилам `PATCH`. Ничего не пишет; неверно —
    `ValueError` с понятным текстом.
  - `save(config: Config) -> None` — пишет только отличия от умолчаний,
    атомарно (временный файл и `replace`), и запоминает их как текущие.

- [ ] **Step 1: Написать падающие тесты.**
  - Слияние вглубь:
    `{"devices": {"AA:…": {"name": "Кухня"}}}` → имя есть, прочие колонки
    на месте.
  - Список заменяется целиком: `{"stages": []}`.
  - `null` сбрасывает: `{"tts": null}` после `save` → в файле нет `tts`,
    `config.tts` по умолчанию.
  - Неверное значение (`{"server": {"port": "x"}}`) → `ValueError`, файл не
    тронут.
  - `overridden()` после сохранения `tts.kind` — `["tts.kind"]`.
  - `save` атомарна: после записи нет временного файла, а повторный
    `ConfigFile(path).load()` отдаёт то же самое.

- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS (полный прогон).**

- [ ] **Step 5: Commit** `feat(core): config store with deep-merge patches and atomic save`.

### Task 5: Ollama — выгрузка модели и список моделей

**Files:**
- Modify: `core/smartesp/executors/ollama_executor.py`
- Create: `core/smartesp/executors/ollama_models.py`; экспорт в
  `executors/__init__.py`
- Test: `core/tests/executors/test_ollama_models.py`, дополнить
  `test_ollama_executor.py`

**Interfaces:**
- Produces:
  - `OllamaExecutor.unload(timeout_s: float = 1.0) -> Awaitable[None]` —
    `generate(model, prompt="", keep_alive=0)`. Любая ошибка или таймаут —
    предупреждение в журнал, не исключение.
  - `OllamaExecutor.model -> str`.
  - `async list_models(client=None) -> list[tuple[str, int]]` — имя и
    размер в байтах. Ошибка → `ExecutorError`.
  - `async loaded_models(client=None) -> list[str]` — через `ps()`. Ошибка →
    `ExecutorError`.

- [ ] **Step 1: Написать тесты** с подделкой клиента (как в
  `test_ollama_executor.py`):
  - `unload` шлёт `keep_alive=0`;
  - `unload` при ошибке и при зависании клиента (`asyncio.sleep(10)`)
    выходит за ~1 с без исключения;
  - `list_models` разбирает ответ `list()`, и объектом, и словарём;
  - `loaded_models` разбирает `ps()`;
  - ошибка сети → `ExecutorError`.

- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS.**

- [ ] **Step 5: Commit** `feat(core): Ollama model unload and model listing`.

### Task 6: Менеджер голосов — фоновое скачивание, запасной голос, образец

**Files:**
- Create: `core/smartesp/tts/manager.py`; экспорт в `tts/__init__.py`
- Test: `core/tests/tts/test_manager.py`

**Interfaces:**
- Consumes:
  - `catalog`, `is_downloaded`, `download_voice` (`progress`),
    `VoiceDownloadError` — из плана голосов;
  - `EventSink`.
- Produces (`contracts/tts.py`): `class VoiceNotDownloadedError(Exception)` —
  нужен API для ответа 409, поэтому лежит в договорах.
- Produces:
  `VoiceManager(home: Path, factories: Mapping[str, Callable[[Path, str], TextToSpeech]], on_ready: Callable[[TextToSpeech, str, str], None], *, events: EventSink | None = None, download=download_voice, retry_delays_s: Sequence[float] = (30, 120, 300))`.
  - `factories[kind](voice_path, voice) -> TextToSpeech`; фабрики приходят из
    `main.py`.
  - `async open(kind, voice, *, retry: bool) -> bool`:
    - голос скачан → собрать в потоке, прогреть, вызвать `on_ready`;
    - не скачан → сразу собрать и отдать в `on_ready` запасной голос (первый
      скачанный из `catalog`), если он есть;
    - запустить фоновое скачивание нужного с событиями `voice_download` и
      повторами по `retry_delays_s` (последняя задержка повторяется);
    - после успеха собрать, прогреть, вызвать `on_ready` и дать событие
      `voice_ready(ok=True)`.

    Новый вызов `open` отменяет прежнее фоновое скачивание.

    Возвращает `True`, когда нужный голос стал текущим. `False` — если
    скачивание не удалось при `retry=False` (так делает изменение из
    приложения). При `retry=True` повторяет, пока не получится (так делает
    старт ядра; `main` запускает его фоновой задачей).
  - `async download(kind, voice) -> None` — одно фоновое скачивание с
    событиями, без подмены голоса.
  - `async preview(kind, voice, style, text) -> bytes`:
    - возвращает WAV-файл 16 кГц моно;
    - голос не скачан → `VoiceNotDownloadedError`;
    - один экземпляр TTS для образцов держится в кеше: последний
      запрошенный, кроме текущего.
  - `state() -> dict` — `{kind, voice, state, error}`, где `state` —
    `ready`, `downloading`, `failed` или `missing`.
  - `async aclose()` — отменяет фоновые задачи.
  - `catalog() -> list[VoiceInfo]` с отметкой текущего.

- [ ] **Step 1: Написать тесты** с поддельными фабриками и поддельным
  `download` (без сети):
  - скачанный голос сразу приходит в `on_ready`, состояние `ready`;
  - нескачанный голос при скачанной Ирине:
    1. `on_ready(piper, irina)` сразу;
    2. затем после поддельного скачивания `on_ready(silero, xenia)`;
    3. события `voice_download` и `voice_ready`;
  - нескачанный голос, запасных нет, скачивание падает дважды, потом
    удаётся (`retry=True`, `retry_delays_s=(0.01,)`) → состояние
    `downloading` → `ready`, `on_ready` вызван один раз, `open` вернул
    `True`;
  - `retry=False`, скачивание падает → `open` вернул `False`, состояние
    `failed` с текстом ошибки, `on_ready` для нового голоса не вызывался;
  - новый `open` отменяет прежнее скачивание: поддельное скачивание
    получает отмену, и прежний голос не приходит в `on_ready`;
  - `preview` отдаёт корректный WAV (`wave.open`: 1 канал, 16000 Гц, 2
    байта), для нескачанного — `VoiceNotDownloadedError`;
  - `aclose` не оставляет задач.

- [ ] **Step 2: FAIL. Step 3: Реализовать.**
  - Сборка и прогрев голоса — в потоке.
  - Скачивание вызывает синхронный `download_voice` через
    `asyncio.to_thread`. `progress` перекладывается в событие через
    `loop.call_soon_threadsafe`.
  - Отмена: поток скачивания не прерывается, но его результат
    игнорируется.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit**
  `feat(core): voice manager with background download, fallback and preview`.

### Task 7: Пульт — состояние, очередь изменений, сводка

**Files:**
- Create: `core/smartesp/contracts/control.py`; экспорт
- Create: `core/smartesp/control/__init__.py`, `core/smartesp/control/core.py`,
  `core/smartesp/control/changes.py`
- Test: `core/tests/control/test_changes.py`, `core/tests/control/test_status.py`

**Interfaces:**
- Produces (`contracts/control.py`):
  - `@dataclass(frozen=True) class ChangeResult: change_id: int; status: str; error: str = ""` —
    `status`: `accepted`, `restart_required` или `invalid`.
  - `@dataclass(frozen=True) class Section` — сборщик одного раздела
    настроек:
    - `build: Callable[[Any], Awaitable[object]]` — собирает новую часть из
      настроек;
    - `swap: Callable[[object], object | None]` — подменяет часть и
      возвращает старую;
    - `release: Callable[[object], Awaitable[None]] | None = None`.
  - `class ConfigStore(Protocol)`:
    - `effective() -> dict[str, Any]`;
    - `overridden() -> list[str]`;
    - `merge(patch) -> Any`;
    - `save(config: Any) -> None`;
    - `section(config: Any, name: str) -> object` — значение раздела для
      сравнения.

    Реализуется `ConfigFile` из задачи 4. Если удобнее, добавить `section`
    туда.
  - `class CorePort(Protocol)` — все методы, которые нужны API:
    - `status() -> dict[str, Any]` (async);
    - `config() -> dict[str, Any]`;
    - `patch_config(patch) -> ChangeResult` (async);
    - `models() -> list[dict[str, Any]]` (async);
    - `voices() -> list[dict[str, Any]]`;
    - `download_voice(kind, voice) -> ChangeResult` (async);
    - `preview(kind, voice, style, text) -> bytes` (async);
    - `turns(limit) -> list[dict[str, object]]`;
    - `request_restart() -> None`.
- Produces (`control`):
  `Core(store: ConfigStore, sections: Mapping[str, Section], *, events: EventSink, feed: EventFeed, voices: VoicePort, models: Callable[[], Awaitable[list[tuple[str, int]]]], loaded: Callable[[], Awaitable[list[str]]], devices: Callable[[], list[DeviceInfo]], version: str, clock=time.monotonic)`
  реализует `CorePort`.
  - `VoicePort(Protocol)` в `contracts/control.py` — то, что `Core` берёт у
    `VoiceManager`:
    - `catalog()`;
    - `state()`;
    - `async open(kind, voice, *, retry)`;
    - `async download(kind, voice)`;
    - `async preview(kind, voice, style, text)`.
  - Методы: `set_state(state)`, `state`, `restart_requested -> bool`,
    `async wait_restart()`, `async aclose()`.
  - `RESTART_SECTIONS = ("server", "stt", "arbitration")`.
  - Раздел `tts` применяется не через `Section`, а через
    `await voices.open(kind, voice, retry=False)`. Голос подменяет `on_ready`
    менеджера. `True` → `save` и `change_applied(ok=True)`. `False` →
    `change_applied(ok=False, error=voices.state()["error"])`, `save` не
    вызывается.

- [ ] **Step 1: Написать тесты** с поддельными `Section` (сборщик ждёт
  событие и может падать), поддельным хранилищем и `RecordingSink`:
  - `patch_config` сразу отвечает `accepted` с растущим `change_id`. Затем
    по порядку:
    1. `build`;
    2. `swap`;
    3. `release` старого — после `swap`;
    4. `store.save`;
    5. `change_applied(ok=True, sections=[…])`.
  - Сбой `build` → `swap` и `save` не вызваны, `change_applied(ok=False,
    error=…)`.
  - Два `PATCH` подряд: второй ждёт первый, оба применены по порядку, в
    `save` последнее.
  - Изменились только `server` → `restart_required`, `save` вызван, `build`
    не вызывался, `status()["restart_required"] is True`.
  - Неверный патч (`merge` бросает `ValueError`) → `invalid` с текстом,
    `save` не вызван.
  - Разделы, значение которых не изменилось, не пересобираются.
  - `status()` собирает версию, `uptime_s`, `state`, `ollama.reachable`
    (сбой `loaded` → `False`, `loaded=[]`), колонки, голос и `applying`.
  - `request_restart()` → `wait_restart()` завершается.

- [ ] **Step 2: FAIL. Step 3: Реализовать.**
  - Очередь изменений: `asyncio.Queue` и одна рабочая задача.
  - `changes.py` — сравнение разделов и применение; `core.py` — сводка и
    фасад.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit** `feat(core): control core — live change queue, status and restart request`.

### Task 8: API — роутер, токен, раздача интерфейса

**Files:**
- Create: `core/smartesp/api/__init__.py`, `core/smartesp/api/routes.py`,
  `core/smartesp/api/auth.py`, `core/smartesp/api/schemas.py`,
  `core/smartesp/api/ui.py`
- Test: `core/tests/api/test_api.py`, `core/tests/api/test_events_ws.py`,
  `core/tests/api/test_token.py`
- Create: `core/fakes/fake_core.py` — поддельный `CorePort`

**Interfaces:**
- Consumes: `CorePort`, `EventFeed`, `ChangeResult`.
- Produces:
  - `load_or_create_token(home: Path) -> str` — файл `<home>/token`, права
    `0600`. Уже есть — читается без изменений.
  - `create_api(core: CorePort, feed: EventFeed, token: str) -> APIRouter`
    с префиксом `/api/v1`, ресурсы — как в Global Constraints.
  - `mount_ui(app: FastAPI, ui_dir: Path) -> None` — `StaticFiles(html=True)`
    на `/`, если есть `ui_dir/index.html`. Иначе на `/` отдаётся простая
    страница: «Интерфейс не собран: `cd ui && npm ci && npm run build`».
  - Ответы описаны pydantic-моделями в `schemas.py`, чтобы OpenAPI был
    точным для генерации клиента.

- [ ] **Step 1: Написать тесты** через `httpx.AsyncClient(transport=ASGITransport(app))`
  и `starlette.testclient.TestClient` для WebSocket:
  - без заголовка, с неверным токеном и с `Bearer` без значения → 401,
    `{"detail": "unauthorized"}`;
  - с токеном `GET /status` отдаёт то, что вернул `FakeCore`;
  - `PATCH /config` → 200 `accepted`, неверный патч → 422 `invalid` с
    текстом;
  - `POST /voices/preview`: голос не скачан → 409, иначе `audio/wav`;
  - `GET /turns?limit=2` → два элемента;
  - `POST /restart` → 202 и вызов `request_restart`;
  - WebSocket: без токена → закрытие 4401; с токеном — получает событие,
    опубликованное в `EventBus`, в формате `{"kind","data","at"}`;
  - `/` без `ui/dist` → страница с командой сборки; с временной папкой, где
    есть `index.html`, → её содержимое;
  - `load_or_create_token` создаёт файл с правами `0o600` и второй раз
    возвращает тот же токен.

- [ ] **Step 2: FAIL. Step 3: Реализовать.**
  - Токены сравниваются через `secrets.compare_digest`.
  - `/device` в этот роутер не входит.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit** `feat(core): HTTP API v1 with token auth, events WebSocket and UI serving`.

### Task 9: Связка — старт, честная остановка, перезапуск

**Files:**
- Modify: `core/smartesp/main.py`. Если файл вырастет больше 300 строк,
  разнести связку на `main.py` (реестры и `main()`) и `wiring.py` (сборка
  частей и разделов), оба без своей логики.
- Modify: `core/smartesp/__main__.py`
- Delete: `ensure_voice` и `VoiceUnavailableError` из `core/smartesp/tts/`
  вместе с их тестами. Их место заняли `VoiceManager.open` и фоновый старт.
- Test: `core/tests/test_main.py`, `core/tests/test_lifecycle.py`

**Interfaces:**
- Consumes: всё выше.
- Produces:
  - Флаги командной строки:
    - `python -m smartesp [--parent-watch] [--openapi PATH]`;
    - `--openapi` пишет схему OpenAPI в файл и выходит, ядро не стартует.
  - Последовательность старта:
    1. журнал;
    2. `ConfigFile.load()`;
    3. проверка видов через реестры — неизвестный вид означает
       `StartupError`, как сейчас;
    4. `EventBus`, `DeviceHub`, `History`, `Orchestrator` без частей,
       `VoiceManager`, `Core`;
    5. токен, приложение FastAPI: `/device`, `create_api`, `mount_ui`;
    6. `uvicorn.Server`;
    7. сразу после `server.started` — `run/core.json`;
    8. фоновая задача прогрева:
       - STT (`use_stt`);
       - обработчики (`use_analyzer`);
       - исполнитель с правилами обработчиков (`use_executor`, прогрев до
         120 с);
       - `voices.open(tts.kind, tts.voice, on_ready=…)`;
       - затем `core.set_state("ready")`.
  - `Section` для `devices`, `executors`, `stages`, `history` — тройки из
    существующих фабрик:
    - сборщик исполнителя прогревает модель;
    - `release` вызывает `unload`, если модель другая;
    - `stages` пересобирает и обработчики, и исполнителя, потому что меняются
      правила промпта.
  - Остановка — подкласс `uvicorn.Server`, у которого `handle_exit` при
    первом сигнале запускает честную остановку:
    1. `core.set_state("stopping")`;
    2. `hub.stop_accepting()`, `orchestrator.stop_accepting()`;
    3. `await orchestrator.drain(10)`;
    4. `await hub.close_all()`;
    5. `executor.unload(1.0)`;
    6. `voices.aclose()`;
    7. удалить `run/core.json`;
    8. `server.should_exit = True`.

    Второй сигнал — `force_exit`.
  - Ещё два способа запустить ту же остановку:
    - `--parent-watch`: поток читает stdin до EOF и запускает остановку
      через `loop.call_soon_threadsafe`;
    - `core.wait_restart()`: та же остановка, затем после выхода из
      `asyncio.run` — `os.execv(sys.executable, [sys.executable, "-m", "smartesp", *sys.argv[1:]])`.
  - Код выхода 0.

- [ ] **Step 1: Написать тесты.**
  - `test_lifecycle.py`, ядро собирается на подделках через функцию сборки
    из `main.py` и `httpx` с `ASGITransport`:
    - сразу после старта `GET /api/v1/status` → `state="warming"`; после
      прогрева подделок → `ready`;
    - `wake` до готовности → сигнал ошибки;
    - честная остановка: идущий ход договаривает, новый `wake` получает
      `cancel_turn`, вызван `unload`, `core.json` удалён, всё укладывается
      в 15 с (на подделках — в 1 с);
    - `--parent-watch`: закрытие поддельного stdin запускает остановку;
    - `--openapi PATH` пишет JSON, в `paths` которого есть
      `/api/v1/status`.
  - Поправить `test_main.py` под новую сборку: реестры и `StartupError` на
    неизвестный вид остаются.

- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS**, полный прогон.

- [ ] **Step 5: Проверка вживую.** При запущенной Ollama:
  1. `uv run python -m smartesp`;
  2. `curl -H "Authorization: Bearer $(cat ~/SmartEsp/token)" localhost:8765/api/v1/status`
     → сначала `warming`, потом `ready`;
  3. `PATCH /api/v1/config` с телом `{"tts":{"kind":"vosk","voice":"female_1"}}`
     → `accepted`, затем в журнале «применено»;
  4. `tools/fake_device.py` → ответ голосом Vosk;
  5. вернуть `{"tts": null}`;
  6. `kill -TERM <pid>` → в журнале шаги остановки, `run/core.json` удалён,
     `ollama ps` без модели диспетчера;
  7. отдельно `POST /api/v1/restart` → ядро поднимается снова с тем же pid.

- [ ] **Step 6: Commit**
  `feat(core): serve first, warm up in background, graceful stop and restart`.

### Task 10: Документация

**Files:**
- Modify: `core/README.md`:
  - разделы «Приложение и API»: токен, `run/core.json`, `/api/v1`,
    `--openapi`;
  - «Остановка и перезапуск»;
  - «Настройки» — что меняется на лету, а что требует перезапуска.
- Modify: `core/CLAUDE.md` — структура: `events/`, `control/`, `api/`.

- [ ] **Step 1: Написать и сверить с кодом** (имена ресурсов, файлов,
  флагов).

- [ ] **Step 2: Commit** `docs(core): API, live settings and lifecycle`.
