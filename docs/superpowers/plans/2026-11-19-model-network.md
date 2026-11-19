# Сеть моделей — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** диспетчер передаёт задачу другому исполнителю инструментом `delegate`,
выбирая цель по условию «когда вызывать» на связи. Ответ цели звучит в том же
ходе, пока она думает — звучит «думаю». Исполнители и связи с условиями видны и
настраиваются в приложении.

**Architecture:**
- **Договоры.** `Executor.run` получает необязательные инструменты.
  `ReplyPart` несёт вызов инструмента, отметку передачи (`Handoff`) и признак
  «служебная фраза об ошибке».
- **Новый модуль `network/`.** «Сеть исполнителей» реализует договор
  `Executor`:
  - строит инструмент и правило из связей;
  - перехватывает `delegate`, отдаёт `Handoff` и затем куски ответа цели;
  - держит глубину и подставляет фразы об ошибках;
  - делает страховку «фраза без вызова».
- **Оркестратор** на `Handoff`:
  - пишет путь;
  - ждёт первый кусок цели с «думаю» и пределом 90 с;
  - разрешает метку стиля в начале ответа цели.
- **Связка** собирает сеть из настроек через реестры.
- **`LiveAnswering`** работает с наборами моделей: выгружает модели, которые
  больше не нужны, и греет остальных исполнителей в фоне.
- **Интерфейс:**
  - колонка исполнителей на схеме, условия на стрелках;
  - путь хода по `path`;
  - настройки исполнителя со связями;
  - метка передачи в ленте.

**Tech Stack:**
- Python 3.12, `ollama` 0.6.3 (`tools`, `tool_calls`, `show().capabilities`);
- TypeScript + React + `@xyflow/react` (уже стоят).

Новых зависимостей нет.

**Spec:** `docs/superpowers/specs/2026-11-19-model-network-design.md` — весь
документ, особенно 5.1–5.6 и 6а. Правила: `core/CLAUDE.md`, `ui/CLAUDE.md`.

## Global Constraints

- Ядро:
  - модули импортируют только `smartesp.contracts`;
  - `main.py` и `wiring.py` — без логики;
  - файл ≤ 300 строк, функция ≤ 50 строк, сложность ≤ 10;
  - pyright strict для `contracts`;
  - проверки: `uv run pytest`, `ruff check`, `ruff format --check`,
    `pyright` из `core/`.

  `conversation/orchestrator.py` (297) и `wiring.py` (300) уже на пределе:
  новое выносить в отдельные файлы того же модуля.
- Интерфейс:
  - проверки: `npm run typecheck && npm run lint && npm test -- --run && npm run build`
    из `ui/`, без предупреждений;
  - после изменения API ядра — `npm run api`;
  - тексты по-русски, только переменные темы.
- Коммиты:
  - по-английски;
  - заканчиваются строкой
    `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - пушим сразу в `main`.
- Значения из дизайна:
  - предел первого куска после передачи — **90 с**
    (`DELEGATE_FIRST_PART_LIMIT_S = 90.0`);
  - пауза между кусками — 20 с, как сейчас;
  - «думаю» — каждые 8 с, как сейчас;
  - глубина передачи — **2**;
  - `TURN_WAIT_S` — **150 с**;
  - `keep_alive` по умолчанию — `24h`;
  - фразы (фраза вместо сигнала ошибки: прозвучала — тона ошибки нет):
    - «Не успела ответить, спроси попозже.»
    - «<Имя> сейчас не отвечает.» — цель недоступна или ничего не сказала
- Связь «фраза без вызова» срабатывает так:
  - короткий ответ — одно предложение, не длиннее 80 символов;
  - в нём имя ровно одной активной цели;
  - сравнение без регистра, по основе слова: первые `max(4, len(w) - 2)`
    символов каждого слова имени;
  - id цели, стоящий во фразе отдельным словом, тоже считается названием;
  - вызов `delegate` без фразы: ядро говорит «Минутку, сейчас узнаю.» само.
- Исполнитель по умолчанию `big`:
  - `name`: «Большая модель»;
  - `model`: `deepseek-r1:8b`;
  - `description`: «большая модель: рассуждения, расчёты, подробные
    объяснения, знания»;
  - `system_prompt`: «Ты отвечаешь голосом через колонку: по-русски, без
    разметки и списков, связно, до 6–8 предложений.»

  У диспетчера по умолчанию:
  `delegates: [{to: "big", when: "сложные вопросы: рассуждения, расчёты, подробные объяснения, знания, которых может не быть у тебя"}]`.
- Правило передачи (точный текст из дизайна 5.2). Строки целей:
  `— <имя>: <when>.`. Тело:

  > Ты можешь передать задачу другим исполнителям. Каждому — свои вопросы:
  > <строки целей>
  >
  > Если вопрос относится к области одного из исполнителей, сначала скажи
  > одну короткую фразу (например «Минутку, сейчас узнаю»), затем вызови
  > инструмент delegate с этим исполнителем. Если вопрос подходит под
  > условие исполнителя, обязательно передай его, даже если кажется, что
  > можешь ответить сам. Если подходят несколько, выбери того, чья область
  > описывает вопрос точнее. Простые вопросы, приветствия и бытовые просьбы
  > отвечай сам, без инструмента.
- Инструмент `delegate`:
  - описание: «Передать задачу исполнителю, чьё условие точнее всего
    подходит к вопросу.»;
  - `executor`: enum активных id, описание «id — имя: when» через «; »;
  - `task`: string, «Задача своими словами, со всем нужным контекстом»;
  - оба параметра обязательны.
- Новые поля API и событий только добавляются:
  - `turn_finished.path: list[str]`;
  - `turn_finished.delegations: list[{from, to, task, auto}]`;
  - те же поля в `TurnOut`;
  - `ConfigOut.executor_prompts: dict[str, str]`;
  - `ModelOut.supports_tools: bool`.

## Review Focus

1. **Цель «зависла».** Модель не отвечает, Ollama грузит модель минуту. Пока
   ждём, колонка подаёт «думаю», через 90 с звучит «Не успела…» (фраза
   вместо сигнала ошибки), колонка не молчит. Тест — задача 4.
2. **Владелец перебивает ответ цели** (barge-in) или меняет исполнителей во
   время передачи. Цель отменяется, поток модели закрыт, следующий ход идёт
   новой сетью. Тест — задачи 3 и 4.
3. **Цикл ссылок A ↔ B.** Глубина 2 держит его, цикла нет. Тест — задача 3.
4. **Владелец удалил исполнителя, на которого ссылаются другие.** Ссылки
   убираются вместе с ним, настройки остаются верными. Тест — задачи 1 и 7.
5. **Модель цели не умеет инструменты, или её нет в Ollama.** Передача ей
   работает без инструментов, а если модели нет — «<Имя> сейчас не
   отвечает.» Тест — задачи 3 и 5.

---

### Task 1: Договоры и настройки исполнителей

**Files:**
- Modify: `core/smartesp/contracts/executor.py`, `contracts/__init__.py`
- Modify: `core/smartesp/config/models.py`
- Test: `core/tests/test_contracts.py`, `core/tests/config/test_executors_config.py`

**Interfaces:**
- Produces (`contracts`):
  - `@dataclass(frozen=True) ToolSpec(name: str, description: str, parameters: dict[str, object])`.
  - `@dataclass(frozen=True) ToolCall(name: str, arguments: dict[str, object])`.
  - `@dataclass(frozen=True) Handoff(source: str, target: str, target_name: str, task: str, auto: bool = False)`.
  - `ReplyPart(text: str = "", tool_call: ToolCall | None = None, handoff: Handoff | None = None, failure: bool = False)`.
    `failure` — это служебная фраза об ошибке: она звучит, а ход помечается
    ошибкой.
  - `Executor.run(self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()) -> AsyncIterator[ReplyPart]`.
  - `@runtime_checkable Identified(Protocol): id: str`.
  - `@runtime_checkable UsesModels(Protocol)` с двумя членами:
    - `def models(self) -> frozenset[str]`;
    - `async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None`
      — не бросает.
- Produces (`config`):
  - `DelegateLink(BaseModel): to: str; when: str = ""`;
  - `ExecutorConfig` получает `description: str = ""` и
    `delegates: list[DelegateLink] = []`;
  - проверка в `Config`:
    - id уникальны;
    - каждая `to` существует;
    - `to != id` своего исполнителя;
    - одна `to` не повторяется в списке.

    Нарушение — `ValueError` с id в тексте.
  - Умолчания — два исполнителя из Global Constraints.

- [ ] **Step 1: Тесты:**
  - `ReplyPart("x")` по-прежнему работает;
  - новые поля по умолчанию пустые;
  - умолчание `Config().executors` — `dispatcher` со связью на `big` с тем
    `when`, `big` со своей моделью, описанием и промптом;
  - ссылка на себя, на несуществующий id, повторная цель, повторный id → по
    `ValueError` с id в тексте;
  - цикл `a → b → a` проходит проверку;
  - старый `config.yaml` версии 3 без `executors` загружается с двумя
    исполнителями;
  - файл, где владелец задал свой список `executors` из одного диспетчера,
    остаётся без `big`.
- [ ] **Step 2: FAIL. Step 3: Реализовать.** Существующие исполнители
  (`OllamaExecutor`, подделки) принимают `tools` и пока игнорируют его.
  **Step 4: PASS** — полный прогон, ruff, pyright.
- [ ] **Step 5: Commit** `feat(core): tool, handoff contracts and executor links in config`.

### Task 2: Ollama — инструменты и возможности модели

**Files:**
- Modify: `core/smartesp/executors/ollama_executor.py`,
  `core/smartesp/executors/ollama_models.py`, `executors/__init__.py`
- Test: `core/tests/executors/test_ollama_tools.py`

**Interfaces:**
- Consumes: `ToolSpec`, `ToolCall`, `ReplyPart`, `UsesModels` (задача 1).
- Produces:
  - `OllamaExecutor.run(messages, tools=())`:
    - передаёт `tools=[{"type": "function", "function": {name, description, parameters}}]`,
      только если они не пусты;
    - каждый `tool_calls` из потока превращает в
      `ReplyPart(tool_call=ToolCall(name, dict(arguments)))`;
    - понимает и объект, и словарь.
  - `OllamaExecutor`:
    - `id: str` (из конфигурации);
    - `models() -> frozenset({model})`;
    - `unload_models(names)` выгружает, если `model in names`.
  - `async model_capabilities(model: str, client=None) -> frozenset[str]` —
    `show(model).capabilities`. Ошибка или модели нет → пустое множество, без
    исключения.

- [ ] **Step 1: Тесты** с подделкой клиента:
  - `tools` уходят в `chat`;
  - без инструментов ключа `tools` нет;
  - поток «текст + `tool_calls`» даёт текстовые куски и один `tool_call` с
    аргументами;
  - словарный формат;
  - `model_capabilities` разбирает `["completion", "tools"]`;
  - ошибка `show` → `frozenset()`.
- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(core): Ollama tool calls and model capabilities`.

### Task 3: Модуль `network/` — сеть исполнителей

**Files:**
- Create:
  - `core/smartesp/network/__init__.py`;
  - `network/rules.py` — правило и инструмент;
  - `network/names.py` — поиск имени в фразе;
  - `network/network.py` — `ExecutorNetwork`.
- Test: `core/tests/network/test_rules.py`, `test_names.py`, `test_network.py`;
  `core/fakes/fake_executor.py` (сценарии с `tool_call`)

**Interfaces:**
- Consumes: договоры задачи 1.
- Produces:
  - `@dataclass(frozen=True) Target(id: str, name: str, when: str)`.
    `when` уже с подстановкой: пустой `when` → описание цели. Неактивные цели
    сюда не попадают.
  - `delegate_rule(targets: Sequence[Target]) -> str` — точный текст из
    Global Constraints. Пустой список → `""`.
  - `delegate_tool(targets) -> ToolSpec`.
  - `named_target(text: str, targets) -> Target | None` — правило «фразы без
    вызова» из Global Constraints.
  - `@dataclass(frozen=True) Member(executor: Executor, name: str, targets: tuple[Target, ...], tools_ok: bool)`.
  - `ExecutorNetwork(entry: str, members: Mapping[str, Member], *, max_depth: int = 2)`
    реализует `Executor`, `Identified` (`id = entry`), `WarmsUp` (греет
    только входного), `UsesModels` (объединение моделей участников).

    `run(messages, tools=())`:
    1. Запускает входного с `delegate_tool`, если у него есть цели и
       `tools_ok`.
    2. Текстовые куски отдаёт как есть.
    3. Первый верный вызов `delegate(executor ∈ целей, task непустая)` даёт:
       - `ReplyPart(handoff=Handoff(source, target, name, task))`;
       - затем куски цели. Цель получает те же сообщения, к последнему
         сообщению `user` дописано `"\n\nЗадача от диспетчера: <task>"`, и
         свой инструмент, если глубина < `max_depth`.
    4. Второй вызов в том же ответе игнорируется.
    5. Неизвестная цель или пустая задача — передачи нет, предупреждение в
       журнал.
    6. Входной закончил без вызова, а `named_target(весь текст)` нашла цель —
       передача с `auto=True`, задача = текст последнего сообщения `user`.
    7. `ExecutorError` цели или ответ цели без текста для озвучки (пусто,
       пробелы, одна метка стиля) — `ReplyPart(text="<Имя> сейчас не отвечает.", failure=True)`,
       исключение не пробрасывается. `ExecutorError` входного пробрасывается,
       как сейчас.
    8. Генераторы закрываются при любом выходе (`aclosing`).

- [ ] **Step 1: Тесты** (подделки исполнителей с готовыми сценариями кусков):
  - правило с двумя целями — точный текст;
  - `when` пустой → описание цели;
  - инструмент: enum, описание `executor`, обязательные поля;
  - `named_target`:
    - «Сейчас спрошу большую модель.» → big;
    - «Спрошу программиста» → coder;
    - два имени → `None`;
    - длинный ответ → `None`;
  - поток «фраза + вызов» → текст, `handoff`, куски цели;
  - цель получила дописанную задачу;
  - глубина: A → B → C — у B нет инструмента, если `max_depth=2` и это вторая
    передача;
  - цикл A ↔ B не уходит дальше 2;
  - неизвестная цель и пустая задача → без передачи;
  - второй вызов игнорируется;
  - цель бросает `ExecutorError` → кусок `failure` с именем;
  - автопередача по фразе, `auto=True`;
  - `tools_ok=False` → входной без инструмента и без автопередачи;
  - закрытие генератора посреди ответа цели закрывает и генератор цели
    (Review Focus 2);
  - `models()` — объединение;
  - `unload_models` зовёт участников;
  - `warm_up` греет только входного.
- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(core): executor network with delegate tool and handoffs`.

### Task 4: Оркестратор — передача в ходе

**Files:**
- Create: `core/smartesp/conversation/handoffs.py` — ожидание после
  передачи, путь и передачи хода.
- Modify: `conversation/orchestrator.py`, `conversation/turn.py`,
  `conversation/turn_events.py`, `core/smartesp/api/schemas.py` (`TurnOut`)
- Test: `core/tests/conversation/test_handoff.py`

**Interfaces:**
- Consumes: `Handoff`, `ReplyPart.failure`, `Identified`.
- Produces:
  - Новые поля `Turn`:
    - `path: list[str]` — начинается с `executor.id` (`Identified`) или
      `"entry"`;
    - `delegations: list[Handoff]`.
  - `turn_finished` и `TurnOut` получают:
    - `path`;
    - `delegations` — `[{from, to, task, auto}]`.
  - На куске с `handoff`:
    - добавить цель в `path` и `delegations`;
    - следующий кусок ждать как первый: `first_part` с «думаю» каждые 8 с и
      пределом `DELEGATE_FIRST_PART_LIMIT_S = 90.0`;
    - не дождались — в поток озвучки уходит «Не успела ответить, спроси
      попозже.», ход `failed`; фраза вместо сигнала ошибки.
    - цель ничего не сказала (поток кончился или пауза 20 с до первого
      текста) — «<Имя> сейчас не отвечает.», ход `failed`.
  - Передача без текста до неё — тон «думаю» сразу.
  - Кусок `failure` начинает новое предложение, озвучивается и помечает ход
    `failed`. Фраза вместо сигнала ошибки: тон ошибки звучит, только если
    звука не было (сигнал уходит вместе с reply_end и перебил бы фразу).
  - Метка стиля в начале первого предложения после передачи применяется,
    если стиль ещё `normal`, и в любом случае снимается.
  - Текст `failure` не идёт в историю, так как ход не `completed`.

- [ ] **Step 1: Тесты** (подделка сети — поддельный исполнитель, отдающий
  `ReplyPart(handoff=…)`):
  - фраза звучит до передачи, затем ответ цели;
  - `path == ["dispatcher", "big"]`;
  - `delegations` в `turn_finished`;
  - ожидание цели: «думаю» каждые 8 с (короткие интервалы в тесте), предел →
    фраза «Не успела…» звучит, сигнала ошибки нет, `status="error"`
    (Review Focus 1);
  - передача без текста → тон «думаю» сразу;
  - кусок `failure` → фраза и ошибка (без тона ошибки);
  - цель промолчала → «<Имя> сейчас не отвечает.», ошибка;
  - `[style:quiet]` у цели → `quiet`, метка не звучит;
  - стиль `quiet` диспетчера сохраняется для цели;
  - barge-in во время ожидания цели — генератор закрыт, ход прерван
    (Review Focus 2);
  - история: вопрос и вся прозвучавшая речь одной репликой;
  - ход без передачи: `path == [id входного]`.
- [ ] **Step 2: FAIL. Step 3: Реализовать.** Оркестратор не больше 300
  строк. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(core): spoken handoffs with thinking tones, limits and turn path`.

### Task 5: Связка — сеть из настроек, прогрев и выгрузка наборов моделей

**Files:**
- Create: `core/smartesp/lifecycle/network_build.py` (или аналог в
  `lifecycle/`). Перевод `Config` в `Member`/`Target` и итоговые промпты —
  логика, поэтому не в `wiring.py`.
- Modify:
  - `core/smartesp/wiring.py` — только вызовы;
  - `core/smartesp/lifecycle/answering.py` — наборы моделей;
  - `core/smartesp/api/schemas.py`, `api/routes.py`;
  - `core/smartesp/control/core.py` — `executor_prompts`, `supports_tools`.
- Test: `core/tests/lifecycle/test_network_build.py`, дополнить
  `tests/lifecycle/test_answering.py`, `tests/test_lifecycle.py`,
  `tests/api/test_api.py`

**Interfaces:**
- Consumes: задачи 1–3.
- Produces:
  - `async build_network(config: Config, kinds: Kinds, capabilities: Callable[[str], Awaitable[frozenset[str]]]) -> tuple[Analyzer, ExecutorNetwork]`.
    - Промпт каждого исполнителя: свой промпт + правила обработчиков +
      `delegate_rule(его цели)`, если `tools_ok`.
    - `tools_ok` = `"tools" in capabilities(model)`.
    - Неактивные связи (пустые `when` и описание) отброшены.
  - `executor_prompts(config, kinds, tools_ok_by_id) -> dict[str, str]`.
    `dispatcher_prompt` = промпт входного из этого словаря.
  - `LiveAnswering`:
    - `release(old)` выгружает модели `old.models() - live.models()` после
      `wait_turns(TURN_WAIT_S)` и повторной проверки;
    - `unload_all` выгружает объединение живых и «в стороне»;
    - после подмены — фоновый прогрев остальных участников, с допуском
      ошибок: запись в журнал, не блокирует ни старт, ни правку.
  - `TURN_WAIT_S = 150.0`.
  - API:
    - `ConfigOut.executor_prompts`;
    - `ModelOut.supports_tools` (через `model_capabilities`, кеш на время
      процесса по имени модели).
  - Разделы `executors` и `stages` пересобирают сеть.

- [ ] **Step 1: Тесты:**
  - `build_network` из умолчаний: два участника, у входного цель `big` с
    `when` из настроек и правилом в промпте;
  - модель без `tools` → без правила, `tools_ok=False`;
  - пустая связь отброшена;
  - промпт цели включает правила обработчиков;
  - `release` выгружает только модели, ушедшие из живой сети;
  - смена промпта не выгружает модель;
  - фоновый прогрев `big` не задерживает `build` (модель «грузится» 5 с в
    подделке, `build` возвращается сразу после входного);
  - API отдаёт `executor_prompts` и `supports_tools`;
  - `test_lifecycle`: ядро на подделках проходит ход с передачей — `path` в
    `/api/v1/turns`.
- [ ] **Step 2: FAIL. Step 3: Реализовать.** `wiring.py` не больше 300 строк,
  без логики. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(core): build executor network from settings, per-model warm-up and unload`.

### Task 6: Проверка с моделями и вживую

**Files:**
- Create: `core/tests/network/test_routing_models.py` (`@pytest.mark.models`)
- Create: `tools/make_wav.py` — озвучивает фразу нашим TTS в WAV 16 кГц для
  `fake_device.py`

**Interfaces:**
- Consumes: всё выше.

- [ ] **Step 1: Тест с моделями.** Gemma, правило и инструмент из
  `network/rules.py`, без сети ядра:
  - цели `big` и `coder` (`when` «вопросы про программирование, код, ошибки в
    программах»);
  - 3 простых → без вызова;
  - 3 сложных → `big`;
  - 2 про код (питон, сортировка на C) → `coder`;
  - допуск: не меньше 7 из 8 верных;
  - при вызове всегда есть фраза до вызова.

  `uv run pytest -m models tests/network -v` → PASS.
- [ ] **Step 2: `tools/make_wav.py "текст" out.wav [--voice silero/xenia]`**
  — через `smartesp.tts` (`SileroTTS` и `voice_path`), запуск из `core/`.
- [ ] **Step 3: Проверка вживую.**
  - Порт 8765 свободен; файлы `~/SmartEsp` (`config.yaml`, `.bak`,
    `config.defaults.yaml`) сохранить и вернуть побайтно.
  1. `cd core && uv run python -m smartesp`.
  2. `make_wav.py "Объясни подробно, почему небо голубое" q.wav` →
     `fake_device.py --wav q.wav --out reply.wav`.
  3. В журнале ход с `path=['dispatcher','big']`, первым звуком фраза
     диспетчера, затем ответ deepseek. `reply.wav` длиннее 10 с.
  4. Простой вопрос («Привет, как дела?») → без передачи.
  5. Остановить ядро, вернуть файлы.

  Отчёт — строки журнала и задержки.
- [ ] **Step 4: Commit** `test(core): model routing check and WAV maker for live tests`.

### Task 7: Интерфейс — состояние и действия исполнителей

**Files:**
- Modify:
  - `ui/openapi.json`, `ui/src/api/schema.ts` (`npm run api`);
  - `ui/src/state/actions.ts`, `ui/src/state/model.ts`;
  - `ui/src/schema/blocks.ts` — помощники исполнителей.
- Test: `ui/src/state/executors.test.ts`, `ui/src/schema/blocks.test.ts`

**Interfaces:**
- Produces:
  - `type ExecutorItem = { id, name, model, description, systemPrompt, entry, links: {to, when, active}[] }`;
  - `listExecutors(state) -> ExecutorItem[]` — входной первым;
  - действия:
    - `addExecutor()` — id `executor-N` (первый свободный N), модель
      входного, имя «Исполнитель N»;
    - `updateExecutor(id, patch)`;
    - `removeExecutor(id)` — нельзя для входного; убирает ссылки на него у
      других;
    - `setLink(from, to, enabled, when)`.

    Все шлют `PATCH {executors: [...]}` целым списком, как сейчас
    `setDispatcher`, без `undefined`.
  - `setDispatcher` остаётся обёрткой над `updateExecutor(entry, …)`.
  - `Turn` знает `path` и `delegations`.

- [ ] **Step 1: Тесты:**
  - `listExecutors` из умолчаний;
  - `active` — по `when` или описанию цели;
  - `addExecutor` даёт `executor-1`, затем `executor-2`;
  - `removeExecutor('big')` убирает и связь у диспетчера (Review Focus 4);
  - входной не удаляется;
  - `setLink` включает и выключает связь, меняет `when`;
  - в PATCH весь список.
- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS** + typecheck, lint,
  build.
- [ ] **Step 5: Commit** `feat(ui): executors and links in state and actions`.

### Task 8: Интерфейс — схема с исполнителями

**Files:**
- Modify: `ui/src/schema/buildGraph.ts`,
  `ui/src/components/schema/SchemaView.tsx`, `nodes.tsx`, `schema.css`
- Test: `ui/src/schema/buildGraph.test.ts`

**Interfaces:**
- Produces:
  - **Колонка исполнителей** вместо одного узла диспетчера:
    - `id = executor:<id>`, входной сверху;
    - на узле имя и модель;
    - «не умеет передавать», если модель без `supports_tools`.
  - **Стрелки исполнитель → исполнитель** по связям:
    - `label` — `when`, обрезанный до 40 символов с «…»;
    - полный текст — в `data.title`;
    - неактивная связь — пунктиром.
  - **Голос** получает связи от всех исполнителей.
  - **Подсветка по `turn.path`:**
    - колонка → обработчики → `path[0]`;
    - стрелки `path[i]` → `path[i+1]`;
    - последний исполнитель → голос.

    Ход без `path` (старые записи) — как раньше, до входного.
  - Клик по исполнителю → `select({kind: "executor", id})`.

- [ ] **Step 1: Тесты:**
  - узлы исполнителей из умолчаний;
  - стрелка `dispatcher → big` с подписью;
  - неактивная связь — пунктир;
  - ход с `path [dispatcher, big]` подсвечивает `dispatcher → big` и
    `big → голос`, но не `dispatcher → голос`;
  - ход без передачи подсвечивает `dispatcher → голос`;
  - длинное условие обрезается.
- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS** + typecheck, lint,
  build.
- [ ] **Step 5: Commit** `feat(ui): executors column, labelled links and handoff path on schema`.

### Task 9: Интерфейс — настройки исполнителя, левая панель, лента

**Files:**
- Create: `ui/src/components/settings/ExecutorSettings.tsx`, `LinkRows.tsx`
- Modify:
  - `SettingsPanel.tsx` — вид `executor`; `DispatcherSettings.tsx` заменить;
  - `ui/src/components/side/SideList.tsx` — раздел «Исполнители» с
    «Добавить»;
  - `ui/src/components/feed/TurnRow.tsx`, `TurnCard.tsx`.
- Test: `ui/src/components/settings/ExecutorSettings.test.tsx`,
  `ui/src/components/feed/Feed.test.tsx`, `SideList.test.tsx`

**Interfaces:**
- **Настройки исполнителя:**
  - имя;
  - модель — список из `models`, с «(без инструментов)» у моделей без
    `supports_tools`;
  - «Описание» — что это за исполнитель;
  - промпт с «Сохранить»;
  - «Может передавать:» — строка на каждого другого исполнителя:
    - флажок;
    - поле «Когда вызывать» с заглушкой — описанием цели;
    - пометка «неактивна — укажите, когда вызывать», если пусто и то, и
      другое;
    - сохраняется по Enter или потере фокуса;
  - «Итоговый промпт» из `executor_prompts[id]`, свёрнутый;
  - «Удалить» с подтверждением (не у входного);
  - если модель без инструментов — «эта модель не умеет передавать задачи»,
    строки связей неактивны.
  - Пока применяется изменение — элементы заблокированы, как сейчас.
- **Левая панель:** раздел «Исполнители» — список (имя, модель) и кнопка
  «Добавить», которая создаёт исполнителя и выбирает его.
- **Лента:**
  - у хода с передачей — метка «→ <имя цели>» (имя из `delegations[].to` по
    списку исполнителей, иначе id);
  - в карточке — «Передано <имя>: <task>», «(автоматически)» при `auto`.

- [ ] **Step 1: Тесты:**
  - смена имени, модели, описания вызывает `updateExecutor`;
  - флажок и условие вызывают `setLink`;
  - пустое условие при пустом описании цели показывает «неактивна»;
  - «Удалить» — после подтверждения `removeExecutor`, у входного кнопки нет;
  - модель без инструментов — пометка и неактивные связи;
  - «Добавить» в левой панели;
  - метка «→ Большая модель» в строке ленты и задача в карточке.
- [ ] **Step 2: FAIL. Step 3: Реализовать. Step 4: PASS** + typecheck, lint,
  build.
- [ ] **Step 5: Commit** `feat(ui): executor settings with links, executors list and handoff in feed`.

### Task 10: Документация и проверка интерфейса вживую

**Files:**
- Modify: `core/README.md` (раздел про исполнителей и связи), `ui/README.md`
  (коротко), `docs/superpowers/plans/2026-11-18-core-control.md` («Имена
  событий» — `path`, `delegations`)

- [ ] **Step 1: Документация.**
  - Что такое исполнитель и связь.
  - Условие «когда вызывать».
  - Глубина 2, предел 90 с.
  - Модели без инструментов.
  - Как поменять «Большую модель» в приложении.
- [ ] **Step 2: Проверка вживую.** Правила те же, что в задаче 6.
  1. Собрать интерфейс.
  2. Задать сложный вопрос через `fake_device.py`.
  3. Скриншоты через Chrome DevTools: схема с подсвеченным путём до
     «Большой модели», лента с меткой передачи, настройки диспетчера со
     связью.
  4. Посмотреть их и описать в отчёте.
- [ ] **Step 3: Commit** `docs: executor network in core and UI docs`.
