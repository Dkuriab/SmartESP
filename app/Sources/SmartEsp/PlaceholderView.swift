import AppKit
import SmartEspKit

/// Заглушка окна без ядра: текст состояния, кнопки пульта и строка Ollama — родными элементами.
@MainActor final class PlaceholderView: NSView {
    private let text = NSTextField(labelWithString: "")
    private let buttons = NSStackView()
    private let ollama = NSTextField(labelWithString: "")
    private var shownActions: [ControlAction] = []
    /// Нажата кнопка пульта.
    var onAction: ((ControlAction) -> Void)?

    override init(frame: NSRect) {
        super.init(frame: frame)
        layout(text: text, buttons: buttons, ollama: ollama)
    }

    required init?(coder: NSCoder) { nil }

    /// Показывает состояние.
    /// - Parameters:
    ///   - message: текст заглушки (из `windowContent`).
    ///   - controls: доступные кнопки пульта.
    ///   - ollamaText: строка состояния Ollama.
    func show(_ message: String, controls: [ControlAction], ollamaText: String) {
        text.stringValue = message
        ollama.stringValue = ollamaText
        guard controls != shownActions else { return }
        shownActions = controls
        buttons.arrangedSubviews.forEach { $0.removeFromSuperview() }
        for (index, action) in controls.enumerated() {
            let button = NSButton(title: action.title, target: self, action: #selector(press(_:)))
            button.tag = index
            button.bezelStyle = .push
            if index == 0 { button.keyEquivalent = "\r" }
            buttons.addArrangedSubview(button)
        }
        buttons.isHidden = controls.isEmpty
    }

    @objc private func press(_ sender: NSButton) {
        guard shownActions.indices.contains(sender.tag) else { return }
        onAction?(shownActions[sender.tag])
    }

    private func layout(text: NSTextField, buttons: NSStackView, ollama: NSTextField) {
        text.font = .systemFont(ofSize: 17)
        text.textColor = .secondaryLabelColor
        text.alignment = .center
        text.maximumNumberOfLines = 0
        text.preferredMaxLayoutWidth = 600
        ollama.font = .systemFont(ofSize: 13)
        ollama.textColor = .tertiaryLabelColor
        buttons.orientation = .horizontal
        buttons.spacing = 12
        let stack = NSStackView(views: [text, buttons, ollama])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: widthAnchor, constant: -48),
        ])
    }
}
