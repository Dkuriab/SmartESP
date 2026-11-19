import Foundation

/// Ответ `GET /api/v1/status`.
public enum ProbeResult: Equatable, Sendable {
    /// Ядро ответило: фаза (`warming`/`ready`/`stopping`), устройства онлайн/всего, доступна ли Ollama.
    case ok(state: String, devicesOnline: Int, devicesTotal: Int, ollama: Bool)
    /// 401: токен не подошёл (на порту чужое ядро или токен сменился).
    case unauthorized
    /// Порт не отвечает или ответ непонятен.
    case unreachable

    /// Разбирает тело ответа `status`.
    /// - Parameter data: JSON с `state`, `ollama.reachable`, `devices[].connected`.
    /// - Returns: `.ok` или `.unreachable`, если JSON битый или нет `state`.
    public static func parse(_ data: Data) -> ProbeResult {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let state = json["state"] as? String else { return .unreachable }
        let ollama = (json["ollama"] as? [String: Any])?["reachable"] as? Bool ?? false
        let devices = json["devices"] as? [[String: Any]] ?? []
        let online = devices.filter { $0["connected"] as? Bool == true }.count
        return .ok(state: state, devicesOnline: online, devicesTotal: devices.count, ollama: ollama)
    }
}

/// Опрос HTTP API ядра.
@MainActor public protocol StatusProbing: AnyObject {
    /// Запрашивает `GET /api/v1/status`.
    /// - Parameters:
    ///   - port: порт ядра на 127.0.0.1.
    ///   - token: токен доступа.
    /// - Returns: состояние ядра, `.unauthorized` или `.unreachable`.
    func status(port: Int, token: String) async -> ProbeResult

    /// Просит ядро перезапуститься (`POST /api/v1/restart`).
    /// - Parameters:
    ///   - port: порт ядра на 127.0.0.1.
    ///   - token: токен доступа.
    /// - Returns: `true`, если ядро приняло просьбу (202).
    func restart(port: Int, token: String) async -> Bool
}

/// Настоящий опрос через `URLSession`.
@MainActor public final class HTTPStatusProbe: StatusProbing {
    private let session: URLSession

    /// - Parameter timeout: сколько ждать ответа, секунд.
    public init(timeout: TimeInterval = 2) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        session = URLSession(configuration: config)
    }

    public func status(port: Int, token: String) async -> ProbeResult {
        guard let (data, code) = await send("GET", "status", port: port, token: token) else { return .unreachable }
        if code == 401 { return .unauthorized }
        return code == 200 ? ProbeResult.parse(data) : .unreachable
    }

    public func restart(port: Int, token: String) async -> Bool {
        await send("POST", "restart", port: port, token: token)?.1 == 202
    }

    private func send(_ method: String, _ path: String, port: Int, token: String) async -> (Data, Int)? {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/v1/\(path)") else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        guard let (data, response) = try? await session.data(for: request),
              let http = response as? HTTPURLResponse else { return nil }
        return (data, http.statusCode)
    }
}
