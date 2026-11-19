"""Штрихкод товара на фото: EAN-13, EAN-8, UPC-A, UPC-E (библиотека zxing-cpp)."""

from __future__ import annotations

import io

import zxingcpp
from PIL import Image, UnidentifiedImageError

_RETAIL_FORMATS = zxingcpp.BarcodeFormats(
    [
        zxingcpp.BarcodeFormat.EAN13,
        zxingcpp.BarcodeFormat.EAN8,
        zxingcpp.BarcodeFormat.UPCA,
        zxingcpp.BarcodeFormat.UPCE,
    ]
)


def find_barcode(photo: bytes) -> str | None:
    """Ищет штрихкод товара на фото (JPEG/PNG и т. п.).

    Возвращает цифры первого найденного штрихкода; нет штрихкода или это не
    картинка — None. Работа процессорная: из async-кода звать через `asyncio.to_thread`.
    UPC-A zxing-cpp отдаёт как EAN-13 с ведущим нулём.
    """
    try:
        with Image.open(io.BytesIO(photo)) as image:
            found = zxingcpp.read_barcodes(image.convert("L"), formats=_RETAIL_FORMATS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    return found[0].text if found else None
