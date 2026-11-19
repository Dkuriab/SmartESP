import Foundation

/// Надзор за ядром: запуск или подключение к уже запущенному, опрос раз в секунду,
/// перезапуск после падений (не больше 3 за 60 с), остановка SIGTERM → 15 с → SIGKILL.
@MainActor public final class CoreSupervisor {
    /// Сколько ждать выхода ядра после SIGTERM, секунд.
    public static let stopTimeout: TimeInterval = 15
    /// Период опроса, секунд.
    public static let pollInterval: TimeInterval = 1
    /// После стольких падений за `crashWindow` — ошибка вместо перезапуска.
    public static let crashLimit = 3
    /// Окно подсчёта падений, секунд.
    public static let crashWindow: TimeInterval = 60
    /// Шаг ожидания выхода при остановке, секунд.
    static let stopStep: TimeInterval = 0.1

    /// Текущее состояние.
    public private(set) var state: CoreState = .stopped {
        didSet { if state != oldValue { onChange?(state) } }
    }
    /// Вызывается при каждой смене состояния.
    public var onChange: ((CoreState) -> Void)?
    /// Токен API, когда он прочитан.
    public private(set) var token: String?
    /// Порт ядра из файла запуска.
    public private(set) var port: Int?

    private enum Mode {
        case idle
        case own(any CoreHandle)
        case external(pid: Int32)
    }

    private let paths: AppPaths
    private let launcher: any CoreLaunching
    private let probe: any StatusProbing
    private let clock: () -> TimeInterval
    private let sleep: @MainActor (TimeInterval) async -> Void
    private let fileExists: (String) -> Bool
    private let pidAlive: (Int32) -> Bool
    private let env: [String: String]
    private let home: URL
    private let autoPoll: Bool

    private var mode: Mode = .idle
    private var crashTimes: [TimeInterval] = []
    private var logOffset: UInt64 = 0
    private var ticking = false
    private var startInProgress = false
    private var stopInProgress = false
    private var pollTask: Task<Void, Never>?
    /// Задача, которую создал последний `start()`.
    private(set) var startTask: Task<Void, Never>?

    /// - Parameters:
    ///   - paths: пути репозитория и папки данных.
    ///   - launcher: запуск процесса ядра.
    ///   - probe: опрос HTTP API.
    ///   - clock: монотонные секунды (окно падений, ожидание остановки).
    ///   - sleep: пауза в секундах.
    ///   - fileExists: проверка исполняемого файла (поиск `uv`).
    ///   - pidAlive: жив ли процесс с таким pid.
    ///   - env: окружение для поиска `uv` и для процесса ядра.
    ///   - home: домашняя папка (поиск `uv`).
    ///   - autoPoll: сам опрашивать раз в секунду; в тестах `false` и `tick()` вручную.
    public init(
        paths: AppPaths,
        launcher: any CoreLaunching,
        probe: any StatusProbing,
        clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        sleep: @escaping @MainActor (TimeInterval) async -> Void = { try? await Task.sleep(for: .seconds($0)) },
        fileExists: @escaping (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) },
        pidAlive: @escaping (Int32) -> Bool = isProcessAlive,
        env: [String: String] = ProcessInfo.processInfo.environment,
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        autoPoll: Bool = true
    ) {
        self.paths = paths
        self.launcher = launcher
        self.probe = probe
        self.clock = clock
        self.sleep = sleep
        self.fileExists = fileExists
        self.pidAlive = pidAlive
        self.env = env
        self.home = home
        self.autoPoll = autoPoll
    }

    /// Подключается к живому чужому ядру или запускает своё; сразу возвращается.
    public func start() {
        startTask = Task { await self.performStart() }
    }

    /// Перезапуск: `POST /api/v1/restart`; не ответило — `stop()` и запуск заново.
    /// Из ошибки или остановки — просто запуск со сброшенным счётчиком падений.
    public func restart() async {
        await startTask?.value
        if case .idle = mode {
            crashTimes = []
            await performStart()
            return
        }
        if let port, let token, await probe.restart(port: port, token: token) { return }
        await stop()
        mode = .idle
        crashTimes = []
        await performStart()
    }

    /// Останавливает своё ядро: SIGTERM, до 15 с ожидания, затем SIGKILL.
    /// Чужое ядро не трогает.
    public func stop() async {
        await startTask?.value
        switch mode {
        case .external:
            return
        case .idle:
            stopPolling()
            state = .stopped
        case .own(let handle):
            stopInProgress = true
            stopPolling()
            state = .stopping
            await terminate(handle)
            mode = .idle
            port = nil
            stopInProgress = false
            state = .stopped
        }
    }

    /// Один шаг опроса: падение своего ядра, файл запуска, токен, `status`.
    public func tick() async {
        guard !ticking, !stopInProgress else { return }
        ticking = true
        defer { ticking = false }
        switch mode {
        case .idle:
            return
        case .own(let handle):
            if handle.isRunning { await refreshOwn(handle) } else { handleCrash() }
        case .external(let pid):
            await refreshExternal(pid)
        }
    }

    /// Запуск: живой `pid` в файле запуска и ответ `status` → подключение, иначе свой процесс.
    func performStart() async {
        guard case .idle = mode, !startInProgress else { return }
        startInProgress = true
        defer { startInProgress = false }
        state = .starting
        if !(await adoptExternal()) { launchOwn() }
        ensurePolling()
    }

    // MARK: - Запуск

    private func adoptExternal() async -> Bool {
        guard let info = RunFile.read(paths.runFile), pidAlive(info.pid),
              let token = TokenFile.read(paths.tokenFile) else { return false }
        guard case let .ok(phase, online, total, ollama) = await probe.status(port: info.port, token: token)
        else { return false }
        mode = .external(pid: info.pid)
        self.port = info.port
        self.token = token
        state = .external(port: info.port, phase: phase, devices: (online, total), ollama: ollama)
        return true
    }

    private func launchOwn() {
        guard let uv = findUv(env: env, home: home, fileExists: fileExists) else { return fail("Не найден uv") }
        logOffset = CoreLog.size(paths.logFile)
        do {
            let handle = try launcher.launch(uv: uv, cwd: paths.coreDir, env: env)
            handle.onExit { [weak self] _ in
                Task { @MainActor in await self?.tick() }
            }
            mode = .own(handle)
            state = .starting
        } catch {
            fail("Не удалось запустить ядро: \(error.localizedDescription)")
        }
    }

    private func fail(_ message: String) {
        mode = .idle
        port = nil
        stopPolling()
        state = .failed(message)
    }

    // MARK: - Опрос

    private func refreshOwn(_ handle: any CoreHandle) async {
        // Файл запуска с мёртвым pid — от прошлого ядра: своё его ещё не переписало
        guard let info = RunFile.read(paths.runFile), pidAlive(info.pid) else { return state = .starting }
        port = info.port
        guard let token = TokenFile.read(paths.tokenFile) else { return state = .starting }
        self.token = token
        let result = await probe.status(port: info.port, token: token)
        guard !stopInProgress, case .own(let current) = mode, current === handle else { return }
        if case let .ok(phase, online, total, ollama) = result {
            state = .running(port: info.port, phase: phase, devices: (online, total), ollama: ollama)
        } else {
            state = .starting
        }
    }

    private func refreshExternal(_ pid: Int32) async {
        guard pidAlive(pid) else {
            mode = .idle
            port = nil
            stopPolling()
            return state = .stopped
        }
        // Во время перезапуска чужое ядро переписывает файл — пока его нет, состояние не трогаем
        guard let info = RunFile.read(paths.runFile), info.pid == pid,
              let token = TokenFile.read(paths.tokenFile) else { return }
        let result = await probe.status(port: info.port, token: token)
        guard case .external(let current) = mode, current == pid,
              case let .ok(phase, online, total, ollama) = result else { return }
        port = info.port
        self.token = token
        state = .external(port: info.port, phase: phase, devices: (online, total), ollama: ollama)
    }

    private func handleCrash() {
        mode = .idle
        port = nil
        let log = CoreLog.read(paths.logFile, from: logOffset)
        if log.portConflict {
            let busy = log.conflictPort ?? RunFile.read(paths.runFile)?.port
            return fail(busy.map { "Порт \($0) занят другой программой" } ?? "Порт занят другой программой")
        }
        let now = clock()
        crashTimes = crashTimes.filter { now - $0 < Self.crashWindow } + [now]
        if crashTimes.count >= Self.crashLimit {
            return fail(log.failureLine ?? "Ядро завершилось, в журнале нет новых записей")
        }
        state = .starting
        launchOwn()
    }

    private func ensurePolling() {
        guard autoPoll, pollTask == nil, !isIdle else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.tick()
                await self.sleep(Self.pollInterval)
            }
        }
    }

    private func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    private var isIdle: Bool {
        if case .idle = mode { return true }
        return false
    }

    // MARK: - Остановка

    private func terminate(_ handle: any CoreHandle) async {
        handle.terminate()
        let deadline = clock() + Self.stopTimeout
        while handle.isRunning && clock() < deadline {
            await sleep(Self.stopStep)
        }
        if handle.isRunning { handle.kill() }
    }
}
