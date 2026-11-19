/// Состояние ядра для меню и окна.
public enum CoreState: Equatable, Sendable {
    /// Ядро не запущено.
    case stopped
    /// Процесс запущен, но API ещё не ответил (нет файла запуска или токена).
    case starting
    /// Своё ядро отвечает; `phase` — `warming`, `ready` или `stopping`,
    /// `devices` — онлайн и всего, `ollama` — доступна ли Ollama.
    case running(port: Int, phase: String, devices: (online: Int, total: Int), ollama: Bool)
    /// Ядро запущено не приложением; поля как у `running`.
    case external(port: Int, phase: String, devices: (online: Int, total: Int), ollama: Bool)
    /// Своё ядро останавливается.
    case stopping
    /// Ошибка с текстом для меню; выход из неё — «Перезапустить ядро».
    case failed(String)
    /// macOS спрашивает доступ к защищённой папке с репозиторием (`folder` — её русское имя).
    case waitingForAccess(folder: String)
    /// Ядро после запуска долго молчит, а репозиторий в защищённой папке: возможно,
    /// `uv` ждёт ответа на запрос доступа, а возможно, ещё ставит зависимости.
    case silentStart(folder: String)
    /// В доступе к папке отказано; «Перезапустить ядро» проверяет заново.
    case accessDenied(folder: String)

    public static func == (lhs: CoreState, rhs: CoreState) -> Bool {
        switch (lhs, rhs) {
        case (.stopped, .stopped), (.starting, .starting), (.stopping, .stopping):
            return true
        case let (.running(p1, s1, d1, o1), .running(p2, s2, d2, o2)),
             let (.external(p1, s1, d1, o1), .external(p2, s2, d2, o2)):
            return p1 == p2 && s1 == s2 && d1 == d2 && o1 == o2
        case let (.failed(a), .failed(b)),
             let (.waitingForAccess(a), .waitingForAccess(b)),
             let (.silentStart(a), .silentStart(b)),
             let (.accessDenied(a), .accessDenied(b)):
            return a == b
        default:
            return false
        }
    }
}
