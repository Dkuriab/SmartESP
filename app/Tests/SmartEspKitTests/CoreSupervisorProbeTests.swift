import Foundation
import Testing
@testable import SmartEspKit

/// Сбои опроса при живом ядре не сбрасывают окно на заглушку.
@MainActor @Suite struct CoreSupervisorProbeTests {
    private let ready = CoreState.running(port: 8765, phase: "ready", devices: (0, 0), ollama: true)

    /// Своё ядро запущено и ответило `ready`.
    private func runningRig() async -> Rig {
        let rig = Rig()
        await rig.supervisor.performStart()
        rig.writeRunFile(port: 8765, pid: 4242)
        rig.alive = [4242]
        rig.writeToken()
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        return rig
    }

    @Test func singleUnreachableKeepsRunning() async {
        let rig = await runningRig()
        let changes = rig.changes.count
        rig.probe.result = .unreachable
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == ready)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == ready)
        #expect(rig.changes.count == changes)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .starting)
    }

    @Test func successResetsFailureCount() async {
        let rig = await runningRig()
        rig.probe.result = .unauthorized
        await rig.supervisor.tick()
        await rig.supervisor.tick()
        rig.probe.result = .ok(state: "ready", devicesOnline: 0, devicesTotal: 0, ollama: true)
        await rig.supervisor.tick()
        rig.probe.result = .unauthorized
        await rig.supervisor.tick()
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == ready)
    }

    @Test func deadRunFilePidDropsAtOnce() async {
        let rig = await runningRig()
        rig.alive = []
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .starting)
    }

    @Test func missingRunFileButCoreAnswersStaysRunning() async throws {
        let rig = await runningRig()
        try FileManager.default.removeItem(at: rig.paths.dataDir)
        rig.clock.now += 60
        rig.probe.result = .ok(state: "ready", devicesOnline: 1, devicesTotal: 1, ollama: true)
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .running(port: 8765, phase: "ready", devices: (1, 1), ollama: true))
        #expect(rig.supervisor.token == "tok")
    }

    @Test func missingRunFileAndNoAnswerDropsAtOnce() async throws {
        let rig = await runningRig()
        try FileManager.default.removeItem(at: rig.paths.runFile)
        rig.probe.result = .unreachable
        await rig.supervisor.tick()
        #expect(rig.supervisor.state == .starting)
    }
}
