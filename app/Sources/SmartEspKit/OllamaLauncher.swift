import Darwin
import Foundation

/// Настоящая проверка Ollama: `GET /api/version` с таймаутом 1 с.
@MainActor public final class HTTPOllamaProbe: OllamaProbing {
    private let session: URLSession
    private let url: URL

    /// - Parameter url: адрес проверки.
    public init(url: URL = URL(string: "http://127.0.0.1:11434/api/version")!) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 1
        config.timeoutIntervalForResource = 1
        session = URLSession(configuration: config)
        self.url = url
    }

    public func isUp() async -> Bool {
        guard let (_, response) = try? await session.data(from: url) else { return false }
        return (response as? HTTPURLResponse)?.statusCode == 200
    }
}

/// Ошибка запуска `ollama serve`.
public struct SpawnError: LocalizedError {
    /// Код `errno`.
    public let code: Int32
    public var errorDescription: String? { String(cString: strerror(code)) }
}

/// Настоящий запуск Ollama.
@MainActor public final class ProcessOllamaLauncher: OllamaLaunching {
    private let log: URL
    private let env: [String: String]

    /// - Parameters:
    ///   - log: куда дописывать вывод `ollama serve`.
    ///   - env: окружение для `ollama serve`.
    public init(log: URL, env: [String: String]) {
        self.log = log
        self.env = env
    }

    public func openApp(_ app: URL) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", app.path]
        try process.run()
    }

    public func serve(_ binary: URL) throws {
        try FileManager.default.createDirectory(
            at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
        let pid = try spawnDetached(binary.path, ["serve"], env: env, log: log.path)
        // Забираем код выхода, чтобы вышедший процесс не висел зомби, пока живо приложение
        Thread.detachNewThread {
            var status: Int32 = 0
            _ = waitpid(pid, &status, 0)
        }
    }
}

/// Запускает программу в своей сессии (`setsid`): stdin — `/dev/null`, stdout и stderr
/// дописываются в журнал, остальные дескрипторы приложения не наследуются
/// (иначе процесс держал бы, например, трубу stdin ядра).
/// - Returns: pid запущенного процесса.
/// - Throws: `SpawnError` с кодом ошибки `posix_spawn`.
private func spawnDetached(_ path: String, _ arguments: [String], env: [String: String], log: String) throws -> pid_t {
    var attr: posix_spawnattr_t?
    posix_spawnattr_init(&attr)
    defer { posix_spawnattr_destroy(&attr) }
    posix_spawnattr_setflags(&attr, Int16(POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT))
    var actions: posix_spawn_file_actions_t?
    posix_spawn_file_actions_init(&actions)
    defer { posix_spawn_file_actions_destroy(&actions) }
    posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
    posix_spawn_file_actions_addopen(&actions, 1, log, O_WRONLY | O_CREAT | O_APPEND, 0o644)
    posix_spawn_file_actions_adddup2(&actions, 1, 2)
    let argv = ([path] + arguments).map { strdup($0) } + [nil]
    let envp = env.map { strdup("\($0.key)=\($0.value)") } + [nil]
    defer { (argv + envp).forEach { free($0) } }
    var pid: pid_t = 0
    let code = posix_spawn(&pid, path, &actions, &attr, argv, envp)
    guard code == 0 else { throw SpawnError(code: code) }
    return pid
}
