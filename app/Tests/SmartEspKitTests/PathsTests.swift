import Foundation
import Testing
@testable import SmartEspKit

private let home = URL(fileURLWithPath: "/Users/tester")

@Suite struct AppPathsTests {
    @Test func repoFromInfoPlist() {
        let paths = AppPaths.resolve(env: [:], infoPlist: ["SmartEspRepoPath": "/repo/plist"], home: home)
        #expect(paths?.repo.path == "/repo/plist")
        #expect(paths?.coreDir.path == "/repo/plist/core")
    }

    @Test func envRepoBeatsInfoPlist() {
        let paths = AppPaths.resolve(
            env: ["SMARTESP_REPO": "/repo/env"],
            infoPlist: ["SmartEspRepoPath": "/repo/plist"], home: home)
        #expect(paths?.repo.path == "/repo/env")
    }

    @Test func noRepoGivesNil() {
        #expect(AppPaths.resolve(env: [:], infoPlist: [:], home: home) == nil)
        #expect(AppPaths.resolve(env: ["SMARTESP_REPO": ""], infoPlist: ["SmartEspRepoPath": ""], home: home) == nil)
    }

    @Test func defaultDataDirIsHomeSmartEsp() {
        let paths = AppPaths.resolve(env: [:], infoPlist: ["SmartEspRepoPath": "/r"], home: home)
        #expect(paths?.dataDir.path == "/Users/tester/SmartEsp")
        #expect(paths?.runFile.path == "/Users/tester/SmartEsp/run/core.json")
        #expect(paths?.tokenFile.path == "/Users/tester/SmartEsp/token")
        #expect(paths?.logFile.path == "/Users/tester/SmartEsp/logs/core.log")
    }

    @Test func smartespHomeBeatsDefault() {
        let paths = AppPaths.resolve(
            env: ["SMARTESP_HOME": "/data/x"], infoPlist: ["SmartEspRepoPath": "/r"], home: home)
        #expect(paths?.dataDir.path == "/data/x")
        #expect(paths?.tokenFile.path == "/data/x/token")
    }
}

@Suite struct FindUvTests {
    @Test func searchesInOrder() {
        let all = Set(["/Users/tester/.local/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv", "/p/uv"])
        let env = ["PATH": "/p:/q"]
        #expect(findUv(env: env, home: home, fileExists: { all.contains($0) })?.path == "/Users/tester/.local/bin/uv")
        #expect(findUv(env: env, home: home, fileExists: { $0 != "/Users/tester/.local/bin/uv" && all.contains($0) })?.path == "/opt/homebrew/bin/uv")
        #expect(findUv(env: env, home: home, fileExists: { $0 == "/usr/local/bin/uv" || $0 == "/p/uv" })?.path == "/usr/local/bin/uv")
        #expect(findUv(env: env, home: home, fileExists: { $0 == "/q/uv" })?.path == "/q/uv")
    }

    @Test func nothingFoundGivesNil() {
        #expect(findUv(env: ["PATH": "/p"], home: home, fileExists: { _ in false }) == nil)
        #expect(findUv(env: [:], home: home, fileExists: { _ in false }) == nil)
    }
}
