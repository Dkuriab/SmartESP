import Foundation
import Testing
@testable import SmartEspKit

@Suite struct ControlActionsTests {
    private let running = CoreState.running(port: 8765, phase: "ready", devices: (0, 0), ollama: true)
    private let external = CoreState.external(port: 8765, phase: "ready", devices: (0, 0), ollama: true)

    @Test func onlyStartCoreIsTheReturnKeyDefault() {
        // в .starting первой кнопкой стоит «Остановить ядро»: Return не должен её нажимать
        #expect(ControlAction.allCases.filter(\.isDefaultButton) == [.startCore])
    }

    @Test func stoppedOffersStart() {
        #expect(controlActions(state: .stopped, ollama: .up) == [.startCore])
        #expect(controlActions(state: .failed("x"), ollama: .up) == [.startCore])
        #expect(controlActions(state: .accessDenied(folder: "Документы"), ollama: .up) == [.startCore])
    }

    @Test func ownCoreOffersStop() {
        #expect(controlActions(state: running, ollama: .up) == [.stopCore])
        #expect(controlActions(state: .starting, ollama: .up) == [.stopCore])
        #expect(controlActions(state: .silentStart(folder: "Документы"), ollama: .up) == [.stopCore])
        #expect(controlActions(state: .waitingForAccess(folder: "Документы"), ollama: .up) == [.stopCore])
    }

    @Test func externalCoreOffersTakeOver() {
        #expect(controlActions(state: external, ollama: .up) == [.takeOver])
    }

    @Test func stoppingOffersNothing() {
        #expect(controlActions(state: .stopping, ollama: .up).isEmpty)
    }

    @Test func ollamaDownOffersLaunch() {
        #expect(controlActions(state: running, ollama: .down) == [.stopCore, .startOllama])
        #expect(controlActions(state: .stopped, ollama: .failed("x")) == [.startCore, .startOllama])
        #expect(controlActions(state: running, ollama: .launching) == [.stopCore])
        #expect(controlActions(state: running, ollama: .unknown) == [.stopCore])
    }

    @Test func titles() {
        #expect(ControlAction.startCore.title == "Запустить ядро")
        #expect(ControlAction.stopCore.title == "Остановить ядро")
        #expect(ControlAction.takeOver.title == "Взять управление")
        #expect(ControlAction.startOllama.title == "Запустить Ollama")
    }

    @Test func ollamaText() {
        #expect(ollamaStatusText(.unknown) == "Ollama: проверяю…")
        #expect(ollamaStatusText(.up) == "Ollama: работает")
        #expect(ollamaStatusText(.down) == "Ollama: не отвечает")
        #expect(ollamaStatusText(.launching) == "Ollama: запускаю…")
        #expect(ollamaStatusText(.failed("не найдена")) == "Ollama: не найдена")
    }

    @Test func stoppedDisablesRestart() {
        #expect(!menuModel(state: .stopped).canRestart)
        #expect(menuModel(state: .failed("x")).canRestart)
    }
}

@Suite struct BridgeTests {
    private let paths = AppPaths(repo: URL(fileURLWithPath: "/repo"), dataDir: URL(fileURLWithPath: "/data"))

    @Test func parsesKnownActions() {
        #expect(BridgeAction.parse(["action": "openDataFolder"]) == .openDataFolder)
        #expect(BridgeAction.parse(["action": "openConfig"]) == .openConfig)
        #expect(BridgeAction.parse(["action": "revealLog"]) == .revealLog)
    }

    @Test func rejectsEverythingElse() {
        #expect(BridgeAction.parse(["action": "rm"]) == nil)
        #expect(BridgeAction.parse(["action": 1]) == nil)
        #expect(BridgeAction.parse(["action": "openConfig", "path": "/etc/passwd"]) == nil)
        #expect(BridgeAction.parse("openConfig") == nil)
        #expect(BridgeAction.parse([String: Any]()) == nil)
        #expect(BridgeAction.parse(["openConfig"]) == nil)
    }

    @Test func targetsExistingFiles() {
        let all: (String) -> Bool = { _ in true }
        #expect(bridgeTarget(.openDataFolder, paths: paths, exists: all) == .open(URL(fileURLWithPath: "/data")))
        #expect(bridgeTarget(.openConfig, paths: paths, exists: all) == .openText(URL(fileURLWithPath: "/data/config.yaml")))
        #expect(bridgeTarget(.revealLog, paths: paths, exists: all) == .reveal(URL(fileURLWithPath: "/data/logs/core.log")))
    }

    @Test func fallsBackToFolders() {
        let onlyDirs: (String) -> Bool = { ["/data", "/data/logs"].contains($0) }
        #expect(bridgeTarget(.openConfig, paths: paths, exists: onlyDirs) == .open(URL(fileURLWithPath: "/data")))
        #expect(bridgeTarget(.revealLog, paths: paths, exists: onlyDirs) == .open(URL(fileURLWithPath: "/data/logs")))
        let nothing: (String) -> Bool = { _ in false }
        #expect(bridgeTarget(.openDataFolder, paths: paths, exists: nothing) == nil)
        #expect(bridgeTarget(.openConfig, paths: paths, exists: nothing) == nil)
        #expect(bridgeTarget(.revealLog, paths: paths, exists: nothing) == nil)
    }

    @Test func trustsOnlyLocalCorePages() {
        #expect(isTrustedBridgeOrigin(scheme: "http", host: "127.0.0.1"))
        #expect(isTrustedBridgeOrigin(scheme: "http", host: "localhost"))
        #expect(!isTrustedBridgeOrigin(scheme: "https", host: "example.com"))
        #expect(!isTrustedBridgeOrigin(scheme: "http", host: "192.168.1.5"))
        #expect(!isTrustedBridgeOrigin(scheme: "file", host: ""))
    }

    @Test func userScriptMarksBridge() {
        #expect(bridgeMessageName == "smartesp")
        #expect(bridgeUserScript.contains("window.smartespBridge = true"))
    }
}
