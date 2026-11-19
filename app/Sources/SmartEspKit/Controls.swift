import Foundation

/// Кнопки пульта: в меню и в окне-заглушке.
public enum ControlAction: Equatable, Sendable, CaseIterable {
    /// Запустить своё ядро (из остановки или ошибки).
    case startCore
    /// Остановить своё ядро; само оно после этого не запустится.
    case stopCore
    /// Остановить чужое ядро и запустить своё.
    case takeOver
    /// Запустить Ollama.
    case startOllama

    /// Надпись на пункте меню и кнопке.
    public var title: String {
        switch self {
        case .startCore: "Запустить ядро"
        case .stopCore: "Остановить ядро"
        case .takeOver: "Взять управление"
        case .startOllama: "Запустить Ollama"
        }
    }
}

/// Какие кнопки пульта доступны.
/// - Parameters:
///   - state: состояние ядра.
///   - ollama: состояние Ollama.
/// - Returns: кнопки по порядку: сначала ядро, затем Ollama (если она не отвечает).
public func controlActions(state: CoreState, ollama: OllamaState) -> [ControlAction] {
    var actions: [ControlAction]
    switch state {
    case .stopped, .failed, .accessDenied:
        actions = [.startCore]
    case .starting, .running, .silentStart, .waitingForAccess:
        actions = [.stopCore]
    case .external:
        actions = [.takeOver]
    case .stopping:
        actions = []
    }
    switch ollama {
    case .down, .failed: actions.append(.startOllama)
    case .unknown, .up, .launching: break
    }
    return actions
}

/// Строка состояния Ollama для меню и окна.
/// - Parameter state: состояние Ollama.
/// - Returns: например «Ollama: работает».
public func ollamaStatusText(_ state: OllamaState) -> String {
    switch state {
    case .unknown: "Ollama: проверяю…"
    case .up: "Ollama: работает"
    case .down: "Ollama: не отвечает"
    case .launching: "Ollama: запускаю…"
    case let .failed(message): "Ollama: \(message)"
    }
}
