import AppKit

/// Главное меню, пока окно открыто и приложение в Dock: без меню «Правка»
/// в WKWebView не работают ⌘C/⌘V, без меню приложения — ⌘Q.
@MainActor enum MainMenu {
    /// Собирает меню «SmartESP», «Правка», «Окно».
    /// - Returns: меню для `NSApp.mainMenu`.
    static func make() -> NSMenu {
        let main = NSMenu()
        main.addItem(submenu("SmartESP", [
            item("Скрыть SmartESP", #selector(NSApplication.hide(_:)), "h"),
            .separator(),
            item("Выйти из SmartESP", #selector(NSApplication.terminate(_:)), "q"),
        ]))
        main.addItem(submenu("Правка", [
            item("Отменить", Selector(("undo:")), "z"),
            item("Повторить", Selector(("redo:")), "Z"),
            .separator(),
            item("Вырезать", #selector(NSText.cut(_:)), "x"),
            item("Копировать", #selector(NSText.copy(_:)), "c"),
            item("Вставить", #selector(NSText.paste(_:)), "v"),
            item("Выбрать всё", #selector(NSText.selectAll(_:)), "a"),
        ]))
        let window = submenu("Окно", [
            item("Свернуть", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Закрыть", #selector(NSWindow.performClose(_:)), "w"),
        ])
        main.addItem(window)
        NSApp.windowsMenu = window.submenu
        return main
    }

    private static func item(_ title: String, _ action: Selector, _ key: String) -> NSMenuItem {
        NSMenuItem(title: title, action: action, keyEquivalent: key)
    }

    private static func submenu(_ title: String, _ items: [NSMenuItem]) -> NSMenuItem {
        let holder = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let menu = NSMenu(title: title)
        items.forEach(menu.addItem)
        holder.submenu = menu
        return holder
    }
}
