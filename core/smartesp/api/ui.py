"""Раздача собранного интерфейса."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

NOT_BUILT_HTML = (
    "<!doctype html><html lang='ru'><meta charset='utf-8'><title>SmartESP</title>"
    "<body><p>Интерфейс не собран: <code>cd ui &amp;&amp; npm ci &amp;&amp; npm run build</code></p>"
    "</body></html>"
)


class UiFiles(StaticFiles):
    """Файлы сборки; страницы .html — с Cache-Control: no-cache.

    Без этого окно приложения (WKWebView) по эвристике кэша показывало старый index.html после
    обновления — новой вкладки не видно. Файлы сборки с хешем в имени кэшируются как обычно.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_ui(app: FastAPI, ui_dir: Path) -> None:
    """Раздаёт `ui_dir` на `/`, а без сборки — страницу с командой сборки.

    Вызывать после подключения ВСЕХ остальных маршрутов (API, /device и т. д.):
    монтирование на `/` перехватывает всё, что объявлено позже.
    """
    if (ui_dir / "index.html").is_file():
        app.mount("/", UiFiles(directory=ui_dir, html=True), name="ui")
        return

    @app.get("/", include_in_schema=False)
    def not_built() -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        return HTMLResponse(NOT_BUILT_HTML)
