"""Общие заготовки тестов: поддельный запуск Claude, часы, клиент в памяти."""

import asyncio
import stat
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import LoggingMessageNotificationParams, RequestParamsMeta, TextContent

from claude_tasks_mcp.runner import RunResult

START = datetime(2026, 11, 19, 14, 0, tzinfo=timezone(timedelta(hours=3)))


class FakeClock:
    """Часы, которые идут только по `advance`."""

    def __init__(self) -> None:
        self.current = START

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@dataclass
class Call:
    """Один запуск поддельного Claude: задача, папка и как он закончится."""

    prompt: str
    folder: Path
    done: asyncio.Future[RunResult] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    cancelled: bool = False


class FakeRunner:
    """Вместо настоящего `claude`: запуск висит, пока тест не завершит его через `finish`."""

    def __init__(self) -> None:
        self.calls: list[Call] = []

    async def __call__(self, prompt: str, folder: Path) -> RunResult:
        call = Call(prompt, folder)
        self.calls.append(call)
        try:
            return await call.done
        except asyncio.CancelledError:
            call.cancelled = True
            raise

    async def started(self, count: int) -> list[Call]:
        """Ждёт, пока запусков станет `count` (предел — защита от зависания)."""
        with anyio.fail_after(5):
            while len(self.calls) < count:
                await anyio.sleep(0.001)
        return self.calls

    def finish(self, index: int, ok: bool, text: str) -> None:
        """Завершает запуск номер `index` с итогом."""
        self.calls[index].done.set_result(RunResult(ok, text))


class Session:
    """Клиент в памяти и полученные им объявления."""

    def __init__(self, client: Client, inbox: MemoryObjectReceiveStream[dict[str, Any]]) -> None:
        self.client = client
        self._inbox = inbox

    async def call(self, tool: str, person: str | None = None, **args: Any) -> str:
        """Вызывает инструмент и возвращает текст ответа (и ошибки тоже)."""
        meta = RequestParamsMeta(person=person) if person is not None else None
        result = await self.client.call_tool(tool, args, meta=meta)
        block = result.content[0]
        assert isinstance(block, TextContent)
        return block.text

    async def announce(self) -> dict[str, Any]:
        """Ждёт следующее объявление."""
        with anyio.fail_after(5):
            return await self._inbox.receive()

    def pending(self) -> list[dict[str, Any]]:
        """Объявления, уже пришедшие и ещё не прочитанные."""
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(self._inbox.receive_nowait())
            except anyio.WouldBlock:
                return items


@asynccontextmanager
async def connect(server: MCPServer[Any]) -> AsyncGenerator[Session]:
    """Подключает клиента в памяти (рукопожатие, как по stdio) и ловит объявления."""
    send, receive = anyio.create_memory_object_stream[dict[str, Any]](100)

    async def on_log(params: LoggingMessageNotificationParams) -> None:
        if params.logger == "smartesp":
            await send.send(params.data)

    async with send, receive, Client(server, mode="legacy", logging_callback=on_log) as client:
        yield Session(client, receive)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def folders(tmp_path: Path) -> tuple[tuple[str, Path], ...]:
    """Две разрешённые папки: smartesp (по умолчанию) и notes."""
    for name in ("repo", "notes", "secret"):
        (tmp_path / name).mkdir()
    real = tmp_path.resolve()
    return (("smartesp", real / "repo"), ("notes", real / "notes"))


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """Исполняемый файл `claude`, который запускает tests/fake_claude.py этим же Python.

    Журнал — `tmp_path/log.json`, режим — в файле `tmp_path/mode` (нет файла — ok).
    """
    script = Path(__file__).with_name("fake_claude.py")
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        "#!/bin/sh\n"
        f'export FAKE_CLAUDE_LOG="{tmp_path / "log.json"}" FAKE_CLAUDE_MODE_FILE="{tmp_path / "mode"}"\n'
        f'exec "{sys.executable}" "{script}" "$@"\n'
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return binary
