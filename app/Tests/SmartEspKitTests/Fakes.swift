import Foundation
@testable import SmartEspKit

/// Поддельные часы: sleep сдвигает время мгновенно и даёт поработать другим задачам.
@MainActor final class FakeClock {
    var now: TimeInterval = 1000
    func sleep(_ seconds: TimeInterval) async {
        now += seconds
        await Task.yield()
    }
}

/// Поддельная проверка доступа: ответ готов, когда поддельные часы дойдут до `at`.
@MainActor final class FakeAccessCheck: AccessChecking {
    private let resolve: () -> AccessResult?
    init(_ resolve: @escaping () -> AccessResult?) { self.resolve = resolve }
    var result: AccessResult? { resolve() }
}

/// Поддельный доступ к папке ядра.
@MainActor final class FakeAccess: AccessProbing {
    /// Что ответит проверка.
    var answer: AccessResult = .granted
    /// Когда (по поддельным часам) придёт ответ; `nil` — сразу, `.infinity` — никогда.
    var answerAt: TimeInterval?
    var checks = 0
    private let clock: FakeClock

    init(clock: FakeClock) { self.clock = clock }

    func check(_ dir: URL) -> any AccessChecking {
        checks += 1
        let answer = self.answer
        let at = answerAt
        return FakeAccessCheck { [clock] in
            guard let at else { return answer }
            return clock.now >= at ? answer : nil
        }
    }
}

/// Поддельный процесс ядра.
@MainActor final class FakeHandle: CoreHandle {
    let pid: Int32
    var isRunning = true
    var exitCode: Int32?
    var exitsOnTerminate = true
    var terminateCount = 0
    var killCount = 0
    private var exitCallbacks: [@Sendable (Int32) -> Void] = []

    init(pid: Int32) { self.pid = pid }

    /// Процесс выходит сам и сообщает подписчикам, как настоящий.
    func exit(code: Int32 = 1) {
        isRunning = false
        exitCode = code
        exitCallbacks.forEach { $0(code) }
    }

    func terminate() {
        terminateCount += 1
        if exitsOnTerminate { isRunning = false }
    }

    func kill() {
        killCount += 1
        isRunning = false
    }

    func onExit(_ callback: @escaping @Sendable (Int32) -> Void) {
        exitCallbacks.append(callback)
    }
}

/// Поддельный запуск: запоминает аргументы и выданные процессы.
@MainActor final class FakeLauncher: CoreLaunching {
    var handles: [FakeHandle] = []
    var lastUv: URL?
    var lastCwd: URL?
    var lastEnv: [String: String]?
    var exitsOnTerminate = true

    func launch(uv: URL, cwd: URL, env: [String: String]) throws -> any CoreHandle {
        lastUv = uv
        lastCwd = cwd
        lastEnv = env
        let handle = FakeHandle(pid: Int32(100 + handles.count))
        handle.exitsOnTerminate = exitsOnTerminate
        handles.append(handle)
        return handle
    }
}

/// Поддельный опрос `status` и `restart`.
@MainActor final class FakeProbe: StatusProbing {
    var result: ProbeResult = .unreachable
    var statusCalls = 0
    var restartAccepted = false
    var restartCalls = 0
    /// `true` — `status` ждёт `release()`.
    var hold = false
    private(set) var waiter: CheckedContinuation<Void, Never>?

    func status(port: Int, token: String) async -> ProbeResult {
        statusCalls += 1
        if hold { await withCheckedContinuation { waiter = $0 } }
        return result
    }

    /// Отпускает ждущий `status`.
    func release() {
        hold = false
        waiter?.resume()
        waiter = nil
    }

    func restart(port: Int, token: String) async -> Bool {
        restartCalls += 1
        return restartAccepted
    }
}

/// Стенд: временная папка данных, подделки и надзор без собственного цикла опроса.
@MainActor final class Rig {
    let dir: URL
    let paths: AppPaths
    let clock = FakeClock()
    let launcher = FakeLauncher()
    let probe = FakeProbe()
    lazy var access = FakeAccess(clock: clock)
    var alive: Set<Int32> = []
    /// Время (по поддельным часам), когда pid перестаёт быть живым.
    var diesAt: [Int32: TimeInterval] = [:]
    var uvExists = true
    /// Командные строки процессов по pid (для «Взять управление»).
    var commandLines: [Int32: [String]] = [:]
    /// Посланные сигналы.
    private(set) var signals: [(pid: Int32, signal: Int32)] = []
    /// pid, которые сразу выходят по SIGTERM.
    var exitsOnTerm: Set<Int32> = []
    private(set) var changes: [CoreState] = []
    private(set) lazy var supervisor: CoreSupervisor = makeSupervisor()

    /// - Parameter repo: путь репозитория внутри временной «домашней» папки
    ///   (`Documents/SmartEsp` — защищённая папка).
    init(repo: String = "repo") {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("smartesp-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        paths = AppPaths(repo: dir.appendingPathComponent(repo), dataDir: dir.appendingPathComponent("data"))
    }

    private func makeSupervisor() -> CoreSupervisor {
        let sup = CoreSupervisor(
            paths: paths, launcher: launcher, probe: probe, access: access,
            clock: { [unowned self] in clock.now },
            sleep: { [unowned self] in await clock.sleep($0) },
            fileExists: { [unowned self] _ in uvExists },
            pidAlive: { [unowned self] in alive.contains($0) && clock.now < diesAt[$0, default: .infinity] },
            env: ["PATH": "/bin"], home: dir, autoPoll: false,
            commandLine: { [unowned self] in commandLines[$0] },
            sendSignal: { [unowned self] pid, signal in
                signals.append((pid, signal))
                if signal == SIGTERM, exitsOnTerm.contains(pid) { alive.remove(pid) }
                return alive.contains(pid) || exitsOnTerm.contains(pid)
            })
        sup.onChange = { [unowned self] in changes.append($0) }
        return sup
    }

    func writeRunFile(port: Int, pid: Int32) {
        write(#"{"port": \#(port), "pid": \#(pid), "started_at": 1.5}"#, to: paths.runFile)
    }

    func writeToken(_ token: String = "tok") {
        write(token + "\n", to: paths.tokenFile)
    }

    func writeStderr(_ text: String) {
        write(text, to: paths.stderrLogFile)
    }

    func appendLog(_ lines: [String]) {
        let url = paths.logFile
        let old = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        write(old + lines.map { $0 + "\n" }.joined(), to: url)
    }

    /// Последний запущенный процесс «падает».
    func crashLast() {
        launcher.handles.last?.isRunning = false
    }

    private func write(_ text: String, to url: URL) {
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? text.write(to: url, atomically: true, encoding: .utf8)
    }
}
