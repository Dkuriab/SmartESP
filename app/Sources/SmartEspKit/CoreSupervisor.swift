import Darwin
import Foundation

/// Надзор за ядром: запуск или подключение к уже запущенному, опрос раз в секунду,
/// перезапуск после падений (не больше 3 за 60 с), остановка SIGTERM → 15 с → SIGKILL.
/// Запуск, опрос и падения — в `CoreSupervisor+Polling.swift`; «Взять управление» —
/// в `CoreSupervisor+Control.swift`.
@MainActor public final class CoreSupervisor {
    /// Сколько ждать выхода ядра (своего после SIGTERM или прежнего, которое ещё останавливается), секунд.
    public static let stopTimeout: TimeInterval = 15
    /// Период опроса, секунд.
    public static let pollInterval: TimeInterval = 1
    /// После стольких падений за `crashWindow` — ошибка вместо перезапуска.
    public static let crashLimit = 3
    /// Окно подсчёта падений, секунд.
    public static let crashWindow: TimeInterval = 60
    /// Шаг ожидания выхода процесса и проверки доступа, секунд.
    static let waitStep: TimeInterval = 0.1
    /// Проверка доступа к папке дольше этого — значит, macOS спрашивает пользователя, секунд.
    public static let accessPromptDelay: TimeInterval = 1
    /// Ядро после запуска молчит столько (нет файла запуска, stderr и записей в журнале),
    /// а репозиторий в защищённой папке — показываем подсказку про доступ, секунд.
    public static let silentStartLimit: TimeInterval = 20
    /// Столько неудачных опросов подряд (ядро живо, но `status` не ответил),
    /// прежде чем `running` сменится на `starting`: единичный таймаут окно не трогает.
    public static let probeFailureLimit = 3

    /// Текущее состояние.
    public internal(set) var state: CoreState = .stopped {
        didSet { if state != oldValue { onChange?(state) } }
    }
    /// Вызывается при каждой смене состояния.
    public var onChange: ((CoreState) -> Void)?
    /// Токен API, когда он прочитан.
    public internal(set) var token: String?
    /// Порт ядра из файла запуска.
    public internal(set) var port: Int?

    enum Mode {
        case idle
        case own(any CoreHandle)
        case external(pid: Int32)
    }

    let paths: AppPaths
    let launcher: any CoreLaunching
    let probe: any StatusProbing
    let access: any AccessProbing
    let clock: () -> TimeInterval
    let sleep: @MainActor (TimeInterval) async -> Void
    let fileExists: (String) -> Bool
    let pidAlive: (Int32) -> Bool
    let env: [String: String]
    let home: URL
    let autoPoll: Bool
    let commandLine: (Int32) -> [String]?
    let sendSignal: (Int32, Int32) -> Bool

    var mode: Mode = .idle
    var crashTimes: [TimeInterval] = []
    /// Неудачные опросы своего ядра подряд.
    var probeFailures = 0
    var logOffset: UInt64 = 0
    /// Когда запущен свой процесс (по `clock`).
    var launchedAt: TimeInterval = 0
    /// Растёт при каждом `stop()`: долгие ожидания видят, что их отменили.
    var generation = 0
    var pollTask: Task<Void, Never>?
    private var ticking = false
    /// Идёт запуск или «Взять управление»: второй запуск не начинаем.
    var startInProgress = false
    private var stopTask: Task<Void, Never>?
    /// Задача, которую создал последний `start()` или `takeOver()`; её ждёт `stop()`.
    var startTask: Task<Void, Never>?

    /// - Parameters:
    ///   - paths: пути репозитория и папки данных.
    ///   - launcher: запуск процесса ядра.
    ///   - probe: опрос HTTP API.
    ///   - access: проверка доступа к папке ядра перед запуском.
    ///   - clock: монотонные секунды (окно падений, ожидание остановки).
    ///   - sleep: пауза в секундах.
    ///   - fileExists: проверка исполняемого файла (поиск `uv`).
    ///   - pidAlive: жив ли процесс с таким pid.
    ///   - env: окружение для поиска `uv` и для процесса ядра.
    ///   - home: домашняя папка (поиск `uv`).
    ///   - autoPoll: сам опрашивать раз в секунду; в тестах `false` и `tick()` вручную.
    ///   - commandLine: аргументы процесса по pid (проверка перед «Взять управление»).
    ///   - sendSignal: послать сигнал процессу; `true` — получилось.
    public init(
        paths: AppPaths,
        launcher: any CoreLaunching,
        probe: any StatusProbing,
        access: (any AccessProbing)? = nil,
        clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        sleep: @escaping @MainActor (TimeInterval) async -> Void = { try? await Task.sleep(for: .seconds($0)) },
        fileExists: @escaping (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) },
        pidAlive: @escaping (Int32) -> Bool = isProcessAlive,
        env: [String: String] = ProcessInfo.processInfo.environment,
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        autoPoll: Bool = true,
        commandLine: @escaping (Int32) -> [String]? = processArguments,
        sendSignal: @escaping (Int32, Int32) -> Bool = { Darwin.kill($0, $1) == 0 }
    ) {
        self.paths = paths
        self.launcher = launcher
        self.probe = probe
        self.access = access ?? FileAccessProbe()
        self.clock = clock
        self.sleep = sleep
        self.fileExists = fileExists
        self.pidAlive = pidAlive
        self.env = env
        self.home = home
        self.autoPoll = autoPoll
        self.commandLine = commandLine
        self.sendSignal = sendSignal
    }

    /// Подключается к живому чужому ядру или запускает своё; сразу возвращается.
    public func start() {
        startTask = Task { await self.performStart() }
    }

    /// Перезапуск: `POST /api/v1/restart`; не ответило — `stop()` и запуск заново.
    /// Пока идёт запуск — ничего не делает. Из ошибки или остановки — просто запуск
    /// со сброшенным счётчиком падений (и новой проверкой доступа к папке).
    public func restart() async {
        // Запуск (в том числе проверка доступа) ещё идёт — он сам доведёт дело до конца;
        // иначе после «Разрешить» запустили бы `uv` и тут же остановили и запустили снова
        guard !startInProgress else { return }
        if case .idle = mode {
            crashTimes = []
            await performStart()
            return
        }
        if let port, let token, await probe.restart(port: port, token: token) { return }
        let expected = generation + 1
        await stop()
        // Пока ждали остановки, позвали ещё `stop()` (выход из приложения) — не запускаем
        guard generation == expected else { return }
        mode = .idle
        crashTimes = []
        await performStart()
    }

    /// Останавливает своё ядро: SIGTERM, до 15 с ожидания, затем SIGKILL.
    /// Чужое ядро не трогает. Повторный вызов во время остановки ждёт первую.
    /// После остановки надзор ядро сам не запускает — только `start()` или `restart()`.
    public func stop() async {
        generation += 1
        await startTask?.value
        if let inFlight = stopTask { return await inFlight.value }
        switch mode {
        case .external:
            return
        case .idle:
            stopPolling()
            clearConnection()
            state = .stopped
        case .own(let handle):
            let task = Task { await self.performStop(handle) }
            stopTask = task
            await task.value
            stopTask = nil
        }
    }

    /// Один шаг опроса: падение своего ядра, файл запуска, токен, `status`.
    public func tick() async {
        guard !ticking, stopTask == nil else { return }
        ticking = true
        defer { ticking = false }
        switch mode {
        case .idle:
            return
        case .own(let handle):
            if handle.isRunning {
                await refreshOwn(handle)
            } else if handle.exitCode == 0 {
                stoppedByItself()
            } else {
                await handleCrash()
            }
        case .external(let pid):
            await refreshExternal(pid)
        }
    }

    /// Запуск: живой `pid` в файле запуска и ответ `status` → подключение, иначе свой процесс.
    func performStart() async {
        guard case .idle = mode, !startInProgress else { return }
        startInProgress = true
        defer { startInProgress = false }
        let current = generation
        state = .starting
        let adopted = await adoptExternal(current)
        guard current == generation else { return }
        if !adopted {
            guard await checkAccess(current) else { return }
            launchOwn()
        }
        ensurePolling()
    }

    /// Ждёт смерти процесса не дольше `stopTimeout`; прерывается `stop()`.
    /// - Returns: `true`, если ожидание не отменили.
    func waitForExit(_ pid: Int32, _ current: Int) async -> Bool {
        let deadline = clock() + Self.stopTimeout
        while pidAlive(pid) && clock() < deadline && current == generation {
            await sleep(Self.waitStep)
        }
        return current == generation
    }

    private func performStop(_ handle: any CoreHandle) async {
        stopPolling()
        state = .stopping
        handle.terminate()
        let deadline = clock() + Self.stopTimeout
        while handle.isRunning && clock() < deadline {
            await sleep(Self.waitStep)
        }
        if handle.isRunning { handle.kill() }
        mode = .idle
        clearConnection()
        state = .stopped
    }
}
