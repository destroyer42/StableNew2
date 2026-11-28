"""QR symbols for the application (PHONE-CORE PP-1): the vendored encoder behind one function.

It only computes the grid. Whoever draws it decides where; a pairing link is drawn on screen and never saved or logged.
"""

from __future__ import annotations

from src.utils.vendor.qrcodegen import QrCode


def qr_modules(text: str) -> tuple[tuple[bool, ...], ...]:
    """The modules of ``text``'s symbol, row by row (``True`` is dark), without the quiet zone.

    Raises ``ValueError`` when the text does not fit. The message never repeats the text, which may hold a pairing code.
    """

    try:
        symbol = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    except ValueError:
        raise ValueError("The text does not fit a QR code.") from None
    size = symbol.get_size()
    return tuple(tuple(symbol.get_module(x, y) for x in range(size)) for y in range(size))
