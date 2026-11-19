import AppKit
import SmartEspKit
import WebKit

/// Главное окно: веб-интерфейс ядра в WKWebView или заглушка с текстом.
@MainActor final class MainWindow: NSObject, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    /// Сколько раз подряд повторять неудачную загрузку страницы (раз в секунду).
    private static let maxRetries = 30

    private let window: NSWindow
    private let webView: WKWebView
    private let placeholder = NSTextField(labelWithString: "")
    private var shown: WindowContent?
    private var retries = 0
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
        webView.navigationDelegate = self
        webView.uiDelegate = self
        layout()
        // Сначала по центру; сохранённая рамка (если есть) восстановится при задании имени
        window.center()
        window.setFrameAutosaveName("SmartEspMainWindow")
    }

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
            if reload {
                retries = 0
                webView.load(URLRequest(url: url))
            }
        case let .placeholder(text):
            placeholder.stringValue = text
            placeholder.isHidden = false
            webView.isHidden = true
        }
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }

    // MARK: - WebKit

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        retries = 0
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        retryLoad(after: error)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        retryLoad(after: error)
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction
    ) async -> WKNavigationActionPolicy {
        guard let url = navigationAction.request.url, opensExternally(url) else { return .allow }
        NSWorkspace.shared.open(url)
        return .cancel
    }

    /// `target=_blank` и `window.open`: внешние адреса — в браузере, свои — в этом же окне.
    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url {
            if opensExternally(url) { NSWorkspace.shared.open(url) } else { webView.load(navigationAction.request) }
        }
        return nil
    }

    /// Ядро отвечает на `status`, а страница не загрузилась — пробуем ещё раз через 1 с.
    private func retryLoad(after error: Error) {
        let nsError = error as NSError
        guard shouldRetryLoad(domain: nsError.domain, code: nsError.code), case let .page(url) = shown, retries < Self.maxRetries else { return }
        retries += 1
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(1))
            guard let self, self.shown == .page(url) else { return }
            self.webView.load(URLRequest(url: url))
        }
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
