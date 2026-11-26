"""Исполнитель на модели локального сервера LM Studio (OpenAI-совместимый /v1/chat/completions).

Рассуждение: уровень low/medium/high — поле reasoning_effort, «off» — поле не шлётся; текст
рассуждения в ответ не попадает (reasoning_content не читается, <think>…</think> вырезается).
Время удержания: keep_alive исполнителя → ttl в секундах (LM Studio применяет его к модели,
загруженной по запросу). Прогрев — запрос на один токен: LM Studio сам загружает модель.
"""

import re
from typing import Any

import httpx

from smartesp.contracts import LMSTUDIO_MODEL_PREFIX, ExecutorError, Reasoning

from .openai_chat import OpenAIChatExecutor, TextFilter
from .openai_format import error_detail
from .think_filter import ThinkFilter

SERVICE = "LM Studio"
DEFAULT_URL = "http://localhost:1234"
_DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
# (слова в тексте ошибки сервера, понятный текст; {m} — модель): первое совпадение
_DETAIL_TEXT = (
    (
        ("no models loaded", "not loaded"),
        "модель «{m}» не загружена в LM Studio: загрузите её или включите JIT-загрузку",
    ),
    (("not found", "model_not_found", "no model"), "В LM Studio нет модели «{m}»: скачайте её в LM Studio"),
    (("tool",), "модель «{m}» в LM Studio не умеет инструменты — выберите другую модель"),
)


def server_url(base_url: str) -> str:
    """Адрес сервера без «/» и «/v1» в конце (владелец мог ввести адрес OpenAI-совместимого API)."""
    url = (base_url.strip() or DEFAULT_URL).rstrip("/")
    return url.removesuffix("/v1").rstrip("/")


def ttl_seconds(keep_alive: str) -> int | None:
    """keep_alive в стиле Ollama («24h», «30m», «1h30m», «90s», «3600») → секунды; «-1», «0» и
    непонятное — None (ttl не шлём: модель держит сам LM Studio)."""
    text = keep_alive.strip()
    if text.isdigit():
        seconds = int(text)
    elif text and (match := _DURATION.fullmatch(text)):
        hours, minutes, secs = (int(g or 0) for g in match.groups())
        seconds = hours * 3600 + minutes * 60 + secs
    else:
        return None
    return seconds or None


class LmStudioExecutor(OpenAIChatExecutor):
    """Отвечает моделью LM Studio потоком chat/completions (SSE) с инструментами."""

    model_prefix = LMSTUDIO_MODEL_PREFIX

    def __init__(
        self,
        model: str,
        system_prompt: str,
        base_url: str,
        api_key: str = "",
        *,
        id: str = "",  # noqa: A002 — имя поля задано контрактом Identified
        reasoning: Reasoning = "off",
        keep_alive: str = "24h",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """model — id модели в LM Studio; base_url — адрес сервера (http://localhost:1234);
        api_key — ключ, если в LM Studio включена проверка (пусто — без ключа);
        keep_alive — сколько держать модель (→ ttl); client — свой HTTP-клиент (тесты).
        """
        self._server = server_url(base_url)
        self._ttl = ttl_seconds(keep_alive)
        url = self._server + "/v1/chat/completions"
        super().__init__(
            model, system_prompt, url, api_key, id=id, reasoning=reasoning, service=SERVICE, client=client
        )

    async def warm_up(self) -> None:
        """Загружает модель запросом на один токен (без потока и инструментов); сбой — ExecutorError."""
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": "Привет"}],
            "max_tokens": 1,
            "stream": False,
            **self._extra_fields(),
        }
        try:
            response = await self._http().post(self._url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise self._connect_error(exc) from exc
        if response.status_code != httpx.codes.OK:
            detail = error_detail(response.content)
            raise ExecutorError(f"{self._error_text(response.status_code, detail)}: {detail}")

    def _reasoning_fields(self) -> dict[str, Any]:
        return {} if self._reasoning == "off" else {"reasoning_effort": self._reasoning}

    def _extra_fields(self) -> dict[str, Any]:
        return {} if self._ttl is None else {"ttl": self._ttl}

    def _text_filter(self) -> TextFilter:
        return ThinkFilter()

    def _error_text(self, status: int, detail: str) -> str:
        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            return "LM Studio не принял ключ — проверьте ключ в настройках ядра"
        lowered = detail.lower()
        for words, text in _DETAIL_TEXT:
            if any(word in lowered for word in words):
                return text.format(m=self._model)
        if status == httpx.codes.NOT_FOUND:
            return _DETAIL_TEXT[1][1].format(m=self._model)
        return f"LM Studio ответил ошибкой {status}"

    def _connect_error(self, exc: httpx.HTTPError) -> ExecutorError:
        return connect_error(self._server, exc)


def connect_error(server: str, exc: httpx.HTTPError) -> ExecutorError:
    """Понятная ошибка связи с сервером LM Studio по адресу server."""
    if isinstance(exc, httpx.ConnectError):
        return ExecutorError(
            f"Сервер LM Studio не запущен по адресу {server}: запустите его в LM Studio "
            "(вкладка Developer → Start Server) или проверьте адрес в настройках ядра"
        )
    if isinstance(exc, httpx.TimeoutException):
        return ExecutorError(f"LM Studio по адресу {server} не ответил вовремя")
    return ExecutorError(f"Нет связи с LM Studio по адресу {server}: {type(exc).__name__}")
