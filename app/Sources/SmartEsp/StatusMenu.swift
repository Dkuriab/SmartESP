import AppKit
import SmartEspKit

/// Действия пунктов меню; их выполняет `AppDelegate`.
@MainActor protocol StatusMenuActions: AnyObject {
    func openWindow()
    func restartCore()
    func openLog()
    func openAccessSettings()
    func toggleLoginItem()
    /// Кнопка пульта: запустить, остановить ядро, взять управление, запустить Ollama.
    func perform(_ action: ControlAction)
    /// Меню открывается — пора проверить Ollama.
    func menuWillOpen()
    /// Состояние автозапуска прямо сейчас; `nil` — не трогать пункт (идёт выход).
    func liveLoginState() -> LoginMenuState?
}

/// Значок SmartESP в строке меню и его меню.
@MainActor final class StatusMenu: NSObject, NSMenuDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private let statusLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    /// Строки подсказки (по одной на пункт: меню не переносит длинные строки).
    private var hintLines: [NSMenuItem] = []
    private let settingsItem = NSMenuItem(title: "Открыть настройки доступа", action: nil, keyEquivalent: "")
    private let openItem = NSMenuItem(title: "Открыть SmartESP", action: nil, keyEquivalent: "o")
    private let restartItem = NSMenuItem(title: "Перезапустить ядро", action: nil, keyEquivalent: "")
    /// Пункты пульта; видны только доступные.
    private let controlItems: [ControlAction: NSMenuItem] = Dictionary(
        uniqueKeysWithValues: ControlAction.allCases.map { ($0, NSMenuItem(title: $0.title, action: nil, keyEquivalent: "")) })
    private let ollamaLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let loginItem = NSMenuItem(title: "Запускать при входе", action: nil, keyEquivalent: "")
    private let logItem = NSMenuItem(title: "Журнал", action: nil, keyEquivalent: "")
    private let quitItem = NSMenuItem(title: "Выйти", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    private weak var actions: StatusMenuActions?

    /// - Parameter actions: кто выполняет пункты меню.
    init(actions: StatusMenuActions) {
        self.actions = actions
        super.init()
        buildMenu()
    }

    /// Показывает модель: строка состояния, подсказка, значок, доступность пунктов.
    /// - Parameters:
    ///   - model: модель меню из `menuModel`.
    ///   - controls: доступные кнопки пульта (из `controlActions`).
    ///   - ollama: строка состояния Ollama.
    ///   - canRestart: можно ли вообще перезапускать (нет надзора — нет и перезапуска).
    func show(_ model: MenuModel, controls: [ControlAction], ollama: String, canRestart: Bool, login: LoginMenuState) {
        statusLine.title = model.statusText
        showHint(model.hint)
        settingsItem.isHidden = !model.showsAccessSettings
        openItem.isEnabled = model.canOpen
        restartItem.isEnabled = model.canRestart && canRestart
        for (action, entry) in controlItems { entry.isHidden = !(canRestart && controls.contains(action)) }
        ollamaLine.title = ollama
        showLogin(login)
        let image = NSImage(systemSymbolName: model.symbolName, accessibilityDescription: "SmartESP")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.toolTip = model.statusText
    }

    /// Выход идёт: «Останавливаю ядро…», перезапуск и повторный выход недоступны.
    func showQuitting() {
        statusLine.title = "Останавливаю ядро…"
        item.button?.toolTip = statusLine.title
        restartItem.isEnabled = false
        controlItems.values.forEach { $0.isHidden = true }
        loginItem.isEnabled = false
        quitItem.isEnabled = false
    }

    /// Автозапуск могли поменять в Системных настройках — перед открытием меню берём живое состояние.
    func menuWillOpen(_ menu: NSMenu) {
        if let login = actions?.liveLoginState() { showLogin(login) }
        actions?.menuWillOpen()
    }

    /// Пункт «Запускать при входе»: заголовок, отметка, доступность.
    private func showLogin(_ login: LoginMenuState) {
        loginItem.title = login.title
        loginItem.isEnabled = login.click != .none
        switch login.mark {
        case .on: loginItem.state = .on
        case .off: loginItem.state = .off
        case .mixed: loginItem.state = .mixed
        }
    }

    /// Заменяет строки подсказки под строкой состояния.
    private func showHint(_ hint: String?) {
        hintLines.forEach(menu.removeItem)
        let lines = hint?.split(separator: "\n").map(String.init) ?? []
        hintLines = lines.map { line in
            let entry = NSMenuItem(title: line, action: nil, keyEquivalent: "")
            entry.isEnabled = false
            return entry
        }
        for (offset, entry) in hintLines.enumerated() {
            menu.insertItem(entry, at: menu.index(of: statusLine) + 1 + offset)
        }
    }

    private func buildMenu() {
        menu.autoenablesItems = false
        menu.delegate = self
        statusLine.isEnabled = false
        ollamaLine.isEnabled = false
        settingsItem.isHidden = true
        for entry in controlItems.values {
            entry.target = self
            entry.action = #selector(control(_:))
            entry.isHidden = true
        }
        for entry in [settingsItem, openItem, restartItem, logItem, loginItem] { entry.target = self }
        settingsItem.action = #selector(settings)
        openItem.action = #selector(open)
        restartItem.action = #selector(restart)
        logItem.action = #selector(log)
        loginItem.action = #selector(login)
        quitItem.target = NSApp
        let core = [ControlAction.startCore, .stopCore, .takeOver].compactMap { controlItems[$0] }
        let ollama = [ollamaLine] + [controlItems[.startOllama]].compactMap { $0 }
        let items = [statusLine, settingsItem, .separator(), openItem] + core + [restartItem, logItem, .separator()]
            + ollama + [.separator(), loginItem, .separator(), quitItem]
        items.forEach(menu.addItem)
        item.menu = menu
    }

    @objc private func settings() { actions?.openAccessSettings() }
    @objc private func open() { actions?.openWindow() }
    @objc private func restart() { actions?.restartCore() }
    @objc private func login() { actions?.toggleLoginItem() }
    @objc private func log() { actions?.openLog() }
    @objc private func control(_ sender: NSMenuItem) {
        guard let action = controlItems.first(where: { $0.value === sender })?.key else { return }
        actions?.perform(action)
    }
}
