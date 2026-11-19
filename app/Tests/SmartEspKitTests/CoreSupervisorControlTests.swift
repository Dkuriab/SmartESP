import Foundation
import Testing
@testable import SmartEspKit

private let coreCommand = ["/repo/core/.venv/bin/python3", "-m", "smartesp", "--parent-watch"]

/// Стенд с подключённым чужим ядром pid 4242 на порту 8765.
@MainActor private func adoptedRig() async -> Rig {
    let rig = Rig()
    rig.writeRunFile(port: 8765, pid: 4242)
    rig.alive = [4242]
    rig.writeToken()
    rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
    await rig.supervisor.performStart()
    return rig
}

/// «Взять управление» чужим ядром, «Остановить ядро» и чистый выход своего ядра.
@MainActor @Suite struct CoreSupervisorControlTests {
    @Test func takeOverStopsVerifiedCoreAndLaunchesOwn() async {
        let rig = await adoptedRig()
        #expect(rig.supervisor.state == .external(port: 8765, phase: "ready", devices: (0, 0), ollama: true))
        rig.commandLines[4242] = coreCommand
        rig.exitsOnTerm = [4242]
        rig.supervisor.takeOver()
        await rig.supervisor.startTask?.value
        #expect(rig.signals.map(\.pid) == [4242])
        #expect(rig.signals.map(\.signal) == [SIGTERM])
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .starting)
        #expect(rig.changes.contains(.stopping))
    }

    @Test func takeOverWaitsForSlowExit() async {
        let rig = await adoptedRig()
        rig.commandLines[4242] = coreCommand
        rig.diesAt = [4242: rig.clock.now + 5]
        let started = rig.clock.now
        rig.supervisor.takeOver()
        await rig.supervisor.startTask?.value
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.clock.now - started >= 5 && rig.clock.now - started < 6)
    }

    @Test func takeOverRefusesProcessThatIsNotCore() async {
        let rig = await adoptedRig()
        rig.commandLines[4242] = ["/usr/bin/vim", "/Users/x/SmartEsp/notes.txt"]
        rig.supervisor.takeOver()
        await rig.supervisor.startTask?.value
        #expect(rig.signals.isEmpty)
        #expect(rig.launcher.handles.isEmpty)
        guard case let .failed(message) = rig.supervisor.state else {
            Issue.record("ожидали ошибку, а состояние \(rig.supervisor.state)")
            return
        }
        #expect(message.contains("4242"))
    }

    @Test func takeOverRefusesUnreadableCommandLine() async {
        let rig = await adoptedRig()
        rig.supervisor.takeOver()
        await rig.supervisor.startTask?.value
        #expect(rig.signals.isEmpty)
        #expect(rig.launcher.handles.isEmpty)
        if case .failed = rig.supervisor.state {} else { Issue.record("ожидали ошибку") }
    }

    @Test func takeOverTimeoutIsErrorWithoutKill() async {
        let rig = await adoptedRig()
        rig.commandLines[4242] = coreCommand
        let started = rig.clock.now
        rig.supervisor.takeOver()
        await rig.supervisor.startTask?.value
        #expect(rig.signals.map(\.signal) == [SIGTERM])
        #expect(rig.launcher.handles.isEmpty)
        #expect(rig.clock.now - started >= CoreSupervisor.stopTimeout)
        guard case let .failed(message) = rig.supervisor.state else {
            Issue.record("ожидали ошибку, а состояние \(rig.supervisor.state)")
            return
        }
        #expect(message.contains("15 с"))
        // Из ошибки «Запустить ядро» снова подключается к живому чужому ядру
        await rig.supervisor.restart()
        #expect(rig.supervisor.state == .external(port: 8765, phase: "ready", devices: (0, 0), ollama: true))
    }

    @Test func takeOverOfOwnCoreDoesNothing() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.supervisor.takeOver()
        await rig.supervisor.startTask?.value
        #expect(rig.signals.isEmpty)
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .starting)
    }

    @Test func stopDuringTakeOverLaunchesNothing() async {
        let rig = await adoptedRig()
        rig.commandLines[4242] = coreCommand
        rig.diesAt = [4242: rig.clock.now + 10]
        rig.supervisor.takeOver()
        await Task.yield()
        await rig.supervisor.stop()
        #expect(rig.launcher.handles.isEmpty)
        #expect(rig.supervisor.state == .stopped)
    }

    @Test func explicitStopIsNotRestarted() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        await rig.supervisor.stop()
        #expect(rig.supervisor.state == .stopped)
        for _ in 0..<3 { await rig.supervisor.tick() }
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .stopped)
        // «Запустить ядро»
        rig.supervisor.start()
        await rig.supervisor.startTask?.value
        #expect(rig.launcher.handles.count == 2)
        #expect(rig.supervisor.state == .starting)
    }

    @Test func cleanExitOfOwnCoreMeansStopped() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.launcher.handles.last?.exit(code: 0)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .stopped)
        #expect(rig.launcher.handles.count == 1)
        await rig.supervisor.tick()
        #expect(rig.launcher.handles.count == 1)
    }

    @Test func failingExitOfOwnCoreIsRestarted() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.launcher.handles.last?.exit(code: 1)
        await rig.supervisor.tick()
        #expect(rig.launcher.handles.count == 2)
        #expect(rig.supervisor.state == .starting)
    }
}

@Suite struct CoreCommandTests {
    @Test func recognisesCoreCommandLine() {
        #expect(isSmartEspCoreCommand(coreCommand))
        #expect(isSmartEspCoreCommand(["python", "-m", "smartesp"]))
        #expect(isSmartEspCoreCommand(["/usr/bin/python3", "-msmartesp"]))
    }

    @Test func rejectsOtherProcesses() {
        #expect(!isSmartEspCoreCommand([]))
        #expect(!isSmartEspCoreCommand(["/usr/bin/vim", "/Users/x/SmartEsp/smartesp"]))
        #expect(!isSmartEspCoreCommand(["python", "-m", "smartesp_other"]))
        #expect(!isSmartEspCoreCommand(["python", "smartesp"]))
    }

    @Test func readsOwnArguments() {
        let args = processArguments(ProcessInfo.processInfo.processIdentifier)
        #expect(args?.first.map { URL(fileURLWithPath: $0).lastPathComponent } != nil)
        #expect(args?.count == CommandLine.arguments.count)
    }

    @Test func unknownPidHasNoArguments() {
        #expect(processArguments(-1) == nil)
        #expect(processArguments(0) == nil)
    }
}
