import Foundation

/// Запуск приложения при входе в систему.
@MainActor public protocol LoginItemControlling: AnyObject {
    /// Запуск при входе включён по-настоящему (по статусу системы или по файлу LaunchAgent).
    var isEnabled: Bool { get }
    /// Что показать в меню и что делает нажатие.
    var menuState: LoginMenuState { get }
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
    /// - Parameter appPath: путь к приложению, которое откроет `open -a`.
    public func install(appPath: String = "/Applications/SmartEsp.app") throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try launchAgentPlist(appPath: appPath).write(to: url, options: .atomic)
    }

    /// Удаляет plist, если он есть.
    public func remove() throws {
        if exists { try FileManager.default.removeItem(at: url) }
    }
}

/// Статус `SMAppService` без привязки к ServiceManagement.
public enum LoginStatus: Sendable { case enabled, notRegistered, requiresApproval, notFound }

/// Что делает нажатие на «Запускать при входе».
public enum LoginClickAction: Equatable, Sendable { case enable, disable, openSettings, none }

/// Вид пункта «Запускать при входе».
public struct LoginMenuState: Equatable, Sendable {
    public enum Mark: Equatable, Sendable { case on, off, mixed }
    public let title: String
    public let mark: Mark
    public let click: LoginClickAction
}

/// Адрес «Объекты входа» в Системных настройках.
public let loginItemsSettingsURL = URL(string: "x-apple.systempreferences:com.apple.LoginItems-Settings.extension")!

/// Чистое отображение статуса автозапуска в пункт меню.
/// - Parameters:
///   - status: статус `SMAppService.mainApp`.
///   - agentExists: есть файл запасного LaunchAgent.
///   - inApplications: приложение лежит в `/Applications`.
/// - Returns: заголовок, отметка и действие по нажатию.
public func loginMenuState(status: LoginStatus, agentExists: Bool, inApplications: Bool) -> LoginMenuState {
    let on = status == .enabled || agentExists
    guard inApplications else {
        return LoginMenuState(title: "Запускать при входе (только из «Программ»)", mark: on ? .on : .off, click: .none)
    }
    let title = "Запускать при входе"
    if on { return LoginMenuState(title: title, mark: .on, click: .disable) }
    if status == .requiresApproval {
        return LoginMenuState(
            title: title + " — ожидает разрешения в Системных настройках → Основные → Объекты входа",
            mark: .mixed, click: .openSettings)
    }
    return LoginMenuState(title: title, mark: .off, click: .enable)
}
