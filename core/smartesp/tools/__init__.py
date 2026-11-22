"""MCP-хаб: коннекторы-подпроцессы и их инструменты для исполнителей."""

from smartesp.contracts import ConnectorState

from .hub import McpHub
from .person import with_person
from .specs import ConnectorSpec

__all__ = ["ConnectorSpec", "ConnectorState", "McpHub", "with_person"]
