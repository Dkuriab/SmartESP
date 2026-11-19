import Foundation

/// Новые строки журнала ядра (записанные после запуска процесса).
public struct CoreLogExcerpt: Equatable, Sendable {
    /// Непустые строки по порядку.
    public let lines: [String]

    /// Последняя строка с уровнем ERROR или CRITICAL. После падения ядро ещё пишет
    /// «Ядро остановлено» — такая строка причину не объясняет.
    public var errorLine: String? {
        lines.last(where: { $0.contains(" ERROR ") || $0.contains(" CRITICAL ") })
    }

    /// uvicorn не смог занять порт («address already in use»).
    public var portConflict: Bool {
        lines.contains { $0.localizedCaseInsensitiveContains("address already in use") }
    }

    /// Порт из сообщения uvicorn `... ('127.0.0.1', 8765): address already in use`.
    public var conflictPort: Int? {
        for line in lines.reversed() {
            if let match = line.firstMatch(of: /, (\d+)\)\s*:\s*address already in use/) {
                return Int(match.1)
            }
        }
        return nil
    }
}

/// Чтение журнала ядра `logs/core.log`.
public enum CoreLog {
    /// Сколько байт журнала читать не больше (хвост).
    static let maxBytes: UInt64 = 64 * 1024

    /// Размер журнала.
    /// - Parameter url: путь к журналу.
    /// - Returns: размер в байтах, 0 — если файла нет.
    public static func size(_ url: URL) -> UInt64 {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        return (attrs?[.size] as? NSNumber)?.uint64Value ?? 0
    }

    /// Читает строки, дописанные после смещения.
    /// - Parameters:
    ///   - url: путь к журналу.
    ///   - offset: размер журнала в момент запуска. Если файл стал короче
    ///     (журнал повернулся), читается с начала.
    /// - Returns: не больше последних 64 КБ новых строк.
    public static func read(_ url: URL, from offset: UInt64) -> CoreLogExcerpt {
        guard let file = try? FileHandle(forReadingFrom: url) else { return CoreLogExcerpt(lines: []) }
        defer { try? file.close() }
        let end = (try? file.seekToEnd()) ?? 0
        var start = offset <= end ? offset : 0
        if end - start > maxBytes { start = end - maxBytes }
        try? file.seek(toOffset: start)
        let data = (try? file.readToEnd()) ?? Data()
        let text = String(decoding: data, as: UTF8.self)
        let lines = text.split(whereSeparator: \.isNewline)
            .map { String($0) }
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        return CoreLogExcerpt(lines: lines)
    }
}
