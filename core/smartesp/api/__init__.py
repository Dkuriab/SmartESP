"""HTTP API ядра: роутер v1, токен и раздача интерфейса."""

from .auth import load_or_create_token
from .routes import create_api
from .ui import mount_ui

__all__ = ["create_api", "load_or_create_token", "mount_ui"]
