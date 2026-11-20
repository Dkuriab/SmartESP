import Foundation

/// Что делать окну с переходом страницы.
public enum NavigationDecision: Equatable, Sendable {
    /// Загрузить в окне: адрес самого ядра.
    case allow
    /// Отдать браузеру по умолчанию: внешняя ссылка (http(s) не на ядро, mailto).
    case openExternally
    /// Ничего не делать: file://, blob:, data: и прочее. Иначе брошенный на окно файл
    /// заменил бы интерфейс своим просмотром.
    case cancel
}

private let localHosts: Set<String> = ["127.0.0.1", "localhost"]

/// Решение о переходе в окне приложения.
/// - Parameters:
///   - url: адрес перехода (`nil` — отменить).
///   - core: адрес страницы ядра; переход разрешён на тот же порт 127.0.0.1/localhost.
///     `nil` — ядро ещё не известно: разрешён любой порт 127.0.0.1/localhost.
/// - Returns: `.allow` для http(s) на ядро и `about:` (пустая страница), `.openExternally`
///   для прочих http(s) и mailto, `.cancel` для остального.
public func navigationDecision(for url: URL?, core: URL? = nil) -> NavigationDecision {
    guard let url else { return .cancel }
    switch url.scheme?.lowercased() {
    case "about":
        return .allow
    case "mailto":
        return .openExternally
    case "http", "https":
        return isCore(url, core: core) ? .allow : .openExternally
    default:
        return .cancel
    }
}

/// Адрес на ядро: 127.0.0.1/localhost и, если ядро известно, тот же порт.
private func isCore(_ url: URL, core: URL?) -> Bool {
    guard localHosts.contains(url.host?.lowercased() ?? "") else { return false }
    guard let core else { return true }
    return port(of: url) == port(of: core)
}

/// Порт адреса; не указан — по схеме (80 или 443).
private func port(of url: URL) -> Int {
    url.port ?? (url.scheme?.lowercased() == "https" ? 443 : 80)
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
