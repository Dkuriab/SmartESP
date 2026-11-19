import Foundation

/// Запуск приложения при входе в систему.
@MainActor public protocol LoginItemControlling: AnyObject {
    /// Включён ли запуск при входе.
    var isEnabled: Bool { get }
    /// Включает или выключает запуск при входе.
    /// - Parameter on: `true` — включить.
    func setEnabled(_ on: Bool) throws
}

/// Ключ `UserDefaults`: пользователь (или первый запуск из `/Applications`) уже решил про автозапуск.
public let loginItemDecidedKey = "loginItemDecided"

/// Включать ли автозапуск при первом запуске.
/// - Parameters:
///   - bundlePath: путь к `.app`.
///   - alreadyDecided: пользователь уже решал (`loginItemDecided`).
/// - Returns: `true` только для `/Applications/…` и только если ещё не решал —
///   проверочные сборки не прописываются в автозапуск.
public func firstLaunchDefault(bundlePath: String, alreadyDecided: Bool) -> Bool {
    !alreadyDecided && bundlePath.hasPrefix("/Applications/")
}

/// Метка и имя файла запасного LaunchAgent.
public let launchAgentLabel = "com.smartesp.app"

/// Содержимое plist запасного LaunchAgent: `open -a <приложение>` при входе.
/// - Parameter appPath: путь к приложению, по умолчанию `/Applications/SmartEsp.app`.
/// - Returns: XML-plist.
public func launchAgentPlist(appPath: String = "/Applications/SmartEsp.app") throws -> Data {
    let plist: [String: Any] = [
        "Label": launchAgentLabel,
        "ProgramArguments": ["/usr/bin/open", "-a", appPath],
        "RunAtLoad": true,
    ]
    return try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
}

/// Файл запасного LaunchAgent в папке `~/Library/LaunchAgents`.
public struct LaunchAgentFile: Sendable {
    /// Папка LaunchAgents.
    public let directory: URL

    /// - Parameter directory: папка LaunchAgents (по умолчанию в домашней).
    public init(directory: URL) { self.directory = directory }

    /// Путь к plist.
    public var url: URL { directory.appendingPathComponent(launchAgentLabel + ".plist") }

    /// Файл есть.
    public var exists: Bool { FileManager.default.fileExists(atPath: url.path) }

    /// Создаёт папку при необходимости и пишет plist.
    public func install() throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try launchAgentPlist().write(to: url, options: .atomic)
    }

    /// Удаляет plist, если он есть.
    public func remove() throws {
        if exists { try FileManager.default.removeItem(at: url) }
    }
}

/// Перезапускать ли загрузку страницы после ошибки.
/// - Parameters:
///   - domain: домен ошибки.
///   - code: код ошибки.
/// - Returns: `true` для сетевых ошибок (`NSURLErrorDomain`, кроме отмены);
///   «frame load interrupted» (WebKit, код 102) — нет: это не сбой сети.
public func shouldRetryLoad(domain: String, code: Int) -> Bool {
    domain == NSURLErrorDomain && code != NSURLErrorCancelled
}
