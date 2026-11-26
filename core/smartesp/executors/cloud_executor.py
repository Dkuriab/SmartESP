"""Исполнитель на модели облачного сервиса с OpenAI-совместимым API (OpenRouter и т. п.)."""

from typing import Any

import httpx

from smartesp.contracts import CLOUD_MODEL_PREFIX, ExecutorError, Reasoning

from .openai_chat import OpenAIChatExecutor

# понятный текст по коду ответа сервиса ({s} — имя сервиса, {m} — модель)
_STATUS_TEXT = {
    401: "{s} не принял ключ — проверьте его в настройках ядра",
    402: "на счёте {s} закончились деньги",
    403: "{s} отказал в запросе (ограничение ключа или модерация)",
    404: "у {s} нет модели «{m}» или она не умеет инструменты",
    408: "{s} не дождался ответа модели",
    429: "{s}: слишком много запросов, подождите",
    502: "модель «{m}» у {s} сейчас недоступна",
    503: "у {s} нет свободного поставщика для модели «{m}»",
}


def effort(reasoning: Reasoning) -> str:
    """reasoning.effort для сервиса: «off» — «none» (не рассуждать), иначе тот же уровень."""
    return "none" if reasoning == "off" else reasoning


class CloudExecutor(OpenAIChatExecutor):
    """Отвечает моделью облачного сервиса потоком chat/completions (SSE)."""

    model_prefix = CLOUD_MODEL_PREFIX

    def __init__(
        self,
        model: str,
        system_prompt: str,
        base_url: str,
        api_key: str,
        *,
        id: str = "",  # noqa: A002 — имя поля задано контрактом Identified
        reasoning: Reasoning = "off",
        service: str = "OpenRouter",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """model — id модели сервиса; base_url — адрес API (…/api/v1); api_key — ключ сервиса;
        service — имя сервиса для текстов ошибок; client — свой HTTP-клиент (тесты).
        """
        url = base_url.rstrip("/") + "/chat/completions"
        super().__init__(
            model, system_prompt, url, api_key, id=id, reasoning=reasoning, service=service, client=client
        )

    async def warm_up(self) -> None:
        """Проверяет только, что ключ задан (запрос к модели стоил бы денег); нет — ExecutorError."""
        self._check_ready()

    def _check_ready(self) -> None:
        if not self._key:
            raise ExecutorError(f"Нет ключа {self._service}: введите его в настройках ядра")

    def _reasoning_fields(self) -> dict[str, Any]:
        return {"reasoning": {"effort": effort(self._reasoning), "exclude": True}}

    def _error_text(self, status: int, detail: str) -> str:
        text = _STATUS_TEXT.get(status, "{s} ответил ошибкой " + str(status))
        return text.format(s=self._service, m=self._model)
