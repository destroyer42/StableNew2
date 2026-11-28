"""PHONE-CORE PP-1: the QR encoder behind the pairing dialog. The link is a placeholder."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.utils.qr_code import qr_modules
from src.utils.vendor import qrcodegen

LINK = "https://review.example.test/#/pair/ABCD-EFGH"
_FINDER = [
    "1111111",
    "1000001",
    "1011101",
    "1011101",
    "1011101",
    "1000001",
    "1111111",
]


def test_the_vendored_encoder_is_the_reviewed_file():
    data = Path(qrcodegen.__file__).read_bytes()

    assert hashlib.sha256(data).hexdigest() == (
        "d09f22750a8d5adfb1643e64c5cd7071b8f02c1d04858f814ca9a7cc6f1f0b23"
    ), "see src/utils/vendor/README.md"
    assert b"Copyright (c) Project Nayuki. (MIT License)" in data


def test_a_text_that_does_not_fit_is_refused_without_being_repeated():
    secret = "ABCD-EFGH" * 400

    with pytest.raises(ValueError) as refused:
        qr_modules(secret)

    assert "ABCD" not in str(refused.value) and refused.value.__cause__ is None


def test_the_grid_is_a_square_qr_symbol_with_its_three_finder_patterns():
    grid = qr_modules(LINK)
    size = len(grid)
    assert size >= 21 and (size - 17) % 4 == 0
    assert all(len(row) == size for row in grid)
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        found = [
            "".join("1" if grid[top + row][left + column] else "0" for column in range(7))
            for row in range(7)
        ]
        assert found == _FINDER


@pytest.mark.parametrize(
    "text",
    [
        LINK,
        "https://stablenew-review.tail0000.example.test:8443/#/pair/2345-6789",
        "https://" + "a" * 60 + "." + "b" * 60 + ".example.test/#/pair/ZZZZ-ZZZZ",
    ],
)
def test_a_standard_reader_reads_the_link_back(text):
    cv2 = pytest.importorskip("cv2")  # an optional extra; skipped where it is not installed
    numpy = pytest.importorskip("numpy")

    grid = qr_modules(text)
    pixels = numpy.where(numpy.array(grid), 0, 255).astype(numpy.uint8)
    pixels = numpy.pad(pixels, 4, constant_values=255).repeat(8, axis=0).repeat(8, axis=1)

    # The ArUco-based reader: OpenCV's older QRCodeDetector misses some valid symbols.
    if not hasattr(cv2, "QRCodeDetectorAruco"):
        pytest.skip("this OpenCV is too old to be a trustworthy reader")
    decoded, _points, _straight = cv2.QRCodeDetectorAruco().detectAndDecode(pixels)

    assert decoded == text
