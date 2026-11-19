import AppKit
import SmartEspKit

/// Связка: надзор за ядром и Ollama → меню и окно; пульт и мост → надзор и Finder;
/// выход дожидается остановки ядра.
@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, StatusMenuActions {
    private var paths: AppPaths?
    private var supervisor: CoreSupervisor?
    private var ollama: OllamaControl?
    private var statusMenu: StatusMenu?
    private var window: MainWindow?
    private var quitting = false
    /// macOS запустила приложение как объект входа: окно не открываем.
    private var launchedAsLoginItem = false
    private let loginItem: any LoginItemControlling = LoginItemService()

    /// Состояние для меню и окна; без путей — ошибка вместо надзора.
    private var state: CoreState { supervisor?.state ?? .failed(CoreErrors.repoNotSet) }

    func applicationWillFinishLaunching(_ notification: Notification) {
        launchedAsLoginItem = Self.isLoginItemLaunch()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Событие запуска видно то в will-, то в didFinishLaunching — смотрим в обоих
        launchedAsLoginItem = launchedAsLoginItem || Self.isLoginItemLaunch()
        NSApp.mainMenu = MainMenu.make()
        statusMenu = StatusMenu(actions: self)
        let window = MainWindow()
        // Закрытое окно прячет значок из Dock; приложение остаётся в строке меню
        window.onClose = { NSApp.setActivationPolicy(.accessory) }
        window.onAction = { [weak self] in self?.perform($0) }
        window.onBridge = { [weak self] in WebBridge.perform($0, paths: self?.paths) }
        self.window = window
        SingleInstance.listen { [weak self] in self?.answerShowRequest() ?? .shown }
        applyFirstLaunchLoginDefault()
        startSupervisor()
        render()
        // При автозапуске приложение тихо живёт в строке меню
        if opensWindowAtLaunch(arguments: CommandLine.arguments, launchedAsLoginItem: launchedAsLoginItem) {
            openWindow()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWindow()
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let supervisor else { return .terminateNow }
        // Повторная просьба (ещё один «quit», выход из системы, выключение) — первая уже ждёт
        // остановки ядра; её `reply(true)` ответит и на эту. Отмена сорвала бы выход из системы
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
        // Во время выхода окно не показываем и в Dock не возвращаемся
        guard !quitting else { return }
        NSApp.setActivationPolicy(.regular)
        window?.present()
        NSApp.activate()
    }

    func restartCore() {
        guard let supervisor else { return }
        Task { await supervisor.restart() }
    }

    func openLog() {
        let files = FileManager.default
        guard let paths, files.fileExists(atPath: paths.logFile.path) else {
            // Журнала ещё нет — папка журналов, если она уже есть, иначе объяснение
            if let dir = paths?.logFile.deletingLastPathComponent(), files.fileExists(atPath: dir.path) {
                NSWorkspace.shared.open(dir)
            } else {
                showAlert("Журнала пока нет", "Ядро создаст его при первом запуске.")
            }
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", "Console", paths.logFile.path]
        try? process.run()
    }

    func toggleLoginItem() {
        let click = loginItem.menuState.click
        if click == .openSettings { NSWorkspace.shared.open(loginItemsSettingsURL) }
        guard click == .enable || click == .disable else { return }
        do {
            try loginItem.setEnabled(click == .enable)
            UserDefaults.standard.set(true, forKey: loginItemDecidedKey)
        } catch {
            showAlert("Не удалось изменить автозапуск", error.localizedDescription)
        }
        render()
    }

    func perform(_ action: ControlAction) {
        guard let supervisor, !quitting else { return }
        switch action {
        case .startCore: supervisor.start()
        case .stopCore: Task { await supervisor.stop() }
        case .takeOver: supervisor.takeOver()
        case .startOllama: Task { await self.ollama?.launch() }
        }
    }

    func menuWillOpen() {
        Task { await ollama?.refresh() }
    }

    func openAccessSettings() {
        NSWorkspace.shared.open(accessSettingsURL)
    }

    func liveLoginState() -> LoginMenuState? {
        quitting ? nil : loginItem.menuState
    }

    // MARK: - Внутреннее

    /// Второй экземпляр просит показать окно: показываем, если не выходим.
    private func answerShowRequest() -> SingleInstanceAnswer {
        if quitting { return .quitting }
        openWindow()
        return .shown
    }

    /// Текущее событие Apple — запуск объекта входа.
    private static func isLoginItemLaunch() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent,
              event.eventID == AEEventID(kAEOpenApplication) else { return false }
        return event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue
            == OSType(keyAELaunchedAsLogInItem)
    }

    /// Первый запуск из `/Applications` включает автозапуск; сборки из других мест — нет.
    private func applyFirstLaunchLoginDefault() {
        let defaults = UserDefaults.standard
        let decided = defaults.bool(forKey: loginItemDecidedKey)
        guard firstLaunchDefault(bundlePath: Bundle.main.bundlePath, alreadyDecided: decided) else { return }
        // «Решено» ставим до попытки намеренно: не удалось — не пытаемся при каждом запуске,
        // а пользователь включит вручную через меню
        defaults.set(true, forKey: loginItemDecidedKey)
        try? loginItem.setEnabled(true)
    }

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
        startOllamaControl(paths: paths, env: env, home: home)
    }

    /// Опрос Ollama и её запуск по «Запустить Ollama».
    private func startOllamaControl(paths: AppPaths, env: [String: String], home: URL) {
        let control = OllamaControl(
            probe: HTTPOllamaProbe(),
            launcher: ProcessOllamaLauncher(log: paths.ollamaLogFile, env: env),
            plan: {
                let files = FileManager.default
                return ollamaLaunchPlan(
                    env: env, home: home, exists: { files.fileExists(atPath: $0) },
                    isExecutable: { files.isExecutableFile(atPath: $0) })
            })
        control.onChange = { [weak self] _ in self?.render() }
        ollama = control
        control.startPolling()
    }

    /// Показывает текущее состояние в меню и окне. Во время выхода меню держит
    /// «Останавливаю ядро…» до самого конца.
    private func render() {
        guard !quitting else { return }
        let current = state
        let ollamaState = ollama?.state ?? .unknown
        // Без надзора (нет пути к репозиторию) пульт ядра бесполезен
        let controls = supervisor == nil ? [] : controlActions(state: current, ollama: ollamaState)
        let ollamaText = ollamaStatusText(ollamaState)
        statusMenu?.show(
            menuModel(state: current), controls: controls, ollama: ollamaText,
            canRestart: supervisor != nil, login: loginItem.menuState)
        window?.show(windowContent(state: current, token: supervisor?.token), controls: controls, ollama: ollamaText)
    }

    private func showAlert(_ title: String, _ text: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        NSApp.activate()
        alert.runModal()
    }
}
