import Foundation

/// Открывать ли ссылку во внешнем браузере, а не в окне приложения.
/// - Parameter url: адрес перехода.
/// - Returns: `true` для http(s) и mailto не на 127.0.0.1/localhost.
public func opensExternally(_ url: URL) -> Bool {
    switch url.scheme?.lowercased() {
    case "mailto":
        return true
    case "http", "https":
        return !["127.0.0.1", "localhost"].contains(url.host?.lowercased() ?? "")
    default:
        return false
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
