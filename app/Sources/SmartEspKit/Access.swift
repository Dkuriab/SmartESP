import Foundation

/// Итог проверки доступа к папке.
public enum AccessResult: Equatable, Sendable {
    /// Папка читается.
    case granted
    /// macOS не дала доступ (EPERM/EACCES: «Не разрешать» в окне Файлы и папки).
    case denied
    /// Другая ошибка (например, папки нет) — текст для меню.
    case failed(String)
}

/// Идущая проверка доступа; результат читается при опросе.
@MainActor public protocol AccessChecking: AnyObject {
    /// Результат или `nil`, пока проверка идёт (macOS ждёт ответа на запрос доступа).
    var result: AccessResult? { get }
}

/// Проверка доступа к папке ядра до запуска `uv`.
@MainActor public protocol AccessProbing: AnyObject {
    /// Начинает проверку и сразу возвращается.
    /// - Parameter dir: папка `<repo>/core`.
    /// - Returns: проверка, которую можно опрашивать.
    func check(_ dir: URL) -> any AccessChecking
}

/// Адрес раздела «Файлы и папки» в Системных настройках.
public let accessSettingsURL = URL(
    string: "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders")!

/// Папки, доступ к которым macOS даёт только с разрешения (TCC).
private let protectedFolders = [("Documents", "Документы"), ("Desktop", "Рабочий стол"), ("Downloads", "Загрузки")]

/// Защищённая папка, внутри которой лежит путь.
/// - Parameters:
///   - url: путь (например, репозиторий).
///   - home: домашняя папка пользователя.
/// - Returns: русское имя папки («Документы», «Рабочий стол», «Загрузки») или `nil`.
public func protectedFolderName(of url: URL, home: URL) -> String? {
    let path = url.standardizedFileURL.path
    for (dir, name) in protectedFolders {
        let root = home.appendingPathComponent(dir).standardizedFileURL.path
        if path == root || path.hasPrefix(root + "/") { return name }
    }
    return nil
}

/// Подсказка, как дать доступ к папке.
/// - Parameter folder: русское имя папки.
/// - Returns: две строки через `\n`.
public func accessHint(folder: String) -> String {
    "macOS спрашивает доступ — нажмите «Разрешить».\n" + settingsPathHint(folder: folder)
}

/// Подсказка, когда ядро долго молчит после запуска: причина не известна точно.
/// - Parameter folder: русское имя папки.
/// - Returns: три строки через `\n`: про запрос доступа, путь в настройках и про «Журнал».
public func silentStartHint(folder: String) -> String {
    "Возможно, macOS спрашивает доступ — нажмите «Разрешить».\n" + settingsPathHint(folder: folder)
        + "\n…или ядро ещё ставит зависимости — откройте «Журнал»."
}

/// Где включить доступ вручную.
private func settingsPathHint(folder: String) -> String {
    "Если окна нет: Системные настройки → Конфиденциальность и безопасность → "
        + "Файлы и папки → SmartEsp → «Папка „\(folder)“»."
}

/// Настоящая проверка: чтение списка файлов папки в фоновом потоке. Пока macOS
/// показывает запрос доступа, вызов висит — так приложение само вызывает запрос
/// и знает, что ждёт ответа, а не запускает `uv`, который зависнет молча.
@MainActor public final class FileAccessProbe: AccessProbing {
    public init() {}

    public func check(_ dir: URL) -> any AccessChecking {
        let check = FileAccessCheck()
        let box = check.box
        let path = dir.path
        DispatchQueue.global(qos: .userInitiated).async {
            box.set(Self.probe(path))
        }
        return check
    }

    private nonisolated static func probe(_ path: String) -> AccessResult {
        do {
            _ = try FileManager.default.contentsOfDirectory(atPath: path)
            return .granted
        } catch let error as NSError {
            let posix = (error.userInfo[NSUnderlyingErrorKey] as? NSError)
                .flatMap { $0.domain == NSPOSIXErrorDomain ? Int32($0.code) : nil }
            if error.code == NSFileReadNoPermissionError || posix == EPERM || posix == EACCES {
                return .denied
            }
            if error.code == NSFileReadNoSuchFileError || posix == ENOENT {
                return .failed("Нет папки ядра: \(path)")
            }
            return .failed("Нет доступа к \(path): \(error.localizedDescription)")
        }
    }
}

/// Проверка, результат которой пишет фоновый поток.
@MainActor final class FileAccessCheck: AccessChecking {
    let box = ResultBox()
    var result: AccessResult? { box.get() }
}

/// Результат под замком: пишет фоновый поток, читает главный.
final class ResultBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: AccessResult?

    func set(_ result: AccessResult) {
        lock.lock()
        value = result
        lock.unlock()
    }

    func get() -> AccessResult? {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}
