"""Раздача собранного интерфейса."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

NOT_BUILT_HTML = (
    "<!doctype html><html lang='ru'><meta charset='utf-8'><title>SmartESP</title>"
    "<body><p>Интерфейс не собран: <code>cd ui &amp;&amp; npm ci &amp;&amp; npm run build</code></p>"
    "</body></html>"
)


def mount_ui(app: FastAPI, ui_dir: Path) -> None:
    """Раздаёт `ui_dir` на `/`, а без сборки — страницу с командой сборки.

    Вызывать после подключения роутера API, чтобы маршруты /api побеждали.
    """
    if (ui_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")
        return

    @app.get("/", include_in_schema=False)
    def not_built() -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        return HTMLResponse(NOT_BUILT_HTML)
