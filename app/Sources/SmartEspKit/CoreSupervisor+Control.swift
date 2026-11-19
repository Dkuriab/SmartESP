import Darwin
import Foundation

/// «Взять управление» чужим ядром и чистый выход своего.
extension CoreSupervisor {
    /// «Взять управление»: проверяет, что pid из файла запуска — ядро SmartESP,
    /// посылает ему SIGTERM, ждёт выхода не дольше `stopTimeout` и запускает своё ядро.
    /// Не вышло за это время — ошибка; SIGKILL чужому процессу не посылаем.
    /// Только для чужого ядра; сразу возвращается.
    public func takeOver() {
        guard case .external = mode, !startInProgress else { return }
        startTask = Task { await self.performTakeOver() }
    }

    func performTakeOver() async {
        guard case .external(let pid) = mode, !startInProgress else { return }
        startInProgress = true
        let current = generation
        guard let arguments = commandLine(pid), isSmartEspCoreCommand(arguments) else {
            startInProgress = false
            return fail("Процесс \(pid) из run/core.json не похож на ядро SmartESP — не трогаю его")
        }
        stopPolling()
        mode = .idle
        clearConnection()
        state = .stopping
        if !sendSignal(pid, SIGTERM) && pidAlive(pid) {
            startInProgress = false
            return fail("Не удалось остановить ядро (pid \(pid)): нет прав")
        }
        let finished = await waitForExit(pid, current)
        startInProgress = false
        // Пока ждали, позвали `stop()` (выход из приложения) — своё ядро не запускаем
        guard finished else { return }
        if pidAlive(pid) {
            return fail("Ядро (pid \(pid)) не остановилось за \(Int(Self.stopTimeout)) с — остановите его вручную")
        }
        crashTimes = []
        await performStart()
    }

    /// Своё ядро вышло с кодом 0: его остановили (сигналом или через API), это не падение —
    /// не перезапускаем.
    func stoppedByItself() {
        mode = .idle
        clearConnection()
        stopPolling()
        state = .stopped
    }
}

/// Похожа ли командная строка на ядро SmartESP (`python -m smartesp …`).
/// - Parameter arguments: аргументы процесса, первый — сама программа.
/// - Returns: `true`, если среди аргументов есть `-m smartesp` или `-msmartesp`.
public func isSmartEspCoreCommand(_ arguments: [String]) -> Bool {
    let args = Array(arguments.dropFirst())
    for (index, arg) in args.enumerated() {
        if arg == "-msmartesp" { return true }
        if arg == "-m", index + 1 < args.count, args[index + 1] == "smartesp" { return true }
    }
    return false
}

/// Аргументы процесса по pid (`sysctl KERN_PROCARGS2`).
/// - Parameter pid: номер процесса.
/// - Returns: аргументы (первый — программа) или `nil`, если процесса нет или он чужого пользователя.
public func processArguments(_ pid: Int32) -> [String]? {
    guard pid > 0 else { return nil }
    var mib: [Int32] = [CTL_KERN, KERN_PROCARGS2, pid]
    var size = 0
    guard sysctl(&mib, 3, nil, &size, nil, 0) == 0, size > MemoryLayout<Int32>.size else { return nil }
    var buffer = [UInt8](repeating: 0, count: size)
    guard sysctl(&mib, 3, &buffer, &size, nil, 0) == 0, size > MemoryLayout<Int32>.size else { return nil }
    // Формат: argc (int32), путь программы, нули выравнивания, затем argc строк через \0
    let argc = buffer.withUnsafeBytes { $0.loadUnaligned(as: Int32.self) }
    var index = MemoryLayout<Int32>.size
    while index < size && buffer[index] != 0 { index += 1 }
    while index < size && buffer[index] == 0 { index += 1 }
    var arguments: [String] = []
    while arguments.count < Int(argc) && index < size {
        let start = index
        while index < size && buffer[index] != 0 { index += 1 }
        arguments.append(String(decoding: buffer[start..<index], as: UTF8.self))
        index += 1
    }
    return arguments.count == Int(argc) ? arguments : nil
}
