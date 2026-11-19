"""Запуск: без папки данных — понятная ошибка."""

import pytest

from timers_mcp.server import main


def test_main_without_data_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMARTESP_CONNECTOR_DATA", raising=False)
    with pytest.raises(SystemExit, match="SMARTESP_CONNECTOR_DATA"):
        main()
