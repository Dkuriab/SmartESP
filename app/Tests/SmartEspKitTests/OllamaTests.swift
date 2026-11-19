import Foundation
import Testing
@testable import SmartEspKit

/// Поддельная проверка Ollama.
@MainActor final class FakeOllamaProbe: OllamaProbing {
    var up = false
    var calls = 0
    /// Когда (по поддельным часам) Ollama начинает отвечать; `nil` — смотреть на `up`.
    var upAt: TimeInterval?
    let clock: FakeClock
    init(clock: FakeClock) { self.clock = clock }
    func isUp() async -> Bool {
        calls += 1
        if let upAt { return clock.now >= upAt }
        return up
    }
}

/// Поддельный запуск Ollama.
@MainActor final class FakeOllamaLauncher: OllamaLaunching {
    var opened: [URL] = []
    var served: [URL] = []
    var error: Error?
    func openApp(_ app: URL) throws {
        if let error { throw error }
        opened.append(app)
    }
    func serve(_ binary: URL) throws {
        if let error { throw error }
        served.append(binary)
    }
}

@MainActor private func makeControl(
    plan: OllamaLaunchPlan = .openApp(URL(fileURLWithPath: "/Applications/Ollama.app"))
) -> (OllamaControl, FakeOllamaProbe, FakeOllamaLauncher, FakeClock) {
    let clock = FakeClock()
    let probe = FakeOllamaProbe(clock: clock)
    let launcher = FakeOllamaLauncher()
    let control = OllamaControl(
        probe: probe, launcher: launcher, plan: { plan },
        clock: { clock.now }, sleep: { await clock.sleep($0) }, autoPoll: false)
    return (control, probe, launcher, clock)
}

@MainActor @Suite struct OllamaControlTests {
    @Test func refreshReflectsProbe() async {
        let (control, probe, _, _) = makeControl()
        #expect(control.state == .unknown)
        await control.refresh()
        #expect(control.state == .down)
        probe.up = true
        await control.refresh()
        #expect(control.state == .up)
    }

    @Test func launchOpensAppAndWaitsUntilUp() async {
        let (control, probe, launcher, clock) = makeControl()
        probe.upAt = clock.now + 4
        var seen: [OllamaState] = []
        control.onChange = { seen.append($0) }
        await control.launch()
        #expect(launcher.opened == [URL(fileURLWithPath: "/Applications/Ollama.app")])
        #expect(launcher.served.isEmpty)
        #expect(control.state == .up)
        #expect(seen.contains(.launching))
    }

    @Test func launchServesBinaryWithoutApp() async {
        let (control, probe, launcher, clock) = makeControl(plan: .serve(URL(fileURLWithPath: "/opt/homebrew/bin/ollama")))
        probe.upAt = clock.now + 1
        await control.launch()
        #expect(launcher.served == [URL(fileURLWithPath: "/opt/homebrew/bin/ollama")])
        #expect(control.state == .up)
    }

    @Test func launchWhenAlreadyUpDoesNothing() async {
        let (control, probe, launcher, _) = makeControl()
        probe.up = true
        await control.launch()
        #expect(launcher.opened.isEmpty)
        #expect(control.state == .up)
    }

    @Test func notInstalledIsError() async {
        let (control, _, launcher, _) = makeControl(plan: .notFound)
        await control.launch()
        #expect(launcher.opened.isEmpty && launcher.served.isEmpty)
        #expect(control.state == .failed(OllamaControl.notFoundText))
        // Ошибка держится, пока Ollama не ответит
        await control.refresh()
        #expect(control.state == .failed(OllamaControl.notFoundText))
    }

    @Test func noAnswerAfterLaunchIsError() async {
        let (control, _, _, clock) = makeControl()
        let started = clock.now
        await control.launch()
        #expect(clock.now - started >= OllamaControl.launchTimeout)
        guard case .failed = control.state else {
            Issue.record("ожидали ошибку, а состояние \(control.state)")
            return
        }
    }

    @Test func launcherErrorIsShown() async {
        let (control, _, launcher, _) = makeControl()
        launcher.error = NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "нет"])
        await control.launch()
        #expect(control.state == .failed("Не удалось запустить Ollama: нет"))
    }
}

@Suite struct OllamaPlanTests {
    private let home = URL(fileURLWithPath: "/Users/u")

    @Test func prefersApp() {
        let plan = ollamaLaunchPlan(
            env: ["PATH": "/usr/bin"], home: home,
            exists: { $0 == "/Applications/Ollama.app" }, isExecutable: { _ in true })
        #expect(plan == .openApp(URL(fileURLWithPath: "/Applications/Ollama.app")))
    }

    @Test func appInHomeApplications() {
        let plan = ollamaLaunchPlan(
            env: [:], home: home, exists: { $0 == "/Users/u/Applications/Ollama.app" }, isExecutable: { _ in false })
        #expect(plan == .openApp(URL(fileURLWithPath: "/Users/u/Applications/Ollama.app")))
    }

    @Test func binaryWhenNoApp() {
        let plan = ollamaLaunchPlan(
            env: ["PATH": "/custom/bin"], home: home, exists: { _ in false },
            isExecutable: { $0 == "/custom/bin/ollama" })
        #expect(plan == .serve(URL(fileURLWithPath: "/custom/bin/ollama")))
        let brew = ollamaLaunchPlan(
            env: [:], home: home, exists: { _ in false }, isExecutable: { $0 == "/opt/homebrew/bin/ollama" })
        #expect(brew == .serve(URL(fileURLWithPath: "/opt/homebrew/bin/ollama")))
    }

    @Test func nothingFound() {
        let plan = ollamaLaunchPlan(env: ["PATH": "/bin"], home: home, exists: { _ in false }, isExecutable: { _ in false })
        #expect(plan == .notFound)
    }
}

@MainActor @Suite struct ProcessOllamaLauncherTests {
    @Test func serveRunsDetachedAndAppendsToLog() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("smartesp-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let binary = dir.appendingPathComponent("fake-ollama")
        try "#!/bin/sh\necho \"$1 $MARK\"\necho stderr-too >&2\n".write(to: binary, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)
        let log = dir.appendingPathComponent("logs/ollama.log")
        try ProcessOllamaLauncher(log: log, env: ["MARK": "ok", "PATH": "/bin:/usr/bin"]).serve(binary)
        var text = ""
        for _ in 0..<100 {
            text = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
            if text.contains("stderr-too") { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(text.contains("serve ok"))
        #expect(text.contains("stderr-too"))
    }
}
