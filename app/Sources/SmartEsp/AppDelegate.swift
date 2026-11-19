import AppKit
import SmartEspKit

/// Связка: надзор за ядром → меню и окно; выход дожидается остановки ядра.
@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, StatusMenuActions {
    private var paths: AppPaths?
    private var supervisor: CoreSupervisor?
    private var statusMenu: StatusMenu?
    private var window: MainWindow?
    private var quitting = false

    /// Состояние для меню и окна; без путей — ошибка вместо надзора.
    private var state: CoreState { supervisor?.state ?? .failed(CoreErrors.repoNotSet) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = MainMenu.make()
        statusMenu = StatusMenu(actions: self)
        let window = MainWindow()
        // Закрытое окно прячет значок из Dock; приложение остаётся в строке меню
        window.onClose = { NSApp.setActivationPolicy(.accessory) }
        self.window = window
        SingleInstance.listen { [weak self] in self?.openWindow() }
        startSupervisor()
        render()
        openWindow()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWindow()
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let supervisor else { return .terminateNow }
        if quitting { return .terminateLater }
        quitting = true
        statusMenu?.showQuitting()
        Task {
            await supervisor.stop()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    // MARK: - StatusMenuActions

    func openWindow() {
        NSApp.setActivationPolicy(.regular)
        window?.present()
        NSApp.activate()
    }

    func restartCore() {
        guard let supervisor else { return }
        Task { await supervisor.restart() }
    }

    func openLog() {
        guard let paths else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", "Console", paths.logFile.path]
        try? process.run()
    }

    // MARK: - Внутреннее

    private func startSupervisor() {
        let env = ProcessInfo.processInfo.environment
        let home = FileManager.default.homeDirectoryForCurrentUser
        guard let paths = AppPaths.resolve(env: env, infoPlist: Bundle.main.infoDictionary ?? [:], home: home)
        else { return }
        self.paths = paths
        let supervisor = CoreSupervisor(
            paths: paths,
            launcher: ProcessCoreLauncher(stderrLog: paths.stderrLogFile),
            probe: HTTPStatusProbe())
        supervisor.onChange = { [weak self] _ in self?.render() }
        self.supervisor = supervisor
        supervisor.start()
    }

    /// Показывает текущее состояние в меню и окне. Во время выхода меню держит
    /// «Останавливаю ядро…» до самого конца.
    private func render() {
        guard !quitting else { return }
        let current = state
        // «Запускать при входе» — задача 4; пока всегда выключено
        statusMenu?.show(
            menuModel(state: current, loginEnabled: false),
            canRestart: supervisor != nil, hasLog: paths != nil)
        window?.show(windowContent(state: current, token: supervisor?.token))
    }
}
