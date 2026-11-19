import AppKit
import SmartEspKit

/// Действия пунктов меню; их выполняет `AppDelegate`.
@MainActor protocol StatusMenuActions: AnyObject {
    func openWindow()
    func restartCore()
    func openLog()
}

/// Значок SmartESP в строке меню и его меню.
@MainActor final class StatusMenu: NSObject {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private let statusLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let hintLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let openItem = NSMenuItem(title: "Открыть SmartESP", action: nil, keyEquivalent: "o")
    private let restartItem = NSMenuItem(title: "Перезапустить ядро", action: nil, keyEquivalent: "")
    private let logItem = NSMenuItem(title: "Журнал", action: nil, keyEquivalent: "")
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
    ///   - canRestart: можно ли вообще перезапускать (нет надзора — нет и перезапуска).
    ///   - hasLog: известен ли путь к журналу.
    func show(_ model: MenuModel, canRestart: Bool, hasLog: Bool) {
        statusLine.title = model.statusText
        hintLine.title = model.hint ?? ""
        hintLine.isHidden = model.hint == nil
        openItem.isEnabled = model.canOpen
        restartItem.isEnabled = model.canRestart && canRestart
        logItem.isEnabled = hasLog
        let image = NSImage(systemSymbolName: model.symbolName, accessibilityDescription: "SmartESP")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.toolTip = model.statusText
    }

    /// Строка состояния при выходе, пока ядро останавливается.
    func showQuitting() {
        statusLine.title = "Останавливаю ядро…"
        item.button?.toolTip = statusLine.title
        restartItem.isEnabled = false
    }

    private func buildMenu() {
        menu.autoenablesItems = false
        statusLine.isEnabled = false
        hintLine.isEnabled = false
        hintLine.isHidden = true
        for entry in [openItem, restartItem, logItem] { entry.target = self }
        openItem.action = #selector(open)
        restartItem.action = #selector(restart)
        logItem.action = #selector(log)
        let quitItem = NSMenuItem(title: "Выйти", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        quitItem.target = NSApp
        // «Запускать при входе» с галочкой — в задаче 4, отдельной секцией перед «Выйти»
        let items = [statusLine, hintLine, .separator(), openItem, restartItem, logItem, .separator(), quitItem]
        items.forEach(menu.addItem)
        item.menu = menu
    }

    @objc private func open() { actions?.openWindow() }
    @objc private func restart() { actions?.restartCore() }
    @objc private func log() { actions?.openLog() }
}
