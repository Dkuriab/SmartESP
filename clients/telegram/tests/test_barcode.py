"""Распознавание штрихкода на сгенерированных картинках."""

import io

import pytest
import zxingcpp
from PIL import Image

from telegram_bot.barcode import find_barcode


def barcode_photo(code: str, fmt: zxingcpp.BarcodeFormat, *, image_format: str = "JPEG") -> bytes:
    """Рисует штрихкод писателем zxing-cpp и кладёт его на «фото» побольше."""
    raw = memoryview(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(code, fmt), scale=3))
    assert raw.shape is not None
    height, width = raw.shape[0], raw.shape[1]
    symbol = Image.frombytes("L", (width, height), raw.tobytes())
    photo = Image.new("RGB", (width + 200, height + 300), (235, 230, 220))
    photo.paste(symbol.convert("RGB"), (100, 150))
    out = io.BytesIO()
    photo.save(out, image_format)
    return out.getvalue()


@pytest.mark.parametrize(
    ("code", "fmt", "expected"),
    [
        ("4601234567893", zxingcpp.BarcodeFormat.EAN13, "4601234567893"),
        ("96385074", zxingcpp.BarcodeFormat.EAN8, "96385074"),
        # UPC-A читается как EAN-13 с ведущим нулём — так его знает Open Food Facts
        ("036000291452", zxingcpp.BarcodeFormat.UPCA, "0036000291452"),
    ],
)
def test_reads_retail_barcodes_from_jpeg(code: str, fmt: zxingcpp.BarcodeFormat, expected: str) -> None:
    assert find_barcode(barcode_photo(code, fmt)) == expected


def test_reads_png() -> None:
    photo = barcode_photo("4601234567893", zxingcpp.BarcodeFormat.EAN13, image_format="PNG")
    assert find_barcode(photo) == "4601234567893"


def test_rotated_photo() -> None:
    photo = Image.open(io.BytesIO(barcode_photo("4601234567893", zxingcpp.BarcodeFormat.EAN13)))
    out = io.BytesIO()
    photo.rotate(90, expand=True).save(out, "JPEG")
    assert find_barcode(out.getvalue()) == "4601234567893"


def test_no_barcode_on_blank_photo() -> None:
    out = io.BytesIO()
    Image.new("RGB", (640, 480), (255, 255, 255)).save(out, "JPEG")
    assert find_barcode(out.getvalue()) is None


def test_qr_code_is_not_a_product_barcode() -> None:
    assert find_barcode(barcode_photo("https://example.org", zxingcpp.BarcodeFormat.QRCode)) is None


def test_not_an_image() -> None:
    assert find_barcode(b"definitely not a picture") is None
