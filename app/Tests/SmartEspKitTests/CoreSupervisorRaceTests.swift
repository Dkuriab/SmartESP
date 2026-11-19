import Foundation
import Testing
@testable import SmartEspKit

private let conflictLine =
    "2026-11-18 10:00:00,000 ERROR uvicorn.error: [Errno 48] error while attempting to bind on address "
    + "('127.0.0.1', 8765): address already in use"

/// Ждёт, пока задачи на главном акторе отработают (onExit → tick).
@MainActor private func drain(until done: () -> Bool) async {
    for _ in 0..<1000 where !done() { await Task.yield() }
}

/// Перезапуск приложения, пока прежнее ядро ещё останавливается, и гонки остановки.
@MainActor @Suite struct CoreSupervisorRaceTests {
    @Test func stoppingExternalCoreIsAwaitedThenOwnLaunched() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.diesAt = [4242: rig.clock.now + 5]
        rig.writeToken()
        rig.probe.result = .ok(state: "stopping", devicesOnline: 0, devicesTotal: 0, ollama: false)
        let started = rig.clock.now
        await rig.supervisor.performStart()
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .starting)
        #expect(rig.clock.now - started >= 5 && rig.clock.now - started < 6)
    }

    @Test func portConflictWithOldCoreStillAliveIsRetried() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .unreachable  // прежнее ядро уже закрыло API, но порт ещё держит
        await rig.supervisor.performStart()
        rig.appendLog([conflictLine, "2026-11-18 10:00:00,200 INFO smartesp: Ядро остановлено"])
        rig.diesAt = [4242: rig.clock.now + 3]
        rig.crashLast()
        await rig.supervisor.tick()
        #expect(rig.launcher.handles.count == 2)
        #expect(rig.supervisor.state == .starting)

        rig.writeRunFile(port: 8765, pid: 5000)
        rig.alive = [5000]
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .running(port: 8765, phase: "ready", devices: (0, 0), ollama: true))
    }

    @Test func persistentConflictWithLivePidFailsWithPortMessageAtLimit() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        await rig.supervisor.performStart()
        for _ in 1...3 {
            rig.appendLog([conflictLine])
            rig.crashLast()
            await rig.supervisor.tick()
        }
        #expect(rig.launcher.handles.count == 3)
        #expect(rig.supervisor.state == .failed("Порт 8765 занят другой программой"))
    }

    @Test func stderrExplainsCrashWithoutErrorLine() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        for _ in 1...3 {
            rig.appendLog(["2026-11-18 10:00:00,000 INFO smartesp: что-то"])
            rig.writeStderr("Resolved 40 packages\nerror: Failed to spawn: `python`\n\n")
            rig.crashLast()
            await rig.supervisor.tick()
        }
        #expect(rig.supervisor.state == .failed("error: Failed to spawn: `python`"))
    }

    @Test func errorLineInLogBeatsStderr() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        for _ in 1...3 {
            rig.appendLog(["2026-11-18 10:00:00,000 ERROR smartesp: плохо", "x INFO y: Ядро остановлено"])
            rig.writeStderr("Traceback\n")
            rig.crashLast()
            await rig.supervisor.tick()
        }
        #expect(rig.supervisor.state == .failed("2026-11-18 10:00:00,000 ERROR smartesp: плохо"))
    }

    @Test func onExitTriggersTick() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.launcher.handles[0].exit()
        await drain { rig.launcher.handles.count == 2 }
        #expect(rig.launcher.handles.count == 2)
    }

    @Test func secondStopDoesNotSignalAgain() async {
        let rig = Rig()
        rig.launcher.exitsOnTerminate = false
        await rig.supervisor.performStart()
        let sup = rig.supervisor
        async let first: Void = sup.stop()
        async let second: Void = sup.stop()
        _ = await (first, second)
        #expect(rig.launcher.handles[0].terminateCount == 1)
        #expect(rig.launcher.handles[0].killCount == 1)
        #expect(sup.state == .stopped)
    }

    @Test func stopWhileStartProbeIsPendingLaunchesNothing() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.hold = true
        rig.supervisor.start()
        await drain { rig.probe.waiter != nil }
        let stopping = Task { await rig.supervisor.stop() }
        await drain { false }
        rig.probe.release()
        await stopping.value
        #expect(rig.launcher.handles.isEmpty)
        #expect(rig.supervisor.state == .stopped)
    }

    @Test func tokenClearedOnStop() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        await rig.supervisor.tick()
        #expect(rig.supervisor.token == "tok")
        await rig.supervisor.stop()
        #expect(rig.supervisor.token == nil)
        #expect(rig.supervisor.port == nil)
    }
}
