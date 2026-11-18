"""Связка ядра (аналог SmartEsp.ino): реестры реализаций, запуск, остановка и перезапуск.

Своей логики здесь нет. Сборка частей и порядок прогрева и остановки — в wiring.py.
Запуск: python -m smartesp [--parent-watch] [--openapi PATH].
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import os
import sys
import tomllib
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from smartesp.api import load_or_create_token
from smartesp.config import (
    Config,
    ConfigFile,
    ExecutorConfig,
    StageConfig,
    SttConfig,
    data_dir,
)
from smartesp.contracts import Executor, SpeechToText, Stage, TextToSpeech
from smartesp.executors import OllamaExecutor, list_models, loaded_models
from smartesp.lifecycle import GracefulServer, watch_parent
from smartesp.stages import WhisperDetect
from smartesp.stt import MlxWhisperSTT
from smartesp.tts import PiperTTS, SileroTTS, VoskTTS
from smartesp.wiring import Kinds, Ollama, StartupError, assemble, check_kinds, stop

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 5
GRACE_S = 2  # uvicorn после нашей остановки ждёт соединения API не дольше этого
PACKAGE = "smartesp-core"
UI_DIR = Path(__file__).resolve().parents[2] / "ui" / "dist"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

logger = logging.getLogger("smartesp")

STT_KINDS: dict[str, Callable[[SttConfig], SpeechToText]] = {
    "mlx_whisper": lambda c: MlxWhisperSTT(c.model, c.language),
}
# (путь голоса, голос) → синтез; путь и скачивание — забота менеджера голосов
TTS_KINDS: dict[str, Callable[[Path, str], TextToSpeech]] = {
    "piper": lambda path, voice: PiperTTS(path),
    "silero": lambda path, voice: SileroTTS(path, voice),
    "vosk": lambda path, voice: VoskTTS(path, voice),
}
EXECUTOR_KINDS: dict[str, Callable[[ExecutorConfig], Executor]] = {
    "ollama": lambda c: OllamaExecutor(c.model, c.system_prompt, c.keep_alive),
}
STAGE_KINDS: dict[str, Callable[[StageConfig], Stage]] = {
    "whisper_detect": lambda c: WhisperDetect(),
}
KINDS = Kinds(STT_KINDS, TTS_KINDS, EXECUTOR_KINDS, STAGE_KINDS)
OLLAMA = Ollama(list_models, loaded_models)


def _setup_logging(logs: Path) -> None:
    """Журнал в консоль и в logs/core.log (5 файлов по 1 МБ)."""
    logs.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)
    console = logging.StreamHandler()
    file = RotatingFileHandler(
        logs / "core.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (console, file):
        handler.setFormatter(formatter)
        root.addHandler(handler)


def _flush_logs() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def _version() -> str:
    """Версия ядра: из метаданных пакета, а в виртуальном проекте uv — из pyproject.toml."""
    try:
        return version(PACKAGE)
    except PackageNotFoundError:
        with PYPROJECT.open("rb") as file:
            return str(tomllib.load(file)["project"]["version"])


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="smartesp", description="Ядро SmartESP")
    parser.add_argument(
        "--parent-watch", action="store_true", help="остановиться, когда родитель закроет stdin"
    )
    parser.add_argument("--openapi", type=Path, metavar="PATH", help="записать схему OpenAPI и выйти")
    return parser.parse_args(argv)


def _write_openapi(path: Path) -> None:
    """Схема API настоящего роутера; части не греются, файлы в папке данных не пишутся."""
    home = data_dir()
    parts = assemble(
        ConfigFile(home / "config.yaml"),
        Config(),
        home,
        KINDS,
        OLLAMA,
        version=_version(),
        token="",
        ui_dir=UI_DIR,
    )
    path.write_text(json.dumps(parts.app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")


async def _serve(store: ConfigFile, config: Config, home: Path, parent_watch: bool) -> bool:
    """Сервер сразу, прогрев в фоне, работа до остановки. True — просили перезапуск."""
    token = load_or_create_token(home)
    parts = assemble(store, config, home, KINDS, OLLAMA, version=_version(), token=token, ui_dir=UI_DIR)
    host, port = config.server.host, config.server.port
    # log_config=None: uvicorn пишет через корневой журнал (консоль + core.log)
    uv_config = uvicorn.Config(
        parts.app, host=host, port=port, log_config=None, timeout_graceful_shutdown=GRACE_S
    )
    server = GracefulServer(uv_config, functools.partial(stop, parts), on_started=parts.run_file.write)
    server.stop_after(parts.core.wait_restart())
    if parent_watch:
        watch_parent(sys.stdin.buffer, server.request_stop)
    logger.info("Запускаю сервер на %s:%d (/device, /api/v1)", host, port)
    try:
        await server.serve()
    finally:
        parts.run_file.remove()
    return parts.core.restart_requested


def main(
    argv: Sequence[str] | None = None,
    *,
    execv: Callable[[str, list[str]], object] = os.execv,
) -> None:
    """Точка входа: config.yaml → проверка видов → сервер → прогрев в фоне.

    После остановки по просьбе о перезапуске запускает себя заново через execv.
    """
    args = _parse_args(argv)
    if args.openapi is not None:
        _write_openapi(args.openapi)
        return
    home = data_dir()
    _setup_logging(home / "logs")
    store = ConfigFile(home / "config.yaml")
    try:
        config = store.load()
        logger.info("Настройки: %s", home / "config.yaml")
        check_kinds(config, KINDS)
    except (StartupError, ValueError) as error:
        logger.error("Ядро не запущено: %s", error)
        raise SystemExit(f"Ядро не запущено: {error}") from error
    restart = False
    try:
        restart = asyncio.run(_serve(store, config, home, args.parent_watch))
    except KeyboardInterrupt:
        pass
    logger.info("Ядро остановлено")
    if restart:
        logger.info("Перезапуск: %s -m smartesp %s", sys.executable, " ".join(sys.argv[1:]))
        _flush_logs()
        execv(sys.executable, [sys.executable, "-m", "smartesp", *sys.argv[1:]])
