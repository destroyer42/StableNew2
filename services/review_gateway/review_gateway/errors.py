from __future__ import annotations


class GatewayError(Exception):
    """A refused request. ``code`` is the only detail returned to the caller."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
