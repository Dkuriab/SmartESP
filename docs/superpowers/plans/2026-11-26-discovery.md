# Поиск ядра и настройка Wi-Fi с телефона — план

> **Для исполнителя:** superpowers:executing-plans, шаги — чекбоксы.

**Цель:** в прошивке ничего не зашито: ядро объявляет `_smartesp._tcp` по mDNS, колонка
находит его сама; Wi-Fi задаётся с телефона через точку `Kuzya-xxxx`.

**Архитектура:** ядро — модуль `smartesp/discovery/` (zeroconf, async) с подделываемым
регистратором; колонка — новые модули `net_settings` (NVS), `core_finder` (mDNS в своей
задаче), развитие `wifi_link` (станция + точка настройки с порталом в своей задаче).
`server_link`, `updater`, `stream_player` получают адрес через `setServer(...)`; связь — в `.ino`.

**Стек:** Python 3.12 / asyncio / zeroconf; Arduino ESP32 3.3.12 (Preferences, DNSServer,
WebServer, ESPmDNS + `mdns.h`).

**Спек:** `docs/superpowers/specs/2026-11-26-discovery-design.md` (ветка `docs/discovery-lmstudio-design`).

## Общие ограничения

- `FW_VERSION "0.8.0"`, протокол 5, `partitions.csv` не меняется.
- Служба `_smartesp._tcp`, TXT: `id` (постоянный id ядра), `path=/device`, `version`.
- Имя колонки `kuzya-xxxx` (4 последних hex MAC, строчные), точка `Kuzya-xxxx`, открытая.
- 2 минуты без подключения → точка; точка открыта — сохранённая сеть пробуется дальше.
- `zeroconf` (и `ifaddr`, если импортируется напрямую) — `==` в `pyproject.toml`, `uv.lock` обновлён.
- Тесты не трогают `~/SmartEsp` и настоящую сеть; ядро на 8765 не запускается.
- Прошивка: модули не знают друг друга, `loop()` не блокируется, `.ino` — только связка.

## Обратить внимание при ревью

1. Несколько адресов у Mac (VPN, мост ВМ): колонка берёт адрес из своей подсети — `chooseAddress` (Task 4, хост-тест).
2. Своё ядро на миг не ответило на поиск, чужое ответило: колонка не уходит сразу — 3 поиска подряд без своего (Task 4, хост-тест).
3. Пароль/SSID с `&`, `+`, `%`, кириллицей и пустой пароль (открытая сеть); длины 32/64 — разбор формы (Task 5, хост-тест).
4. SSID с `<`, `"` в списке сетей — экранирование HTML (Task 5, хост-тест).
5. Сменился IP Mac при работающем ядре — объявление обновляется (Task 1, тест с подделкой адресов).

---

### Task 1: Ядро — объявление в сети

**Files:** Create `core/smartesp/discovery/{__init__,identity,addresses,advertiser,registrar}.py`,
`core/tests/discovery/test_*.py`; modify `core/pyproject.toml`, `core/uv.lock`, `core/smartesp/parts.py`,
`core/smartesp/wiring.py`, `core/CLAUDE.md` (строка структуры).

**Interfaces (Produces):**
- `load_or_create_core_id(home: Path) -> str` — `<home>/core_id`, 12 hex, создаётся один раз.
- `pick_addresses(ips: Iterable[str]) -> list[str]` — IPv4 без loopback и 169.254, по порядку, без повторов.
- `ServiceRecord(core_id, port, version, addresses)` (dataclass), `Registrar` (Protocol: `async register(record)`, `async aclose()`).
- `Advertiser(make_registrar, record_for, addresses, *, check_s=30.0)`: `start()`, `async aclose()`; публикует,
  раз в `check_s` сверяет адреса и перепубликует при смене; ошибка — в журнал, повтор на следующей проверке.
- `ZeroconfRegistrar` — `AsyncZeroconf`, `ServiceInfo` из `service_info(record)` (чистая функция, тестируется).

- [ ] Тесты: id стабилен между вызовами и в `tmp_path`; `pick_addresses`; `service_info` даёт тип
  `_smartesp._tcp.local.`, TXT `id/path/version`, порт; `Advertiser` публикует, перепубликует при смене адресов,
  снимает при `aclose`, переживает исключение регистратора, без адресов не публикует.
- [ ] Реализация, `parts.py`: `discovery(home, port, version) -> Advertiser`; `wiring.py`: `start` → `parts.discovery.start()`, `finish` → `aclose()`.
- [ ] `uv run pytest -q`, `ruff check`, `ruff format --check`, `pyright` — зелёные. Коммит.

### Task 2: Прошивка — net_settings

**Files:** Create `firmware/SmartEsp/src/net_settings/NetSettings.{h,cpp}`; modify `src/common/Types.h`.

- `struct WifiCredentials { char ssid[33]; char password[65]; }` и `struct CoreAddress { char host[40]; uint16_t port; char path[32]; char id[33]; }` — в `Types.h`.
- `NetSettings::begin()`, `bool loadWifi(WifiCredentials&)`, `void saveWifi(const WifiCredentials&)` (пишет только при отличии),
  `void loadCoreId(char* out, size_t size)`, `void saveCoreId(const char*)` — Preferences, пространство `net`.

### Task 3: Прошивка — setServer у server_link, updater, stream_player

- `ServerLink::begin(path, fwVersion)` без адреса; `setServer(const char* host, uint16_t port, const char* path)` — под замком,
  задача связи переподключается к новому адресу; тот же адрес — ничего.
- `Updater::setServer(host, port)`, `StreamPlayer::setServer(host, port)` — копия под замком, задача читает копию.
- Убрать `host/port` из `UpdaterConfig`/`StreamPlayerConfig`.

### Task 4: Прошивка — core_finder

**Files:** Create `src/core_finder/{CoreFinder,CoreChoice,SearchTimer}.{h,cpp}`, `tools/host_tests/finder_test.cpp`; modify `tools/host_tests/run.sh`.

- `CoreChoice` (чисто): `chooseCore(const FoundCore* list, size_t n, const char* preferredId, uint8_t& missesOfPreferred) -> int`
  (индекс или −1; свой есть → он; нет своего, но был — первые 2 промаха −1, с 3-го — первое найденное);
  `chooseAddress(const uint32_t* ips, size_t n, uint32_t localIp, uint32_t mask) -> int`.
- `SearchTimer` (чисто): `bool due(uint32_t now, bool wifi, bool server)` — первый поиск сразу при Wi-Fi, затем 5, 10, 20, 30 с …;
  связь с ядром есть — не ищет; связь пропала — первый поиск через 5 с.
- `CoreFinder`: `begin({hostname})`, `setPreferredId`, `setWifiConnected`, `setServerConnected`, `pollFound(CoreAddress&)`,
  `pollRemember(char*, size_t)` (id ядра, с которым связь установилась, если он сменился). Задача: `MDNS.begin(hostname)` после Wi-Fi,
  `mdns_query_ptr("_smartesp","_tcp",3000,8)`, нет A-записи — `mdns_query_a`.
- [ ] Хост-тесты: свой из нескольких; нет своего 1–2 раза → −1, 3-й → первый; без preferred → первый; пустой список;
  адрес из своей подсети; паузы таймера. `tools/host_tests/run.sh` зелёный. Коммит.

### Task 5: Прошивка — wifi_link: станция, переход с 0.7.0, точка настройки

**Files:** Modify `src/wifi_link/WifiLink.{h,cpp}`; create `src/wifi_link/{LinkPlan,SetupForm,SetupPage}.{h,cpp}`, `tools/host_tests/wifi_test.cpp`.

- `LinkPlan` (чисто): паузы 1, 2, 4 … 30 с; `portalWanted` — нет сети сразу, иначе 120 с без связи; точка закрывается через 15 с после подключения.
- `SetupForm` (чисто): `urlDecode`, `parseSetupForm(body, WifiCredentials&) -> bool` (SSID 1..32 байт, пароль пустой или 8..63), `htmlEscape`.
- `WifiLink::begin({hostPrefix, apPrefix}, const WifiCredentials* saved)` — нет своей → сеть из `esp_wifi_get_config` (0.7.0);
  `loop()`, `isConnected()`, `hostname()`, `pollJoined(WifiCredentials&)` — сеть, к которой подключились (её сохраняет `.ino`).
  Портал (DNSServer + WebServer, асинхронный скан) — в своей задаче; страница по-русски, без внешних ресурсов, `/status` для опроса.
- [ ] Хост-тесты на `LinkPlan` и `SetupForm`, включая пункты 3–4 обзора. Коммит.

### Task 6: Связка, версия, секреты, документы

- `SmartEsp.ino`: `NetSettings` → `WifiLink` → `CoreFinder` → `setServer` трёх модулей; `pollJoined` → `saveWifi`; `pollRemember` → `saveCoreId`. `FW_VERSION "0.8.0"`.
- Удалить `secrets.example.h`; README (настройка с телефона, без `secrets.h`), корневой `CLAUDE.md` (правило секретов — для будущих), упоминания `SERVER_HOST` в комментариях `Types.h`.
- [ ] `tools/build.sh` собирается, размер < 4 МБ; хост-тесты; проверки ядра. Коммит.
