import Foundation

/// Аргумент, с которым запасной LaunchAgent запускает приложение при входе: окно не открывать.
public let backgroundLaunchArgument = "--background"

/// Открывать ли окно сразу после запуска.
/// - Parameters:
///   - arguments: аргументы командной строки (`CommandLine.arguments`).
///   - launchedAsLoginItem: macOS запустила приложение как объект входа (событие запуска Apple Event).
/// - Returns: `false` при автозапуске (объект входа или `--background` от LaunchAgent) —
///   тогда приложение тихо живёт в строке меню.
public func opensWindowAtLaunch(arguments: [String], launchedAsLoginItem: Bool) -> Bool {
    !launchedAsLoginItem && !arguments.contains(backgroundLaunchArgument)
}

/// Ответ первого экземпляра на просьбу второго показать окно.
public enum SingleInstanceAnswer: String, Sendable {
    /// Окно показано: второму экземпляру пора выйти.
    case shown
    /// Первый экземпляр выходит (останавливает ядро) — окно не показывает.
    case quitting
}

/// Что делать второму экземпляру.
public enum SecondInstanceAction: Equatable, Sendable {
    /// Уступить первому и выйти.
    case handOff
    /// Подождать, пока первый выйдет (не дольше `SingleInstanceTiming.quitWait`), и запуститься самому.
    case waitThenLaunch
}

/// Сроки передачи между экземплярами, секунд.
public enum SingleInstanceTiming {
    /// Сколько второй экземпляр ждёт ответа первого.
    public static let replyWait: TimeInterval = 2
    /// Сколько ждать выхода первого экземпляра: остановка ядра — до 15 с плюс запас.
    public static let quitWait: TimeInterval = 20
}

/// Решение второго экземпляра по ответу первого.
/// - Parameter firstAnswer: ответ или `nil`, если первый не ответил за `replyWait`.
/// - Returns: `.waitThenLaunch`, только если первый сам сказал, что выходит.
public func secondInstanceAction(firstAnswer: SingleInstanceAnswer?) -> SecondInstanceAction {
    firstAnswer == .quitting ? .waitThenLaunch : .handOff
}
