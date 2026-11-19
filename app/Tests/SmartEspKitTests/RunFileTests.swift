import Foundation
import Testing
@testable import SmartEspKit

private func tempFile(_ text: String?) -> URL {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("smartesp-\(UUID().uuidString)")
    if let text { try? text.write(to: url, atomically: true, encoding: .utf8) }
    return url
}

@Suite struct RunFileTests {
    @Test func readsValidFile() {
        let url = tempFile(#"{"port": 8765, "pid": 4242, "started_at": 1731900000.5}"#)
        #expect(RunFile.read(url) == RunInfo(port: 8765, pid: 4242, startedAt: 1731900000.5))
    }

    @Test func brokenEmptyOrMissingGivesNil() {
        #expect(RunFile.read(tempFile(#"{"port": 87"#)) == nil)
        #expect(RunFile.read(tempFile("")) == nil)
        #expect(RunFile.read(tempFile(#"{"port": "x", "pid": 1, "started_at": 0}"#)) == nil)
        #expect(RunFile.read(tempFile(nil)) == nil)
    }

    @Test func tokenIsTrimmedAndEmptyIsNil() {
        #expect(TokenFile.read(tempFile("abc\n")) == "abc")
        #expect(TokenFile.read(tempFile("  \n")) == nil)
        #expect(TokenFile.read(tempFile(nil)) == nil)
    }
}

@Suite struct CoreLogTests {
    @Test func readsOnlyLinesAfterOffset() {
        let url = tempFile("old line\n")
        let offset = CoreLog.size(url)
        try? "old line\nnew INFO a\nnew ERROR b\n\nnew INFO c\n".write(to: url, atomically: true, encoding: .utf8)
        let excerpt = CoreLog.read(url, from: offset)
        #expect(excerpt.lines == ["new INFO a", "new ERROR b", "new INFO c"])
        #expect(excerpt.errorLine == "new ERROR b")
    }

    @Test func noErrorLineWithoutErrors() {
        let url = tempFile("2026 INFO x: a\n2026 INFO x: b\n")
        #expect(CoreLog.read(url, from: 0).errorLine == nil)
        #expect(CoreLog.read(url, from: 0).lines.last == "2026 INFO x: b")
        #expect(CoreLog.read(tempFile(nil), from: 0).lines.isEmpty)
    }

    @Test func rotatedLogIsReadFromStart() {
        let url = tempFile("short\n")
        #expect(CoreLog.read(url, from: 10_000).lines == ["short"])
    }

    @Test func detectsPortConflict() {
        let line = "E [Errno 48] error while attempting to bind on address ('127.0.0.1', 8770): address already in use"
        let excerpt = CoreLog.read(tempFile(line + "\nINFO done\n"), from: 0)
        #expect(excerpt.portConflict)
        #expect(excerpt.conflictPort == 8770)
        #expect(CoreLog.read(tempFile("INFO fine\n"), from: 0).portConflict == false)
    }
}

@Suite struct ProbeResultTests {
    @Test func parsesStatus() {
        let json = #"""
        {"state": "ready", "ollama": {"reachable": true},
         "devices": [{"connected": true}, {"connected": false}, {"connected": true}]}
        """#
        #expect(ProbeResult.parse(Data(json.utf8)) == .ok(state: "ready", devicesOnline: 2, devicesTotal: 3, ollama: true))
    }

    @Test func missingPartsAreTolerated() {
        #expect(ProbeResult.parse(Data(#"{"state": "warming"}"#.utf8))
            == .ok(state: "warming", devicesOnline: 0, devicesTotal: 0, ollama: false))
        #expect(ProbeResult.parse(Data("not json".utf8)) == .unreachable)
        #expect(ProbeResult.parse(Data(#"{"devices": []}"#.utf8)) == .unreachable)
    }
}

/// Настоящий `Process` с подставными программами вместо `uv` (ядро не запускается).
@MainActor @Suite struct ProcessCoreLauncherTests {
    private func exitCode(of handle: any CoreHandle) async -> Int32 {
        await withCheckedContinuation { cont in handle.onExit { cont.resume(returning: $0) } }
    }

    @Test func reportsExitOfFailingProgram() async throws {
        // sh пытается выполнить файл «run» и сразу выходит с ошибкой
        let handle = try ProcessCoreLauncher().launch(
            uv: URL(fileURLWithPath: "/bin/sh"), cwd: FileManager.default.temporaryDirectory, env: [:])
        #expect(await exitCode(of: handle) != 0)
        #expect(!handle.isRunning)
        #expect(handle.pid > 0)
    }

    @Test func killStopsRunningProgram() async throws {
        // yes печатает аргументы бесконечно (в /dev/null), пока его не убьют
        let handle = try ProcessCoreLauncher().launch(
            uv: URL(fileURLWithPath: "/usr/bin/yes"), cwd: FileManager.default.temporaryDirectory, env: [:])
        #expect(handle.isRunning)
        #expect(isProcessAlive(handle.pid))
        handle.kill()
        _ = await exitCode(of: handle)
        #expect(!handle.isRunning)
    }

    @Test func deadPidIsNotAlive() {
        #expect(!isProcessAlive(0))
        #expect(isProcessAlive(getpid()))
    }
}

@MainActor @Suite struct ProcessCoreLauncherStderrTests {
    @Test func stderrGoesToFreshFile() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("smartesp-\(UUID().uuidString)")
        let log = dir.appendingPathComponent("logs/core-stderr.log")
        try FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "old junk\n".write(to: log, atomically: true, encoding: .utf8)
        let handle = try ProcessCoreLauncher(stderrLog: log).launch(
            uv: URL(fileURLWithPath: "/bin/sh"), cwd: FileManager.default.temporaryDirectory, env: [:])
        _ = await withCheckedContinuation { cont in handle.onExit { cont.resume(returning: $0) } }
        let text = try String(contentsOf: log, encoding: .utf8)
        #expect(!text.contains("old junk"))
        #expect(text.contains("run"))
    }
}
