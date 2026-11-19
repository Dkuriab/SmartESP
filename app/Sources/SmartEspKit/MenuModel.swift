import Foundation

/// Тексты ошибок ядра, на которые меню реагирует особо.
public enum CoreErrors {
    /// `uv` не найден ни в одном из известных мест.
    public static let uvNotFound = "Не найден uv"
    /// В `Info.plist` нет пути к репозиторию, и `SMARTESP_REPO` не задана.
    public static let repoNotSet = "Не задан путь к репозиторию (SmartEspRepoPath в Info.plist)"
}

/// Что показывает меню в строке меню.
public struct MenuModel: Equatable, Sendable {
    /// Строка состояния (первый пункт меню и подсказка значка).
    public let statusText: String
    /// Имя символа SF для значка.
    public let symbolName: String
    /// Подсказка под строкой состояния (как поставить `uv`, как дать доступ к папке);
    /// строки через `\n`; `nil` — нет.
    public let hint: String?
    /// Показывать «Открыть настройки доступа».
    public let showsAccessSettings: Bool
    /// Доступен ли «Открыть SmartESP».
    public let canOpen: Bool
    /// Доступен ли «Перезапустить ядро».
    public let canRestart: Bool
}

private enum Symbol {
    static let busy = "waveform.circle"
    static let ok = "waveform.circle.fill"
    static let problem = "exclamationmark.triangle.fill"
}

/// Строит модель меню по состоянию ядра.
/// - Parameters:
///   - state: состояние ядра.
/// - Returns: строка состояния, символ значка, подсказка и доступность пунктов.
public func menuModel(state: CoreState) -> MenuModel {
    let (text, symbol) = describe(state)
    var hint: String?
    var showsAccessSettings = false
    switch state {
    case .failed(CoreErrors.uvNotFound):
        hint = "Установите uv: https://docs.astral.sh/uv/"
    case let .waitingForAccess(folder), let .accessDenied(folder):
        hint = accessHint(folder: folder)
        showsAccessSettings = true
    case let .silentStart(folder):
        hint = silentStartHint(folder: folder)
        showsAccessSettings = true
    default:
        break
    }
    var canRestart = true
    if case .stopping = state { canRestart = false }
    return MenuModel(
        statusText: text, symbolName: symbol, hint: hint, showsAccessSettings: showsAccessSettings,
        canOpen: true, canRestart: canRestart)
}

/// Строка состояния и символ значка.
private func describe(_ state: CoreState) -> (String, String) {
    switch state {
    case .stopped:
        return ("Ядро остановлено", Symbol.problem)
    case .starting:
        return ("Ядро запускается…", Symbol.busy)
    case .stopping:
        return ("Останавливаю ядро…", Symbol.busy)
    case let .failed(message):
        return ("Ошибка: \(message)", Symbol.problem)
    case let .waitingForAccess(folder):
        return ("Нужно разрешение на папку «\(folder)»", Symbol.problem)
    case let .accessDenied(folder):
        return ("Ошибка: нет доступа к папке «\(folder)»", Symbol.problem)
    case let .silentStart(folder):
        return ("Ядро молчит — возможно, ждёт доступа к папке «\(folder)»", Symbol.busy)
    case let .running(_, phase, devices, ollama):
        let details = " · колонок \(devices.online) из \(devices.total) · Ollama \(ollama ? "✓" : "✗")"
        switch phase {
        case "warming": return ("Ядро прогревается" + details, Symbol.busy)
        case "stopping": return ("Ядро останавливается…", Symbol.busy)
        default: return ("Ядро работает" + details, Symbol.ok)
        }
    case let .external(_, phase, _, _):
        return ("Ядро запущено не из приложения", phase == "ready" ? Symbol.ok : Symbol.busy)
    }
}

/// Что показывать в окне: страницу ядра или заглушку с текстом.
public enum WindowContent: Equatable, Sendable {
    /// Веб-интерфейс ядра.
    case page(URL)
    /// Заглушка с текстом вместо страницы.
    case placeholder(String)

    /// Нужно ли грузить страницу заново при переходе к этому содержимому.
    /// - Parameter previous: что было показано раньше (`nil` — ничего).
    /// - Returns: `true`, если это страница и она отличается от прежней
    ///   (другой адрес или до этого была заглушка — ядро могло перезапуститься).
    public func needsLoad(after previous: WindowContent?) -> Bool {
        guard case .page = self else { return false }
        return self != previous
    }
}

/// Решает, что показывать в окне. Страница — только когда ядро отвечает
/// (`running` или `external`) и токен прочитан.
/// - Parameters:
///   - state: состояние ядра (порт берётся из него).
///   - token: токен доступа к API.
/// - Returns: адрес `http://127.0.0.1:<port>/?token=<token>` или заглушка.
public func windowContent(state: CoreState, token: String?) -> WindowContent {
    switch state {
    case let .running(port, _, _, _), let .external(port, _, _, _):
        guard let token, let url = coreURL(port: port, token: token) else {
            return .placeholder("Ядро запускается…")
        }
        return .page(url)
    case .starting:
        return .placeholder("Ядро запускается…")
    default:
        let model = menuModel(state: state)
        return .placeholder(model.statusText + (model.hint.map { "\n\n" + $0 } ?? ""))
    }
}

/// Адрес веб-интерфейса ядра с токеном в запросе.
private func coreURL(port: Int, token: String) -> URL? {
    var allowed = CharacterSet.urlQueryAllowed
    allowed.remove(charactersIn: "+&=")
    guard let encoded = token.addingPercentEncoding(withAllowedCharacters: allowed) else { return nil }
    return URL(string: "http://127.0.0.1:\(port)/?token=\(encoded)")
}
