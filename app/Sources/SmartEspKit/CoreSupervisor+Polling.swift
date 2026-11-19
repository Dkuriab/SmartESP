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

    /// Проверяет доступ к папке ядра. Пока проверка висит дольше `accessPromptDelay`
    /// (macOS спрашивает пользователя) — состояние `waitingForAccess`.
    /// - Returns: `true`, если доступ есть и можно запускать.
    func checkAccess(_ current: Int) async -> Bool {
        let check = access.check(paths.coreDir)
        let started = clock()
        while check.result == nil {
            guard current == generation else { return false }
            if clock() - started >= Self.accessPromptDelay { state = .waitingForAccess(folder: folderName) }
            await sleep(Self.waitStep)
            await Task.yield()
        }
        guard current == generation, let result = check.result else { return false }
        switch result {
        case .granted:
            return true
        case .denied:
            fail(nil)
            state = .accessDenied(folder: folderName)
        case let .failed(message):
            fail(message)
        }
        return false
    }

    /// Русское имя защищённой папки с репозиторием, иначе имя самой папки репозитория.
    var folderName: String {
        protectedFolderName(of: paths.repo, home: home) ?? paths.repo.lastPathComponent
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
            launchedAt = clock()
            probeFailures = 0
            state = .starting
        } catch {
            fail("Не удалось запустить ядро: \(error.localizedDescription)")
        }
    }

    /// Переход в ошибку: надзор прекращается. `nil` — состояние выставит вызывающий.
    func fail(_ message: String?) {
        mode = .idle
        clearConnection()
        stopPolling()
        if let message { state = .failed(message) }
    }

    func clearConnection() {
        port = nil
        token = nil
    }

    // MARK: - Опрос

    func refreshOwn(_ handle: any CoreHandle) async {
        // Файл запуска с мёртвым pid — от прошлого ядра: своё его ещё не переписало
        guard let info = RunFile.read(paths.runFile), pidAlive(info.pid) else {
            return await refreshWithoutRunFile(handle)
        }
        port = info.port
        guard let token = TokenFile.read(paths.tokenFile) else { return state = .starting }
        self.token = token
        let current = generation
        let result = await probe.status(port: info.port, token: token)
        guard current == generation, case .own(let now) = mode, now === handle else { return }
        applyOwnStatus(result, port: info.port)
    }

    /// Ответ `status` своего ядра. Неудача при живом ядре сбрасывает `running`
    /// только после `probeFailureLimit` неудач подряд — иначе окно мигало бы заглушкой.
    private func applyOwnStatus(_ result: ProbeResult, port: Int) {
        if case let .ok(phase, online, total, ollama) = result {
            probeFailures = 0
            state = .running(port: port, phase: phase, devices: (online, total), ollama: ollama)
            return
        }
        probeFailures += 1
        if case .running = state, probeFailures < Self.probeFailureLimit { return }
        state = .starting
    }

    /// Файла запуска нет или его pid мёртв. Файл пропал (удалили папку данных), а ядро
    /// отвечает по прежним порту и токену — остаёмся в `running`; иначе сразу `starting`.
    private func refreshWithoutRunFile(_ handle: any CoreHandle) async {
        if RunFile.read(paths.runFile) == nil, case .running = state, let port, let token {
            let current = generation
            let result = await probe.status(port: port, token: token)
            guard current == generation, case .own(let now) = mode, now === handle else { return }
            if case .ok = result { return applyOwnStatus(result, port: port) }
        }
        probeFailures = 0
        state = silentStartState()
    }

    /// Ядро ещё не написало файл запуска. Если оно молчит дольше `silentStartLimit`
    /// (ни stderr, ни новых строк журнала), а репозиторий в защищённой папке, —
    /// возможно, `uv` ждёт ответа на запрос доступа (например, после пересборки)
    /// или ещё молча ставит зависимости.
    private func silentStartState() -> CoreState {
        guard clock() - launchedAt >= Self.silentStartLimit,
              let folder = protectedFolderName(of: paths.repo, home: home),
              CoreLog.size(paths.stderrLogFile) == 0,
              CoreLog.size(paths.logFile) == logOffset else { return .starting }
        return .silentStart(folder: folder)
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
