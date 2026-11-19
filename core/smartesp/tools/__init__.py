"""MCP-хаб: коннекторы-подпроцессы и их инструменты для исполнителей."""

from .hub import McpHub
from .specs import ConnectorSpec, ConnectorState

__all__ = ["ConnectorSpec", "ConnectorState", "McpHub"]
