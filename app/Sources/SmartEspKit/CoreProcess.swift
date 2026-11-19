import Darwin
import Foundation

/// Запущенный процесс ядра (`uv run python -m smartesp`).
@MainActor public protocol CoreHandle: AnyObject {
    /// pid процесса `uv`.
    var pid: Int32 { get }
    /// Процесс ещё работает.
    var isRunning: Bool { get }
    /// Просит остановиться (SIGTERM; `uv` передаёт его ядру).
    func terminate()
    /// Убивает сразу (SIGKILL) вместе с дочерним Python и закрывает stdin.
    func kill()
    /// Подписка на выход процесса.
    /// - Parameter callback: получает код выхода; может вызываться из любого потока.
    func onExit(_ callback: @escaping @Sendable (Int32) -> Void)
}

/// Запуск ядра.
@MainActor public protocol CoreLaunching: AnyObject {
    /// Запускает `<uv> run python -m smartesp --parent-watch`.
    /// - Parameters:
    ///   - uv: путь к `uv`.
    ///   - cwd: папка `<repo>/core`.
    ///   - env: окружение процесса.
    /// - Returns: запущенный процесс.
    /// - Throws: ошибку `Process.run()`.
    func launch(uv: URL, cwd: URL, env: [String: String]) throws -> any CoreHandle
}

/// Проверяет, жив ли процесс (`kill(pid, 0)`).
/// - Parameter pid: номер процесса.
/// - Returns: `true`, если процесс существует (в том числе чужой).
public func isProcessAlive(_ pid: Int32) -> Bool {
    guard pid > 0 else { return false }
    return Darwin.kill(pid, 0) == 0 || errno == EPERM
}

/// Настоящий запуск через `Process`.
@MainActor public final class ProcessCoreLauncher: CoreLaunching {
    private let stderrLog: URL?

    /// - Parameter stderrLog: куда писать stderr процесса (файл очищается при каждом запуске);
    ///   `nil` — в `/dev/null`.
    public init(stderrLog: URL? = nil) {
        self.stderrLog = stderrLog
    }

    public func launch(uv: URL, cwd: URL, env: [String: String]) throws -> any CoreHandle {
        let process = Process()
        process.executableURL = uv
        process.arguments = ["run", "python", "-m", "smartesp", "--parent-watch"]
        process.currentDirectoryURL = cwd
        process.environment = env
        // stdin — труба, которую держим открытой: ядро с --parent-watch выходит, когда она закроется
        let stdin = Pipe()
        process.standardInput = stdin
        process.standardOutput = FileHandle.nullDevice
        process.standardError = try stderrHandle()
        let notifier = ExitNotifier()
        process.terminationHandler = { notifier.fire($0.terminationStatus) }
        try process.run()
        return ProcessCoreHandle(process: process, stdin: stdin, notifier: notifier)
    }

    /// Открывает пустой файл для stderr (`uv run` может упасть до того, как Python настроит журнал).
    private func stderrHandle() throws -> FileHandle {
        guard let stderrLog else { return FileHandle.nullDevice }
        try FileManager.default.createDirectory(
            at: stderrLog.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: stderrLog.path, contents: nil)
        return try FileHandle(forWritingTo: stderrLog)
    }
}

/// Процесс ядра на `Process`.
@MainActor final class ProcessCoreHandle: CoreHandle {
    private let process: Process
    private let stdin: Pipe
    private let notifier: ExitNotifier

    init(process: Process, stdin: Pipe, notifier: ExitNotifier) {
        self.process = process
        self.stdin = stdin
        self.notifier = notifier
    }

    var pid: Int32 { process.processIdentifier }
    var isRunning: Bool { process.isRunning }

    func terminate() {
        if process.isRunning { process.terminate() }
    }

    func kill() {
        // uv не передаёт SIGKILL дочернему Python — убиваем потомков сами
        for child in childPids(of: pid) { Darwin.kill(child, SIGKILL) }
        if process.isRunning { Darwin.kill(pid, SIGKILL) }
        try? stdin.fileHandleForWriting.close()
    }

    func onExit(_ callback: @escaping @Sendable (Int32) -> Void) {
        notifier.add(callback)
    }
}

/// pid прямых потомков процесса.
private func childPids(of pid: Int32) -> [Int32] {
    var buffer = [pid_t](repeating: 0, count: 64)
    let size = Int32(buffer.count * MemoryLayout<pid_t>.size)
    let count = proc_listchildpids(pid, &buffer, size)
    guard count > 0 else { return [] }
    // pid 0 означает «своя группа процессов» — такие не отдаём
    return buffer.prefix(Int(count)).filter { $0 > 0 && $0 != pid }
}

/// Передаёт код выхода подписчикам; подписка после выхода срабатывает сразу.
final class ExitNotifier: @unchecked Sendable {
    private let lock = NSLock()
    private var code: Int32?
    private var callbacks: [@Sendable (Int32) -> Void] = []

    func add(_ callback: @escaping @Sendable (Int32) -> Void) {
        lock.lock()
        if let code {
            lock.unlock()
            callback(code)
            return
        }
        callbacks.append(callback)
        lock.unlock()
    }

    func fire(_ exitCode: Int32) {
        lock.lock()
        code = exitCode
        let pending = callbacks
        callbacks = []
        lock.unlock()
        pending.forEach { $0(exitCode) }
    }
}
