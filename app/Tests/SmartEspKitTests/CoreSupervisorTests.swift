import Foundation
import Testing
@testable import SmartEspKit

private let conflictLine =
    "2026-11-18 10:00:00,000 ERROR uvicorn.error: [Errno 48] error while attempting to bind on address "
    + "('127.0.0.1', 8765): address already in use"

@MainActor @Suite struct CoreSupervisorStartTests {
    @Test func startingThenWarmingThenReady() async {
        let rig = Rig()
        rig.supervisor.start()
        await rig.supervisor.startTask?.value
        #expect(rig.supervisor.state == .starting)
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.launcher.lastCwd == rig.paths.coreDir)
        #expect(rig.launcher.lastUv?.path == rig.dir.appendingPathComponent(".local/bin/uv").path)

        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "warming", devicesOnline: 0, devicesTotal: 1, ollama: false)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .running(port: 8765, phase: "warming", devices: (0, 1), ollama: false))
        #expect(rig.supervisor.port == 8765)
        #expect(rig.supervisor.token == "tok")

        rig.probe.result = .ok(state: "ready", devicesOnline: 1, devicesTotal: 1, ollama: true)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .running(port: 8765, phase: "ready", devices: (1, 1), ollama: true))
        #expect(rig.changes.contains(.starting))
    }

    @Test func noTokenStaysStartingWithoutStatusCall() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .starting)
        #expect(rig.probe.statusCalls == 0)
        #expect(rig.supervisor.token == nil)
    }

    @Test func liveExternalCoreIsAdoptedAndNeverSignalled() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "ready", devicesOnline: 2, devicesTotal: 3, ollama: true)
        await rig.supervisor.performStart()
        #expect(rig.supervisor.state == .external(port: 8765, phase: "ready", devices: (2, 3), ollama: true))
        #expect(rig.launcher.handles.isEmpty)

        await rig.supervisor.stop()
        #expect(rig.launcher.handles.isEmpty)
        #expect(rig.supervisor.state == .external(port: 8765, phase: "ready", devices: (2, 3), ollama: true))

        rig.probe.restartAccepted = true
        await rig.supervisor.restart()
        #expect(rig.probe.restartCalls == 1)
        #expect(rig.launcher.handles.isEmpty)
    }

    @Test func externalCoreGoneMeansStopped() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.performStart()
        rig.alive = []
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .stopped)
        #expect(rig.launcher.handles.isEmpty)
    }

    @Test func liveForeignPidAnswering401IsNotAdopted() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .unauthorized
        await rig.supervisor.performStart()
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.supervisor.state == .starting)
    }

    @Test func missingUvFails() async {
        let rig = Rig()
        rig.uvExists = false
        await rig.supervisor.performStart()
        #expect(rig.supervisor.state == .failed("Не найден uv"))
        #expect(rig.launcher.handles.isEmpty)
    }
}

@MainActor @Suite struct CoreSupervisorCrashTests {
    @Test func threeCrashesWithinMinuteFailWithLastLogLine() async {
        let rig = Rig()
        rig.appendLog(["old ERROR line from a previous run"])
        await rig.supervisor.performStart()
        for attempt in 1...3 {
            rig.appendLog([
                "2026-11-18 10:00:0\(attempt),000 ERROR smartesp: Ядро не запущено: попытка \(attempt)",
                "  extra details",
            ])
            rig.crashLast()
            rig.clock.now += 5
            await rig.supervisor.tick()
        }
        #expect(rig.supervisor.state == .failed("2026-11-18 10:00:03,000 ERROR smartesp: Ядро не запущено: попытка 3"))
        #expect(rig.launcher.handles.count == 3)
        await rig.supervisor.tick()
        #expect(rig.launcher.handles.count == 3)
    }

    @Test func crashesSpreadOverMoreThanMinuteKeepRestarting() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        for _ in 1...4 {
            rig.crashLast()
            rig.clock.now += 31
            await rig.supervisor.tick()
        }
        #expect(rig.launcher.handles.count == 5)
        #expect(rig.supervisor.state == .starting)
    }

    @Test func crashWithEmptyLogStillFails() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        for _ in 1...3 {
            rig.crashLast()
            await rig.supervisor.tick()
        }
        #expect(rig.supervisor.state == .failed("Ядро завершилось, в журнале нет новых записей"))
    }

    @Test func foreignProcessOnPortGivesClearError() async {
        let rig = Rig()
        rig.writeRunFile(port: 8765, pid: 4242)  // pid мёртв
        rig.writeToken()
        rig.probe.result = .unauthorized
        await rig.supervisor.performStart()
        #expect(rig.launcher.handles.count == 1)
        rig.appendLog([conflictLine, "2026-11-18 10:00:00,100 CRITICAL smartesp: Ядро упало", "SystemExit: 1",
                       "2026-11-18 10:00:00,200 INFO smartesp: Ядро остановлено"])
        rig.crashLast()
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .failed("Порт 8765 занят другой программой"))
        #expect(rig.launcher.handles.count == 1)
    }

    @Test func restartAfterFailureStartsAgain() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        for _ in 1...3 {
            rig.crashLast()
            await rig.supervisor.tick()
        }
        #expect(rig.launcher.handles.count == 3)
        await rig.supervisor.restart()
        #expect(rig.launcher.handles.count == 4)
        #expect(rig.supervisor.state == .starting)
    }
}

@MainActor @Suite struct CoreSupervisorStopTests {
    @Test func stuckCoreIsKilledAfter15Seconds() async {
        let rig = Rig()
        rig.launcher.exitsOnTerminate = false
        await rig.supervisor.performStart()
        let started = rig.clock.now
        await rig.supervisor.stop()
        let handle = rig.launcher.handles[0]
        #expect(handle.terminateCount == 1)
        #expect(handle.killCount == 1)
        #expect(rig.clock.now - started >= 15 && rig.clock.now - started < 16)
        #expect(rig.supervisor.state == .stopped)
        #expect(rig.changes.contains(.stopping))
    }

    @Test func coreExitingAtOnceIsNotKilled() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        let started = rig.clock.now
        await rig.supervisor.stop()
        #expect(rig.launcher.handles[0].terminateCount == 1)
        #expect(rig.launcher.handles[0].killCount == 0)
        #expect(rig.clock.now - started < 1)
        #expect(rig.supervisor.state == .stopped)
    }

    @Test func stopDuringWarmupUsesSame15SecondRule() async {
        let rig = Rig()
        rig.launcher.exitsOnTerminate = false
        await rig.supervisor.performStart()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "warming", devicesOnline: 0, devicesTotal: 0, ollama: false)
        await rig.supervisor.tick()
        let started = rig.clock.now
        await rig.supervisor.stop()
        #expect(rig.launcher.handles[0].killCount == 1)
        #expect(rig.clock.now - started < 16)
        #expect(rig.supervisor.state == .stopped)
        await rig.supervisor.tick()
        #expect(rig.launcher.handles.count == 1)
    }

    @Test func stopWhileStartingBeforeRunFileKillsToo() async {
        let rig = Rig()
        rig.launcher.exitsOnTerminate = false
        await rig.supervisor.performStart()
        await rig.supervisor.stop()
        #expect(rig.launcher.handles[0].killCount == 1)
        #expect(rig.supervisor.state == .stopped)
    }

    @Test func ownRestartUsesApiFirst() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        rig.probe.restartAccepted = true
        await rig.supervisor.restart()
        #expect(rig.probe.restartCalls == 1)
        #expect(rig.launcher.handles.count == 1)
        #expect(rig.launcher.handles[0].terminateCount == 0)
    }

    @Test func ownRestartFallsBackToStopAndStart() async {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        rig.probe.restartAccepted = false
        rig.probe.result = .unreachable
        await rig.supervisor.restart()
        #expect(rig.launcher.handles[0].terminateCount == 1)
        #expect(rig.launcher.handles.count == 2)
        #expect(rig.supervisor.state == .starting)
    }
}
