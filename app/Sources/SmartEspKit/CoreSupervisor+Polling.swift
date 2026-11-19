import Foundation

/// Запуск, опрос и обработка падений ядра.
extension CoreSupervisor {
    // MARK: - Запуск

    /// Подключается к живому ядру из файла запуска. Ядро в фазе `stopping`
    /// (прежний экземпляр приложения только что закрылся) не берём: ждём его выхода.
    /// - Returns: `true`, если подключились.
    func adoptExternal(_ current: Int) async -> Bool {
        guard let info = RunFile.read(paths.runFile), pidAlive(info.pid),
              let token = TokenFile.read(paths.tokenFile) else { return false }
        guard case let .ok(phase, online, total, ollama) = await probe.status(port: info.port, token: token)
        else { return false }
        if phase == "stopping" {
            _ = await waitForExit(info.pid, current)
            return false
        }
        guard current == generation else { return false }
        mode = .external(pid: info.pid)
        port = info.port
        self.token = token
        state = .external(port: info.port, phase: phase, devices: (online, total), ollama: ollama)
        return true
    }

    func launchOwn() {
        guard let uv = findUv(env: env, home: home, fileExists: fileExists) else { return fail(CoreErrors.uvNotFound) }
        logOffset = CoreLog.size(paths.logFile)
        do {
            let handle = try launcher.launch(uv: uv, cwd: paths.coreDir, env: env)
            handle.onExit { [weak self] _ in
                Task { @MainActor in await self?.tick() }
            }
            mode = .own(handle)
            state = .starting
        } catch {
            fail("Не удалось запустить ядро: \(error.localizedDescription)")
        }
    }

    func fail(_ message: String) {
        mode = .idle
        clearConnection()
        stopPolling()
        state = .failed(message)
    }

    func clearConnection() {
        port = nil
        token = nil
    }

    // MARK: - Опрос

    func refreshOwn(_ handle: any CoreHandle) async {
        // Файл запуска с мёртвым pid — от прошлого ядра: своё его ещё не переписало
        guard let info = RunFile.read(paths.runFile), pidAlive(info.pid) else { return state = .starting }
        port = info.port
        guard let token = TokenFile.read(paths.tokenFile) else { return state = .starting }
        self.token = token
        let current = generation
        let result = await probe.status(port: info.port, token: token)
        guard current == generation, case .own(let now) = mode, now === handle else { return }
        if case let .ok(phase, online, total, ollama) = result {
            state = .running(port: info.port, phase: phase, devices: (online, total), ollama: ollama)
        } else {
            state = .starting
        }
    }

    func refreshExternal(_ pid: Int32) async {
        guard pidAlive(pid) else {
            mode = .idle
            clearConnection()
            stopPolling()
            return state = .stopped
        }
        // Во время перезапуска чужое ядро переписывает файл — пока его нет, состояние не трогаем
        guard let info = RunFile.read(paths.runFile), info.pid == pid,
              let token = TokenFile.read(paths.tokenFile) else { return }
        let result = await probe.status(port: info.port, token: token)
        guard case .external(let now) = mode, now == pid,
              case let .ok(phase, online, total, ollama) = result else { return }
        port = info.port
        self.token = token
        state = .external(port: info.port, phase: phase, devices: (online, total), ollama: ollama)
    }

    // MARK: - Падения

    /// Своё ядро вышло само. Порт занят прежним ядром (живой pid в файле запуска) —
    /// ждём его выхода и считаем обычным падением; занят чужой программой — сразу ошибка.
    func handleCrash() async {
        mode = .idle
        clearConnection()
        let log = CoreLog.read(paths.logFile, from: logOffset)
        let busyPort = log.conflictPort ?? RunFile.read(paths.runFile)?.port
        if log.portConflict {
            guard let info = RunFile.read(paths.runFile), pidAlive(info.pid) else {
                return fail(portMessage(busyPort))
            }
            state = .starting
            guard await waitForExit(info.pid, generation), case .idle = mode else { return }
        }
        let now = clock()
        crashTimes = crashTimes.filter { now - $0 < Self.crashWindow } + [now]
        if crashTimes.count >= Self.crashLimit {
            return fail(log.portConflict ? portMessage(busyPort) : failureText(log))
        }
        state = .starting
        launchOwn()
    }

    /// Причина падения: строка ERROR/CRITICAL из журнала, иначе последняя строка
    /// stderr (`uv run` мог упасть до Python), иначе последняя строка журнала.
    private func failureText(_ log: CoreLogExcerpt) -> String {
        log.errorLine
            ?? CoreLog.read(paths.stderrLogFile, from: 0).lines.last
            ?? log.lines.last
            ?? "Ядро завершилось, в журнале нет новых записей"
    }

    private func portMessage(_ port: Int?) -> String {
        port.map { "Порт \($0) занят другой программой" } ?? "Порт занят другой программой"
    }

    // MARK: - Цикл опроса

    func ensurePolling() {
        guard autoPoll, pollTask == nil else { return }
        if case .idle = mode { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.tick()
                await self.sleep(Self.pollInterval)
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }
}
