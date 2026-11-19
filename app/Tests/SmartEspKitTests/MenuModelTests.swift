import Foundation
import Testing
@testable import SmartEspKit

@Suite struct MenuModelTests {
    @Test func runningReady() {
        let model = menuModel(
            state: .running(port: 8765, phase: "ready", devices: (1, 2), ollama: true), loginEnabled: false)
        #expect(model.statusText == "Ядро работает · колонок 1 из 2 · Ollama ✓")
        #expect(model.symbolName == "waveform.circle.fill")
        #expect(model.canOpen && model.canRestart)
        #expect(model.hint == nil)
    }

    @Test func runningWarmingWithoutOllama() {
        let model = menuModel(
            state: .running(port: 8765, phase: "warming", devices: (0, 3), ollama: false), loginEnabled: false)
        #expect(model.statusText == "Ядро прогревается · колонок 0 из 3 · Ollama ✗")
        #expect(model.symbolName == "waveform.circle")
        #expect(model.canOpen && model.canRestart)
    }

    @Test func runningStoppingPhase() {
        let model = menuModel(
            state: .running(port: 8765, phase: "stopping", devices: (0, 0), ollama: true), loginEnabled: false)
        #expect(model.statusText == "Ядро останавливается…")
        #expect(model.symbolName == "waveform.circle")
    }

    @Test func starting() {
        let model = menuModel(state: .starting, loginEnabled: false)
        #expect(model.statusText == "Ядро запускается…")
        #expect(model.symbolName == "waveform.circle")
        #expect(model.canOpen && model.canRestart)
    }

    @Test func external() {
        let ready = menuModel(
            state: .external(port: 9000, phase: "ready", devices: (2, 2), ollama: true), loginEnabled: false)
        #expect(ready.statusText == "Ядро запущено не из приложения")
        #expect(ready.symbolName == "waveform.circle.fill")
        #expect(ready.canOpen && ready.canRestart)
        let warming = menuModel(
            state: .external(port: 9000, phase: "warming", devices: (0, 2), ollama: true), loginEnabled: false)
        #expect(warming.symbolName == "waveform.circle")
    }

    @Test func stoppingDisablesRestart() {
        let model = menuModel(state: .stopping, loginEnabled: false)
        #expect(model.statusText == "Останавливаю ядро…")
        #expect(model.symbolName == "waveform.circle")
        #expect(model.canOpen)
        #expect(!model.canRestart)
    }

    @Test func stopped() {
        let model = menuModel(state: .stopped, loginEnabled: false)
        #expect(model.statusText == "Ядро остановлено")
        #expect(model.symbolName == "exclamationmark.triangle.fill")
        #expect(model.canOpen && model.canRestart)
    }

    @Test func failed() {
        let model = menuModel(state: .failed("Порт 8765 занят другой программой"), loginEnabled: false)
        #expect(model.statusText == "Ошибка: Порт 8765 занят другой программой")
        #expect(model.symbolName == "exclamationmark.triangle.fill")
        #expect(model.canOpen && model.canRestart)
        #expect(model.hint == nil)
    }

    @Test func missingUvGivesHint() {
        let model = menuModel(state: .failed(CoreErrors.uvNotFound), loginEnabled: false)
        #expect(model.statusText == "Ошибка: Не найден uv")
        #expect(model.hint?.contains("astral.sh/uv") == true)
    }

    @Test func loginFlagPassesThrough() {
        #expect(menuModel(state: .starting, loginEnabled: true).loginChecked)
        #expect(!menuModel(state: .starting, loginEnabled: false).loginChecked)
    }
}

@Suite struct WindowContentTests {
    @Test func runningWithTokenLoadsPage() {
        let content = windowContent(
            state: .running(port: 8765, phase: "warming", devices: (0, 0), ollama: true), token: "abc")
        #expect(content == .page(URL(string: "http://127.0.0.1:8765/?token=abc")!))
    }

    @Test func externalLoadsPageOnItsPort() {
        let content = windowContent(
            state: .external(port: 9001, phase: "ready", devices: (0, 0), ollama: true), token: "t")
        #expect(content == .page(URL(string: "http://127.0.0.1:9001/?token=t")!))
    }

    @Test func tokenIsPercentEncoded() {
        let content = windowContent(
            state: .running(port: 1, phase: "ready", devices: (0, 0), ollama: true), token: "a+b&c")
        #expect(content == .page(URL(string: "http://127.0.0.1:1/?token=a%2Bb%26c")!))
    }

    @Test func runningWithoutTokenShowsPlaceholder() {
        let content = windowContent(
            state: .running(port: 8765, phase: "ready", devices: (0, 0), ollama: true), token: nil)
        #expect(content == .placeholder("Ядро запускается…"))
    }

    @Test func otherStatesShowPlaceholder() {
        #expect(windowContent(state: .starting, token: "t") == .placeholder("Ядро запускается…"))
        #expect(windowContent(state: .stopped, token: nil) == .placeholder("Ядро остановлено"))
        #expect(windowContent(state: .stopping, token: "t") == .placeholder("Останавливаю ядро…"))
        #expect(windowContent(state: .failed("Порт занят"), token: nil) == .placeholder("Ошибка: Порт занят"))
        #expect(windowContent(state: .failed(CoreErrors.uvNotFound), token: nil)
            == .placeholder("Ошибка: Не найден uv\n\nУстановите uv: https://docs.astral.sh/uv/"))
    }

    @Test func loadOnlyWhenPageChanges() {
        let a = WindowContent.page(URL(string: "http://127.0.0.1:8765/?token=t")!)
        let b = WindowContent.page(URL(string: "http://127.0.0.1:8766/?token=t")!)
        let wait = WindowContent.placeholder("Ядро запускается…")
        #expect(a.needsLoad(after: nil))
        #expect(a.needsLoad(after: wait))
        #expect(b.needsLoad(after: a))
        #expect(!a.needsLoad(after: a))
        #expect(!wait.needsLoad(after: a))
    }
}
