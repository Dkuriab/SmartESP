import AppKit
import SmartEspKit
import WebKit

/// Главное окно: веб-интерфейс ядра в WKWebView или заглушка с текстом.
@MainActor final class MainWindow: NSObject, NSWindowDelegate {
    private let window: NSWindow
    private let webView: WKWebView
    private let placeholder = NSTextField(labelWithString: "")
    private var shown: WindowContent?
    /// Вызывается, когда пользователь закрыл окно.
    var onClose: (() -> Void)?

    override init() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        let config = WKWebViewConfiguration()
        // Постоянное хранилище: настройки интерфейса переживают перезапуск приложения
        config.websiteDataStore = .default()
        // Прослушивание голоса играет после асинхронного синтеза, без жеста пользователя
        config.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()
        window.title = "SmartESP"
        window.minSize = NSSize(width: 900, height: 600)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.setFrameAutosaveName("SmartEspMainWindow")
        layout()
        if !window.setFrameUsingName("SmartEspMainWindow") { window.center() }
    }

    /// Окно сейчас на экране.
    var isVisible: Bool { window.isVisible }

    /// Показывает окно и делает его главным.
    func present() {
        window.makeKeyAndOrderFront(nil)
    }

    /// Показывает страницу или заглушку. Страница грузится заново, только если
    /// сменился адрес или до неё была заглушка.
    /// - Parameter content: что показать (из `windowContent`).
    func show(_ content: WindowContent) {
        let reload = content.needsLoad(after: shown)
        shown = content
        switch content {
        case let .page(url):
            placeholder.isHidden = true
            webView.isHidden = false
            if reload { webView.load(URLRequest(url: url)) }
        case let .placeholder(text):
            placeholder.stringValue = text
            placeholder.isHidden = false
            webView.isHidden = true
        }
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }

    private func layout() {
        let root = NSView()
        for view in [webView, placeholder] as [NSView] {
            view.translatesAutoresizingMaskIntoConstraints = false
            root.addSubview(view)
        }
        placeholder.font = .systemFont(ofSize: 17)
        placeholder.textColor = .secondaryLabelColor
        placeholder.alignment = .center
        placeholder.maximumNumberOfLines = 0
        placeholder.preferredMaxLayoutWidth = 600
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            webView.topAnchor.constraint(equalTo: root.topAnchor),
            webView.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            placeholder.centerXAnchor.constraint(equalTo: root.centerXAnchor),
            placeholder.centerYAnchor.constraint(equalTo: root.centerYAnchor),
            placeholder.widthAnchor.constraint(lessThanOrEqualTo: root.widthAnchor, constant: -48),
        ])
        window.contentView = root
    }
}
