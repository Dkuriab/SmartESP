import Foundation
import ServiceManagement
import SmartEspKit

/// Автозапуск через `SMAppService.mainApp`; если регистрация не удалась
/// (ad-hoc подпись) или статус `.notFound`, пишет запасной LaunchAgent с `open -a <приложение>`.
@MainActor final class LoginItemService: LoginItemControlling {
    private struct StillEnabled: LocalizedError {
        var errorDescription: String? { "Автозапуск остался включённым. Отключите его в Системных настройках → Основные → Объекты входа." }
    }

    private let agent: LaunchAgentFile
    private let appPath = Bundle.main.bundlePath

    init() {
        let library = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library")
        agent = LaunchAgentFile(directory: library.appendingPathComponent("LaunchAgents"))
    }

    private var status: LoginStatus {
        switch SMAppService.mainApp.status {
        case .enabled: return .enabled
        case .requiresApproval: return .requiresApproval
        case .notFound: return .notFound
        default: return .notRegistered
        }
    }

    var isEnabled: Bool { status == .enabled || agent.exists }

    var menuState: LoginMenuState {
        loginMenuState(status: status, agentExists: agent.exists, inApplications: appPath.hasPrefix("/Applications/"))
    }

    func setEnabled(_ on: Bool) throws {
        if on {
            do {
                try SMAppService.mainApp.register()
                if status == .notFound { try agent.install(appPath: appPath) }
            } catch {
                try agent.install(appPath: appPath)
            }
        } else {
            if status == .enabled || status == .requiresApproval { try SMAppService.mainApp.unregister() }
            try agent.remove()
            if isEnabled { throw StillEnabled() }
        }
    }
}
