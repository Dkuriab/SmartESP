import AppKit
import SmartEspKit

/// Один экземпляр приложения: второй показывает окно первого и выходит.
/// Если первый как раз выходит (останавливает ядро) — второй ждёт его выхода и запускается сам.
@MainActor enum SingleInstance {
    /// Уведомление «покажи окно», которое второй экземпляр шлёт первому.
    private nonisolated static let showWindow = Notification.Name("com.smartesp.app.showWindow")
    /// Ответ первого: `object` — `SingleInstanceAnswer.rawValue`.
    private nonisolated static let showWindowAnswer = Notification.Name("com.smartesp.app.showWindowAnswer")

    /// Проверяет, не запущен ли уже экземпляр с тем же bundle id. Если запущен —
    /// просит его показать окно, активирует и возвращает `true` (этому экземпляру пора выйти).
    /// Первый ответил, что выходит, — ждёт его выхода (до 20 с) и возвращает `false`.
    /// Без bundle id (запуск не из `.app`) проверки нет.
    /// - Returns: `true`, если этому экземпляру пора выйти.
    static func handOffToRunning() -> Bool {
        guard let bundleId = Bundle.main.bundleIdentifier else { return false }
        let me = ProcessInfo.processInfo.processIdentifier
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: bundleId)
            .filter { $0.processIdentifier != me && !$0.isTerminated }
        guard let first = others.first else { return false }
        if secondInstanceAction(firstAnswer: askToShowWindow()) == .waitThenLaunch {
            waitForExit(first.processIdentifier)
            return false
        }
        // С macOS 14 активация не отбирается силой: сначала уступаем её первому экземпляру
        NSApplication.shared.yieldActivation(to: first)
        first.activate()
        return true
    }

    /// Подписывает первый экземпляр на просьбы второго показать окно.
    /// - Parameter handler: показывает окно (если не идёт выход) и возвращает ответ второму.
    static func listen(_ handler: @escaping @MainActor () -> SingleInstanceAnswer) {
        DistributedNotificationCenter.default().addObserver(
            forName: showWindow, object: nil, queue: .main
        ) { _ in
            let answer = MainActor.assumeIsolated { handler() }
            DistributedNotificationCenter.default().postNotificationName(
                showWindowAnswer, object: answer.rawValue, userInfo: nil, deliverImmediately: true)
        }
    }

    /// Шлёт первому «покажи окно» и ждёт ответа не дольше `replyWait`.
    /// - Returns: ответ или `nil`, если первый не ответил (старая версия, завис).
    private static func askToShowWindow() -> SingleInstanceAnswer? {
        let box = AnswerBox()
        let center = DistributedNotificationCenter.default()
        let observer = center.addObserver(forName: showWindowAnswer, object: nil, queue: nil) { note in
            box.set((note.object as? String).flatMap(SingleInstanceAnswer.init(rawValue:)))
        }
        defer { center.removeObserver(observer) }
        center.postNotificationName(showWindow, object: nil, userInfo: nil, deliverImmediately: true)
        // Приложение ещё не запущено — уведомления доставляет только крутящийся цикл событий
        spin(until: Date().addingTimeInterval(SingleInstanceTiming.replyWait)) { box.get() != nil }
        return box.get()
    }

    /// Ждёт выхода процесса не дольше `quitWait`.
    private static func waitForExit(_ pid: Int32) {
        spin(until: Date().addingTimeInterval(SingleInstanceTiming.quitWait)) { !isProcessAlive(pid) }
    }

    private static func spin(until deadline: Date, _ done: () -> Bool) {
        while !done() && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
        }
    }
}

/// Ответ первого экземпляра под замком: его пишет обработчик уведомления.
private final class AnswerBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: SingleInstanceAnswer?

    func set(_ answer: SingleInstanceAnswer?) {
        lock.lock()
        value = answer
        lock.unlock()
    }

    func get() -> SingleInstanceAnswer? {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}
