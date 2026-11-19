"""Сведения о колонках: имена из настроек и последние данные сессий."""

from __future__ import annotations

from dataclasses import dataclass

from smartesp.contracts import DeviceInfo


@dataclass
class _Seen:
    """Что известно о последней сессии колонки."""

    remote: str
    fw: str
    protocol: int
    last_seen: float


class DeviceRegistry:
    """Имена колонок и память о виденных колонках (в том числе уже отключённых)."""

    def __init__(self, names: dict[str, str]) -> None:
        """names — имена колонок по id."""
        self._names = dict(names)
        self._seen: dict[str, _Seen] = {}

    def set_names(self, names: dict[str, str]) -> None:
        """Заменяет имена колонок."""
        self._names = dict(names)

    def name(self, device_id: str) -> str:
        """Имя колонки или сам id."""
        return self._names.get(device_id, device_id)

    def hello(self, device_id: str, remote: str, fw: str, protocol: int, now: float) -> None:
        """Колонка поздоровалась: запоминает адрес, прошивку, версию протокола и время."""
        self._seen[device_id] = _Seen(remote, fw, protocol, now)

    def touch(self, device_id: str, now: float) -> None:
        """Пришёл кадр от колонки: обновляет last_seen."""
        seen = self._seen.get(device_id)
        if seen is not None:
            seen.last_seen = now

    def devices(self, connected: set[str]) -> list[DeviceInfo]:
        """Известные колонки (виденные и из настроек), по имени, затем по id."""
        infos = []
        for device_id in self._names.keys() | self._seen.keys():
            seen = self._seen.get(device_id)
            infos.append(
                DeviceInfo(
                    device_id=device_id,
                    name=self.name(device_id),
                    connected=device_id in connected,
                    remote=seen.remote if seen else "",
                    fw=seen.fw if seen else "",
                    last_seen=seen.last_seen if seen else None,
                    protocol=seen.protocol if seen else 0,
                )
            )
        return sorted(infos, key=lambda i: (i.name, i.device_id))
