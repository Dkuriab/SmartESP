"""Устройства вывода звука через CoreAudio (ctypes, без внешних программ).

Функции синхронные и быстрые; из асинхронного кода их зовут через поток.
Ошибка CoreAudio — SystemFailure.
"""

import ctypes
from ctypes import POINTER, Structure, byref, c_int32, c_long, c_uint32, c_void_p, create_string_buffer
from typing import Any

from mac_media_mcp.system import SystemFailure

_COREAUDIO = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
_COREFOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

_UTF8 = 0x08000100  # kCFStringEncodingUTF8
_SYSTEM_OBJECT = 1  # kAudioObjectSystemObject
_ELEMENT_MAIN = 0


def _code(text: str) -> int:
    """Четырёхбуквенный код CoreAudio («dev#») как число."""
    return int.from_bytes(text.encode("ascii"), "big")


_DEVICES = _code("dev#")
_DEFAULT_OUTPUT = _code("dOut")
_NAME = _code("lnam")
_STREAMS = _code("stm#")
_SCOPE_GLOBAL = _code("glob")
_SCOPE_OUTPUT = _code("outp")


class _Address(Structure):
    """AudioObjectPropertyAddress."""

    _fields_ = [("selector", c_uint32), ("scope", c_uint32), ("element", c_uint32)]


class _Libraries:
    """Загруженные CoreAudio и CoreFoundation с сигнатурами нужных функций."""

    def __init__(self) -> None:
        audio: Any = ctypes.CDLL(_COREAUDIO)
        found: Any = ctypes.CDLL(_COREFOUNDATION)
        address = POINTER(_Address)
        audio.AudioObjectGetPropertyDataSize.argtypes = [
            c_uint32,
            address,
            c_uint32,
            c_void_p,
            POINTER(c_uint32),
        ]
        audio.AudioObjectGetPropertyDataSize.restype = c_int32
        audio.AudioObjectGetPropertyData.argtypes = [
            c_uint32,
            address,
            c_uint32,
            c_void_p,
            POINTER(c_uint32),
            c_void_p,
        ]
        audio.AudioObjectGetPropertyData.restype = c_int32
        audio.AudioObjectSetPropertyData.argtypes = [
            c_uint32,
            address,
            c_uint32,
            c_void_p,
            c_uint32,
            c_void_p,
        ]
        audio.AudioObjectSetPropertyData.restype = c_int32
        found.CFStringGetLength.argtypes = [c_void_p]
        found.CFStringGetLength.restype = c_long
        found.CFStringGetMaximumSizeForEncoding.argtypes = [c_long, c_uint32]
        found.CFStringGetMaximumSizeForEncoding.restype = c_long
        found.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, c_long, c_uint32]
        found.CFStringGetCString.restype = ctypes.c_bool
        found.CFRelease.argtypes = [c_void_p]
        found.CFRelease.restype = None
        self.audio = audio
        self.found = found


_libraries: _Libraries | None = None


def _libs() -> _Libraries:
    """Библиотеки загружаются при первом обращении (на не-Mac импорт модуля не падает)."""
    global _libraries
    if _libraries is None:
        _libraries = _Libraries()
    return _libraries


def _data_size(object_id: int, address: _Address) -> int:
    size = c_uint32(0)
    status = _libs().audio.AudioObjectGetPropertyDataSize(object_id, byref(address), 0, None, byref(size))
    if status != 0:
        raise SystemFailure("Не получилось узнать устройства звука.")
    return size.value


def _device_ids() -> list[int]:
    address = _Address(_DEVICES, _SCOPE_GLOBAL, _ELEMENT_MAIN)
    size = _data_size(_SYSTEM_OBJECT, address)
    count = size // ctypes.sizeof(c_uint32)
    ids = (c_uint32 * count)()
    io_size = c_uint32(size)
    status = _libs().audio.AudioObjectGetPropertyData(
        _SYSTEM_OBJECT, byref(address), 0, None, byref(io_size), ids
    )
    if status != 0:
        raise SystemFailure("Не получилось узнать устройства звука.")
    return list(ids)[: io_size.value // ctypes.sizeof(c_uint32)]


def _has_output(device_id: int) -> bool:
    try:
        return _data_size(device_id, _Address(_STREAMS, _SCOPE_OUTPUT, _ELEMENT_MAIN)) > 0
    except SystemFailure:
        return False


def _device_name(device_id: int) -> str:
    address = _Address(_NAME, _SCOPE_GLOBAL, _ELEMENT_MAIN)
    string = c_void_p()
    size = c_uint32(ctypes.sizeof(c_void_p))
    libs = _libs()
    status = libs.audio.AudioObjectGetPropertyData(
        device_id, byref(address), 0, None, byref(size), byref(string)
    )
    if status != 0 or not string.value:
        return ""
    try:
        length = libs.found.CFStringGetLength(string)
        capacity = libs.found.CFStringGetMaximumSizeForEncoding(length, _UTF8) + 1
        buffer = create_string_buffer(capacity)
        if not libs.found.CFStringGetCString(string, buffer, capacity, _UTF8):
            return ""
        return buffer.value.decode("utf-8")
    finally:
        libs.found.CFRelease(string)


def output_devices() -> dict[str, int]:
    """Устройства вывода: имя → номер CoreAudio (без устройств без имени)."""
    devices: dict[str, int] = {}
    for device_id in _device_ids():
        if _has_output(device_id):
            name = _device_name(device_id)
            if name:
                devices.setdefault(name, device_id)
    return devices


def default_output_id() -> int:
    """Номер текущего устройства вывода."""
    address = _Address(_DEFAULT_OUTPUT, _SCOPE_GLOBAL, _ELEMENT_MAIN)
    device = c_uint32(0)
    size = c_uint32(ctypes.sizeof(c_uint32))
    status = _libs().audio.AudioObjectGetPropertyData(
        _SYSTEM_OBJECT, byref(address), 0, None, byref(size), byref(device)
    )
    if status != 0:
        raise SystemFailure("Не получилось узнать текущее устройство звука.")
    return device.value


def set_default_output_id(device_id: int) -> None:
    """Делает устройство device_id устройством вывода."""
    address = _Address(_DEFAULT_OUTPUT, _SCOPE_GLOBAL, _ELEMENT_MAIN)
    device = c_uint32(device_id)
    status = _libs().audio.AudioObjectSetPropertyData(
        _SYSTEM_OBJECT, byref(address), 0, None, ctypes.sizeof(c_uint32), byref(device)
    )
    if status != 0:
        raise SystemFailure("Не получилось переключить устройство звука.")
