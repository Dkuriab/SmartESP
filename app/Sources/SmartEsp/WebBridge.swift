import AppKit
import SmartEspKit
import WebKit

/// Мост WKWebView → приложение: `webkit.messageHandlers.smartesp.postMessage({action})`.
/// `WKUserContentController` держит обработчик сильно — замыкание должно ссылаться на окно слабо.
@MainActor final class WebBridge: NSObject, WKScriptMessageHandler {
    private let onAction: (BridgeAction) -> Void

    /// - Parameter onAction: проверенное действие от страницы ядра.
    init(onAction: @escaping (BridgeAction) -> Void) {
        self.onAction = onAction
    }

    /// Подключает мост: скрипт `window.smartespBridge = true` и обработчик `smartesp`.
    /// - Parameter controller: контроллер содержимого WKWebView.
    func install(in controller: WKUserContentController) {
        let script = WKUserScript(source: bridgeUserScript, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        controller.addUserScript(script)
        controller.add(self, name: bridgeMessageName)
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        // Только главная страница интерфейса ядра (127.0.0.1) и только известные действия
        let origin = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame,
              isTrustedBridgeOrigin(scheme: origin.protocol, host: origin.host),
              let action = BridgeAction.parse(message.body) else { return }
        onAction(action)
    }

    /// Выполняет действие моста через NSWorkspace.
    /// - Parameters:
    ///   - action: действие.
    ///   - paths: пути папки данных; `nil` — ничего не делать.
    static func perform(_ action: BridgeAction, paths: AppPaths?) {
        guard let paths,
              let target = bridgeTarget(action, paths: paths, exists: { FileManager.default.fileExists(atPath: $0) })
        else { return NSSound.beep() }
        let workspace = NSWorkspace.shared
        switch target {
        case let .open(url):
            workspace.open(url)
        case let .reveal(url):
            workspace.activateFileViewerSelecting([url])
        case let .openText(url):
            // Для .yaml может не быть программы по умолчанию — тогда TextEdit
            if workspace.urlForApplication(toOpen: url) != nil {
                workspace.open(url)
            } else {
                let textEdit = URL(fileURLWithPath: "/System/Applications/TextEdit.app")
                workspace.open([url], withApplicationAt: textEdit, configuration: NSWorkspace.OpenConfiguration())
            }
        }
    }
}
