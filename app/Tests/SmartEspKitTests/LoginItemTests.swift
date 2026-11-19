import Foundation
import Testing
@testable import SmartEspKit

@Suite struct LoginItemTests {
    @Test func firstLaunchDefaultOnlyInApplications() {
        #expect(firstLaunchDefault(bundlePath: "/Applications/SmartEsp.app", alreadyDecided: false))
        #expect(!firstLaunchDefault(bundlePath: "/Users/x/SmartEsp/app/build/SmartEsp.app", alreadyDecided: false))
        #expect(!firstLaunchDefault(bundlePath: "/Applications/SmartEsp.app", alreadyDecided: true))
    }

    @Test func plistContent() throws {
        let data = try launchAgentPlist()
        let plist = try #require(
            try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any])
        #expect(plist["Label"] as? String == "com.smartesp.app")
        #expect(plist["ProgramArguments"] as? [String] == ["/usr/bin/open", "-a", "/Applications/SmartEsp.app"])
        #expect(plist["RunAtLoad"] as? Bool == true)
    }

    @Test func agentFileInstallAndRemove() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("la-" + UUID().uuidString).appendingPathComponent("LaunchAgents")
        let file = LaunchAgentFile(directory: dir)
        #expect(!file.exists)
        try file.remove()  // нет файла — не ошибка
        try file.install()
        #expect(file.exists && file.url.lastPathComponent == "com.smartesp.app.plist")
        try file.remove()
        #expect(!file.exists)
        try? FileManager.default.removeItem(at: dir.deletingLastPathComponent())
    }

    @Test func retryOnlyOnNetworkErrors() {
        #expect(shouldRetryLoad(domain: NSURLErrorDomain, code: NSURLErrorCannotConnectToHost))
        #expect(!shouldRetryLoad(domain: NSURLErrorDomain, code: NSURLErrorCancelled))
        #expect(!shouldRetryLoad(domain: "WebKitErrorDomain", code: 102))
        #expect(!shouldRetryLoad(domain: "WKErrorDomain", code: 102))
    }
}
