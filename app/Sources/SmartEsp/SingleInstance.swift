import AppKit

/// Один экземпляр приложения: второй показывает окно первого и выходит.
@MainActor enum SingleInstance {
    /// Уведомление «покажи окно», которое второй экземпляр шлёт первому.
    private static let showWindow = Notification.Name("com.smartesp.app.showWindow")

    /// Проверяет, не запущен ли уже экземпляр с тем же bundle id. Если запущен —
    /// просит его показать окно, активирует и возвращает `true` (этому экземпляру пора выйти).
    /// Без bundle id (запуск не из `.app`) проверки нет.
    /// - Returns: `true`, если уже работает другой экземпляр.
    static func handOffToRunning() -> Bool {
        guard let bundleId = Bundle.main.bundleIdentifier else { return false }
        let me = ProcessInfo.processInfo.processIdentifier
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: bundleId)
            .filter { $0.processIdentifier != me && !$0.isTerminated }
        guard let first = others.first else { return false }
        DistributedNotificationCenter.default().postNotificationName(
            showWindow, object: nil, userInfo: nil, deliverImmediately: true)
        first.activate()
        return true
    }

    /// Подписывает первый экземпляр на просьбы второго показать окно.
    /// - Parameter handler: показывает окно.
    static func listen(_ handler: @escaping @MainActor () -> Void) {
        DistributedNotificationCenter.default().addObserver(
            forName: showWindow, object: nil, queue: .main
        ) { _ in
            MainActor.assumeIsolated { handler() }
        }
    }
}
