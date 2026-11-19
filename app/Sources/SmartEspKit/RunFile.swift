import Foundation

/// Содержимое `run/core.json`: порт и pid запущенного ядра.
public struct RunInfo: Decodable, Equatable, Sendable {
    /// Порт HTTP-сервера ядра.
    public let port: Int
    /// pid процесса Python, написавшего файл.
    public let pid: Int32
    /// Время запуска (секунды Unix), ключ `started_at`.
    public let startedAt: Double

    public init(port: Int, pid: Int32, startedAt: Double) {
        self.port = port
        self.pid = pid
        self.startedAt = startedAt
    }

    private enum CodingKeys: String, CodingKey {
        case port, pid
        case startedAt = "started_at"
    }
}

/// Чтение файла запуска ядра.
public enum RunFile {
    /// Читает `run/core.json`.
    /// - Parameter url: путь к файлу.
    /// - Returns: данные запуска или `nil`, если файла нет, он пуст или битый.
    public static func read(_ url: URL) -> RunInfo? {
        guard let data = try? Data(contentsOf: url), !data.isEmpty else { return nil }
        return try? JSONDecoder().decode(RunInfo.self, from: data)
    }
}

/// Чтение токена доступа к API ядра.
public enum TokenFile {
    /// Читает файл токена.
    /// - Parameter url: путь к файлу `<data>/token`.
    /// - Returns: токен без пробелов по краям или `nil`, если файла нет или он пуст.
    public static func read(_ url: URL) -> String? {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let token = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }
}
