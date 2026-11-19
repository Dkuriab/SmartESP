import Foundation
import ServiceManagement
import SmartEspKit

/// Автозапуск через `SMAppService.mainApp`; если регистрация не удалась
/// (ad-hoc подпись), пишет запасной LaunchAgent с `open -a /Applications/SmartEsp.app`.
@MainActor final class LoginItemService: LoginItemControlling {
    private let agent: LaunchAgentFile

    init() {
        let library = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library")
        agent = LaunchAgentFile(directory: library.appendingPathComponent("LaunchAgents"))
    }

    var isEnabled: Bool { SMAppService.mainApp.status == .enabled || agent.exists }

    func setEnabled(_ on: Bool) throws {
        if on {
            do {
                try SMAppService.mainApp.register()
            } catch {
                try agent.install()
            }
        } else {
            if SMAppService.mainApp.status != .notRegistered { try? SMAppService.mainApp.unregister() }
            try agent.remove()
        }
    }
}
