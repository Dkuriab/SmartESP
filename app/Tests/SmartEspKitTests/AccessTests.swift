import Foundation
import Testing
@testable import SmartEspKit

private let documentsRepo = "Documents/SmartEsp"

@MainActor @Suite struct SupervisorAccessTests {
    @Test func fastGrantLaunchesWithoutAccessState() async {
        let rig = Rig(repo: documentsRepo)
        await rig.supervisor.performStart()
        #expect(rig.access.checks == 1)
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .starting)
        #expect(!rig.changes.contains(.waitingForAccess(folder: "Документы")))
    }

    @Test func pendingPromptShowsWaitingThenLaunches() async {
        let rig = Rig(repo: documentsRepo)
        rig.access.answerAt = rig.clock.now + 5
        await rig.supervisor.performStart()
        #expect(rig.changes == [.starting, .waitingForAccess(folder: "Документы"), .starting])
        #expect(rig.launcher.handles.count == 1)
    }

    @Test func shortProbeDoesNotFlashWaitingState() async {
        let rig = Rig(repo: documentsRepo)
        rig.access.answerAt = rig.clock.now + 0.5
        await rig.supervisor.performStart()
        #expect(!rig.changes.contains(.waitingForAccess(folder: "Документы")))
        #expect(rig.launcher.handles.count == 1)
    }

    @Test func deniedShowsErrorAndRestartProbesAgain() async {
        let rig = Rig(repo: documentsRepo)
        rig.access.answer = .denied
        await rig.supervisor.performStart()
        #expect(rig.supervisor.state == .accessDenied(folder: "Документы"))
        #expect(rig.launcher.handles.isEmpty)

        rig.access.answer = .granted
        await rig.supervisor.restart()
        #expect(rig.access.checks == 2)
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .starting)
    }

    @Test func otherProbeErrorFails() async {
        let rig = Rig()
        rig.access.answer = .failed("Нет папки ядра: /x/core")
        await rig.supervisor.performStart()
        #expect(rig.supervisor.state == .failed("Нет папки ядра: /x/core"))
        #expect(rig.launcher.handles.isEmpty)
    }

    @Test func repoOutsideProtectedFoldersNamesRepoFolder() async {
        let rig = Rig()
        rig.access.answerAt = .infinity
        rig.supervisor.start()
        while rig.supervisor.state != .waitingForAccess(folder: "repo") { await Task.yield() }
        await rig.supervisor.stop()
        #expect(rig.supervisor.state == .stopped)
    }

    @Test func quitWhilePromptPendingLaunchesNothing() async {
        let rig = Rig(repo: documentsRepo)
        rig.access.answerAt = .infinity
        rig.supervisor.start()
        while rig.supervisor.state != .waitingForAccess(folder: "Документы") { await Task.yield() }
        await rig.supervisor.stop()
        #expect(rig.supervisor.state == .stopped)
        #expect(rig.launcher.handles.isEmpty)
    }

    @Test func silentCoreInDocumentsShowsAccessHint() async {
        let rig = Rig(repo: documentsRepo)
        await rig.supervisor.performStart()
        rig.clock.now += 19
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .starting)
        rig.clock.now += 2
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .waitingForAccess(folder: "Документы"))

        // Разрешили — ядро пишет файл запуска и отвечает
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "warming", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .running(port: 8765, phase: "warming", devices: (0, 0), ollama: true))
    }

    @Test func silentStartHintNeedsSilenceAndProtectedFolder() async {
        let outside = Rig()
        await outside.supervisor.performStart()
        outside.clock.now += 30
        await outside.supervisor.tick()
        #expect(outside.supervisor.state == .starting)

        let talking = Rig(repo: documentsRepo)
        await talking.supervisor.performStart()
        talking.writeStderr("Installed 80 packages\n")
        talking.clock.now += 30
        await talking.supervisor.tick()
        #expect(talking.supervisor.state == .starting)

        let logging = Rig(repo: documentsRepo)
        await logging.supervisor.performStart()
        logging.appendLog(["2026-11-19 10:00:00,000 INFO smartesp: Настройки"])
        logging.clock.now += 30
        await logging.supervisor.tick()
        #expect(logging.supervisor.state == .starting)
    }

    @Test func restartDuringAccessPromptDoesNothing() async {
        let rig = Rig(repo: documentsRepo)
        rig.access.answerAt = .infinity
        rig.supervisor.start()
        while rig.supervisor.state != .waitingForAccess(folder: "Документы") { await Task.yield() }
        await rig.supervisor.restart()
        #expect(rig.launcher.handles.isEmpty)
        #expect(rig.supervisor.state == .waitingForAccess(folder: "Документы"))
        await rig.supervisor.stop()
    }

    @Test func quitDuringRestartDoesNotLaunchAgain() async {
        let rig = Rig()
        rig.launcher.exitsOnTerminate = false
        await rig.supervisor.performStart()
        let restart = Task { await rig.supervisor.restart() }
        while rig.launcher.handles.first?.terminateCount != 1 { await Task.yield() }
        await rig.supervisor.stop()
        await restart.value
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .stopped)
    }
}

@MainActor @Suite struct AccessModelTests {
    private let home = URL(fileURLWithPath: "/Users/tester")

    @Test func protectedFolders() {
        #expect(protectedFolderName(of: URL(fileURLWithPath: "/Users/tester/Documents/Danila/SmartEsp"), home: home)
            == "Документы")
        #expect(protectedFolderName(of: URL(fileURLWithPath: "/Users/tester/Desktop/x"), home: home) == "Рабочий стол")
        #expect(protectedFolderName(of: URL(fileURLWithPath: "/Users/tester/Downloads"), home: home) == "Загрузки")
        #expect(protectedFolderName(of: URL(fileURLWithPath: "/Users/tester/DocumentsOld/x"), home: home) == nil)
        #expect(protectedFolderName(of: URL(fileURLWithPath: "/Users/tester/dev/SmartEsp"), home: home) == nil)
    }

    @Test func waitingForAccessMenu() {
        let model = menuModel(state: .waitingForAccess(folder: "Документы"), loginEnabled: false)
        #expect(model.statusText == "Нужно разрешение на папку «Документы»")
        #expect(model.symbolName == "exclamationmark.triangle.fill")
        #expect(model.hint == accessHint(folder: "Документы"))
        #expect(model.hint?.contains("нажмите «Разрешить»") == true)
        #expect(model.hint?.contains("Файлы и папки → SmartEsp → «Папка „Документы“»") == true)
        #expect(model.showsAccessSettings && model.canRestart && model.canOpen)
    }

    @Test func accessDeniedMenu() {
        let model = menuModel(state: .accessDenied(folder: "Документы"), loginEnabled: false)
        #expect(model.statusText == "Ошибка: нет доступа к папке «Документы»")
        #expect(model.symbolName == "exclamationmark.triangle.fill")
        #expect(model.hint == accessHint(folder: "Документы"))
        #expect(model.showsAccessSettings && model.canRestart)
    }

    @Test func otherStatesHideAccessSettings() {
        #expect(!menuModel(state: .starting, loginEnabled: false).showsAccessSettings)
        #expect(!menuModel(state: .failed("x"), loginEnabled: false).showsAccessSettings)
    }

    @Test func placeholderCarriesHint() {
        let text = "Нужно разрешение на папку «Документы»\n\n" + accessHint(folder: "Документы")
        #expect(windowContent(state: .waitingForAccess(folder: "Документы"), token: nil) == .placeholder(text))
    }

    @Test func settingsURL() {
        #expect(accessSettingsURL.absoluteString
            == "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders")
    }

    @Test func externalLinks() {
        #expect(opensExternally(URL(string: "https://ollama.com/library")!))
        #expect(opensExternally(URL(string: "mailto:a@b.c")!))
        #expect(!opensExternally(URL(string: "http://127.0.0.1:8765/settings")!))
        #expect(!opensExternally(URL(string: "http://localhost:8765/")!))
        #expect(!opensExternally(URL(string: "about:blank")!))
        #expect(!opensExternally(URL(string: "blob:http://127.0.0.1:8765/abc")!))
    }
}

@MainActor @Suite struct FileAccessProbeTests {
    private func wait(_ check: any AccessChecking) async -> AccessResult {
        for _ in 0..<200 {
            if let result = check.result { return result }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return .failed("timeout")
    }

    private func tempDir() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("smartesp-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @Test func readableFolderIsGranted() async throws {
        #expect(await wait(FileAccessProbe().check(try tempDir())) == .granted)
    }

    @Test func missingFolderFails() async throws {
        let result = await wait(FileAccessProbe().check(try tempDir().appendingPathComponent("nope")))
        guard case let .failed(text) = result else { Issue.record("ожидали failed, а не \(result)"); return }
        #expect(text.hasPrefix("Нет папки ядра"))
    }

    @Test func unreadableFolderIsDenied() async throws {
        let dir = try tempDir()
        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: dir.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path) }
        #expect(await wait(FileAccessProbe().check(dir)) == .denied)
    }
}
