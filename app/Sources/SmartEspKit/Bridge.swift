import Foundation

/// Имя обработчика сообщений: `window.webkit.messageHandlers.smartesp.postMessage({action})`.
public let bridgeMessageName = "smartesp"

/// Скрипт, который приложение встраивает в страницу: интерфейс по нему узнаёт, что мост есть.
public let bridgeUserScript = "window.smartespBridge = true;"

/// Действия, которые интерфейс может попросить у приложения. Других нет.
public enum BridgeAction: String, CaseIterable, Sendable {
    /// Открыть папку данных в Finder.
    case openDataFolder
    /// Открыть `config.yaml` в редакторе.
    case openConfig
    /// Показать журнал ядра в Finder.
    case revealLog

    /// Разбирает тело сообщения.
    /// - Parameter body: `message.body` из WebKit; ждём ровно `{action: "<имя>"}`.
    /// - Returns: действие или `nil`, если тело не такое (лишние ключи, чужое имя, не строка).
    public static func parse(_ body: Any) -> BridgeAction? {
        guard let dict = body as? [String: Any], dict.count == 1,
              let name = dict["action"] as? String else { return nil }
        return BridgeAction(rawValue: name)
    }
}

/// Что сделать с файлом по просьбе интерфейса.
public enum BridgeTarget: Equatable, Sendable {
    /// Открыть (папку — в Finder).
    case open(URL)
    /// Открыть текстовый файл в редакторе по умолчанию (нет такого — в TextEdit).
    case openText(URL)
    /// Показать файл в Finder.
    case reveal(URL)
}

/// Куда ведёт действие моста. Нет файла — его папка; нет и папки — ничего.
/// - Parameters:
///   - action: действие.
///   - paths: пути папки данных.
///   - exists: есть ли файл или папка по пути.
/// - Returns: что открыть или `nil`.
public func bridgeTarget(_ action: BridgeAction, paths: AppPaths, exists: (String) -> Bool) -> BridgeTarget? {
    let data = exists(paths.dataDir.path) ? BridgeTarget.open(paths.dataDir) : nil
    switch action {
    case .openDataFolder:
        return data
    case .openConfig:
        return exists(paths.configFile.path) ? .openText(paths.configFile) : data
    case .revealLog:
        if exists(paths.logFile.path) { return .reveal(paths.logFile) }
        return exists(paths.logsDir.path) ? .open(paths.logsDir) : data
    }
}

/// Принимать ли сообщение моста от страницы с таким адресом: только интерфейс ядра.
/// - Parameters:
///   - scheme: схема страницы-отправителя.
///   - host: хост страницы-отправителя.
/// - Returns: `true` для `http://127.0.0.1` и `http://localhost`.
public func isTrustedBridgeOrigin(scheme: String, host: String) -> Bool {
    scheme.lowercased() == "http" && ["127.0.0.1", "localhost"].contains(host.lowercased())
}
