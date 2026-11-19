import Foundation

/// Пути приложения: репозиторий и папка данных ядра.
public struct AppPaths: Equatable, Sendable {
    /// Корень репозитория SmartESP.
    public let repo: URL
    /// Папка данных ядра (`SMARTESP_HOME` или `~/SmartEsp`).
    public let dataDir: URL

    public init(repo: URL, dataDir: URL) {
        self.repo = repo
        self.dataDir = dataDir
    }

    /// Папка Python-ядра (`<repo>/core`).
    public var coreDir: URL { repo.appendingPathComponent("core") }
    /// Файл с pid и портом запущенного ядра.
    public var runFile: URL { dataDir.appendingPathComponent("run/core.json") }
    /// Файл с токеном доступа.
    public var tokenFile: URL { dataDir.appendingPathComponent("token") }
    /// Журнал ядра.
    public var logFile: URL { dataDir.appendingPathComponent("logs/core.log") }
    /// stderr процесса ядра (`uv` и Python до настройки журнала); очищается при каждом запуске.
    public var stderrLogFile: URL { dataDir.appendingPathComponent("logs/core-stderr.log") }

    /// Определяет пути.
    /// - Parameters:
    ///   - env: переменные окружения (`SMARTESP_REPO` важнее `Info.plist`, `SMARTESP_HOME` важнее `~/SmartEsp`).
    ///   - infoPlist: словарь `Info.plist` (ключ `SmartEspRepoPath`).
    ///   - home: домашняя папка пользователя.
    /// - Returns: пути или `nil`, если путь к репозиторию не задан.
    public static func resolve(env: [String: String], infoPlist: [String: Any], home: URL) -> AppPaths? {
        let repoPath = nonEmpty(env["SMARTESP_REPO"]) ?? nonEmpty(infoPlist["SmartEspRepoPath"] as? String)
        guard let repoPath else { return nil }
        let data = nonEmpty(env["SMARTESP_HOME"]).map { URL(fileURLWithPath: $0) }
            ?? home.appendingPathComponent("SmartEsp")
        return AppPaths(repo: URL(fileURLWithPath: repoPath), dataDir: data)
    }

    private static func nonEmpty(_ value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        return value
    }
}

/// Ищет `uv`: `~/.local/bin/uv`, `/opt/homebrew/bin/uv`, `/usr/local/bin/uv`, затем `PATH`.
/// - Parameters:
///   - env: переменные окружения (берётся `PATH`).
///   - home: домашняя папка пользователя.
///   - fileExists: проверка наличия исполняемого файла по пути.
/// - Returns: путь к `uv` или `nil`.
public func findUv(env: [String: String], home: URL, fileExists: (String) -> Bool) -> URL? {
    var candidates = [
        home.appendingPathComponent(".local/bin/uv").path,
        "/opt/homebrew/bin/uv",
        "/usr/local/bin/uv",
    ]
    let dirs = (env["PATH"] ?? "").split(separator: ":").map(String.init)
    candidates += dirs.map { URL(fileURLWithPath: $0).appendingPathComponent("uv").path }
    return candidates.first(where: fileExists).map { URL(fileURLWithPath: $0) }
}
