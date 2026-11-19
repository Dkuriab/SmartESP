"""Системные медиа-клавиши: событие NX «system defined» (subtype 8) через Quartz.

Так же нажимает клавиши клавиатура Mac, поэтому работает с любым плеером.
Без разрешения «Универсальный доступ» macOS молча выбрасывает такие события —
поэтому сначала проверка без запроса (CGPreflightPostEventAccess).
"""

from typing import Any

from mac_media_mcp.system import MediaKey, PermissionDenied

# Коды из IOKit ev_keymap.h; FAST/REWIND шлют F9/F7 клавиатуры Apple.
_NX_KEYTYPE: dict[MediaKey, int] = {"play_pause": 16, "next": 19, "previous": 20}
_NX_SYSDEFINED = 14  # NSEventTypeSystemDefined
_NX_SUBTYPE_AUX_CONTROL_BUTTONS = 8
_KEY_DOWN = 0xA
_KEY_UP = 0xB


def event_data(key: MediaKey, down: bool) -> tuple[int, int]:
    """Флаги и data1 события клавиши key: нажатие (down) или отпускание."""
    state = _KEY_DOWN if down else _KEY_UP
    return state << 8, (_NX_KEYTYPE[key] << 16) | (state << 8)


def press(key: MediaKey) -> None:
    """Нажимает и отпускает медиа-клавишу key; нет разрешения — PermissionDenied("keys")."""
    import AppKit  # pyright: ignore[reportMissingTypeStubs]
    import Quartz  # pyright: ignore[reportMissingTypeStubs]

    quartz: Any = Quartz
    appkit: Any = AppKit
    new_event = appkit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_  # noqa: E501
    if not quartz.CGPreflightPostEventAccess():
        raise PermissionDenied("keys")
    for down in (True, False):
        flags, data1 = event_data(key, down)
        event = new_event(
            _NX_SYSDEFINED, (0, 0), flags, 0, 0, None, _NX_SUBTYPE_AUX_CONTROL_BUTTONS, data1, -1
        )
        quartz.CGEventPost(quartz.kCGHIDEventTap, event.CGEvent())
