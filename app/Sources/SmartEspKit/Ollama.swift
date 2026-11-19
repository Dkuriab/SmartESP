import Foundation

/// Состояние Ollama для меню и окна.
public enum OllamaState: Equatable, Sendable {
    /// Ещё не проверяли.
    case unknown
    /// `GET /api/version` отвечает.
    case up
    /// Не отвечает.
    case down
    /// Приложение запустило Ollama и ждёт ответа.
    case launching
    /// Запустить не удалось; текст для меню. Держится, пока Ollama не ответит.
    case failed(String)
}

/// Проверка, отвечает ли Ollama.
@MainActor public protocol OllamaProbing: AnyObject {
    /// - Returns: `true`, если `GET http://127.0.0.1:11434/api/version` ответил 200.
    func isUp() async -> Bool
}

/// Запуск Ollama.
@MainActor public protocol OllamaLaunching: AnyObject {
    /// Открывает приложение Ollama (`open -a`).
    /// - Parameter app: путь к `Ollama.app`.
    /// - Throws: ошибку запуска `open`.
    func openApp(_ app: URL) throws
    /// Запускает `<binary> serve` в фоне, отдельно от приложения.
    /// - Parameter binary: путь к программе `ollama`.
    /// - Throws: ошибку запуска.
    func serve(_ binary: URL) throws
}

/// Как запускать Ollama.
public enum OllamaLaunchPlan: Equatable, Sendable {
    /// Есть `Ollama.app` — открыть его.
    case openApp(URL)
    /// Приложения нет, есть программа `ollama` — `ollama serve`.
    case serve(URL)
    /// Ollama не установлена.
    case notFound
}

/// Выбирает способ запуска Ollama: `/Applications/Ollama.app` или `~/Applications/Ollama.app`,
/// иначе `ollama` в `/opt/homebrew/bin`, `/usr/local/bin` или `PATH`.
/// - Parameters:
///   - env: переменные окружения (берётся `PATH`).
///   - home: домашняя папка.
///   - exists: есть ли файл или папка по пути.
///   - isExecutable: исполняемый ли файл по пути.
/// - Returns: план запуска.
public func ollamaLaunchPlan(
    env: [String: String], home: URL, exists: (String) -> Bool, isExecutable: (String) -> Bool
) -> OllamaLaunchPlan {
    let apps = ["/Applications/Ollama.app", home.appendingPathComponent("Applications/Ollama.app").path]
    if let app = apps.first(where: exists) { return .openApp(URL(fileURLWithPath: app)) }
    let known = ["/opt/homebrew/bin", "/usr/local/bin"]
    if let binary = findExecutable("ollama", in: known, env: env, fileExists: isExecutable) {
        return .serve(binary)
    }
    return .notFound
}

/// Следит за Ollama (опрос раз в `pollInterval`) и запускает её по просьбе.
@MainActor public final class OllamaControl {
    /// Период опроса, секунд.
    public static let pollInterval: TimeInterval = 5
    /// Сколько ждать ответа после запуска, секунд.
    public static let launchTimeout: TimeInterval = 30
    /// Шаг ожидания после запуска, секунд.
    static let launchStep: TimeInterval = 0.5
    /// Текст ошибки, когда Ollama не установлена.
    public static let notFoundText = "не установлена (ollama.com)"

    /// Текущее состояние.
    public private(set) var state: OllamaState = .unknown {
        didSet { if state != oldValue { onChange?(state) } }
    }
    /// Вызывается при каждой смене состояния.
    public var onChange: ((OllamaState) -> Void)?

    private let probe: any OllamaProbing
    private let launcher: any OllamaLaunching
    private let plan: () -> OllamaLaunchPlan
    private let clock: () -> TimeInterval
    private let sleep: @MainActor (TimeInterval) async -> Void
    private let autoPoll: Bool
    private var pollTask: Task<Void, Never>?
    private var launching = false

    /// - Parameters:
    ///   - probe: проверка ответа Ollama.
    ///   - launcher: запуск приложения или `ollama serve`.
    ///   - plan: выбор способа запуска (вызывается при каждом запуске).
    ///   - clock: монотонные секунды.
    ///   - sleep: пауза в секундах.
    ///   - autoPoll: `startPolling()` действительно опрашивает; в тестах `false`.
    public init(
        probe: any OllamaProbing,
        launcher: any OllamaLaunching,
        plan: @escaping () -> OllamaLaunchPlan,
        clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        sleep: @escaping @MainActor (TimeInterval) async -> Void = { try? await Task.sleep(for: .seconds($0)) },
        autoPoll: Bool = true
    ) {
        self.probe = probe
        self.launcher = launcher
        self.plan = plan
        self.clock = clock
        self.sleep = sleep
        self.autoPoll = autoPoll
    }

    /// Начинает опрос раз в `pollInterval` (первый — сразу).
    public func startPolling() {
        guard autoPoll, pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refresh()
                await self.sleep(Self.pollInterval)
            }
        }
    }

    /// Проверяет Ollama сейчас. Во время запуска ничего не делает; ошибка запуска
    /// держится, пока Ollama не ответит.
    public func refresh() async {
        guard !launching else { return }
        let up = await probe.isUp()
        guard !launching else { return }
        if up { return state = .up }
        if case .failed = state { return }
        state = .down
    }

    /// «Запустить Ollama»: открывает приложение или `ollama serve` и ждёт ответа
    /// не дольше `launchTimeout`. Уже отвечает — только обновляет состояние.
    public func launch() async {
        guard !launching else { return }
        launching = true
        defer { launching = false }
        if await probe.isUp() { return state = .up }
        do {
            switch plan() {
            case let .openApp(app): try launcher.openApp(app)
            case let .serve(binary): try launcher.serve(binary)
            case .notFound: return state = .failed(Self.notFoundText)
            }
        } catch {
            return state = .failed("Не удалось запустить Ollama: \(error.localizedDescription)")
        }
        state = .launching
        let deadline = clock() + Self.launchTimeout
        while clock() < deadline {
            await sleep(Self.launchStep)
            if await probe.isUp() { return state = .up }
        }
        state = .failed("не ответила за \(Int(Self.launchTimeout)) с после запуска")
    }
}
