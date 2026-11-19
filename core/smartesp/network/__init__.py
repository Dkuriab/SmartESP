"""Модуль сети исполнителей: передача задачи от одного исполнителя другому."""

from .names import named_target
from .network import ExecutorNetwork, Member
from .rules import DELEGATE_TOOL, Target, delegate_rule, delegate_tool

__all__ = [
    "DELEGATE_TOOL",
    "ExecutorNetwork",
    "Member",
    "Target",
    "delegate_rule",
    "delegate_tool",
    "named_target",
]
