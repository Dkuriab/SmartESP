"""Модуль сети исполнителей: передача задачи от одного исполнителя другому."""

from .build import (
    MemberSpec,
    NetworkPrompts,
    active_targets,
    build_network,
    member_prompts,
    with_stage_hints,
)
from .names import named_target
from .network import ExecutorNetwork, Member
from .rules import DELEGATE_TOOL, Target, delegate_rule, delegate_tool

__all__ = [
    "DELEGATE_TOOL",
    "ExecutorNetwork",
    "Member",
    "MemberSpec",
    "NetworkPrompts",
    "Target",
    "active_targets",
    "build_network",
    "delegate_rule",
    "delegate_tool",
    "member_prompts",
    "named_target",
    "with_stage_hints",
]
