"""Подделка регистратора службы в сети: запоминает публикации, настоящую сеть не трогает."""

from __future__ import annotations

from smartesp.contracts import ServiceRecord


class FakeRegistrar:
    """Одна публикация; общий журнал log — порядок register/close всех регистраторов фабрики."""

    def __init__(self, log: list[tuple[str, ServiceRecord | None]], *, fail: bool = False) -> None:
        self._log = log
        self._fail = fail
        self.record: ServiceRecord | None = None

    async def register(self, record: ServiceRecord) -> None:
        if self._fail:
            raise OSError("сеть недоступна")
        self.record = record
        self._log.append(("register", record))

    async def aclose(self) -> None:
        self._log.append(("close", self.record))


class FakeRegistrars:
    """Фабрика подделок (вызов — новый регистратор); fail — следующие register падают."""

    def __init__(self) -> None:
        self.log: list[tuple[str, ServiceRecord | None]] = []
        self.made: list[FakeRegistrar] = []
        self.fail = False

    def __call__(self) -> FakeRegistrar:
        registrar = FakeRegistrar(self.log, fail=self.fail)
        self.made.append(registrar)
        return registrar

    def published(self) -> list[ServiceRecord]:
        """Записи, опубликованные и ещё не снятые, по порядку публикации."""
        live: list[ServiceRecord] = []
        for action, record in self.log:
            if record is None:
                continue
            if action == "register":
                live.append(record)
            elif record in live:
                live.remove(record)
        return live
