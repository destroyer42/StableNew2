"""Strict validation of ``stablenew.review-gateway-sync.v1`` payloads against the one schema file."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

SCHEMA_VERSION = "stablenew.review-gateway-sync.v1"
SCHEMA_FILE_NAME = f"{SCHEMA_VERSION}.json"


class ContractError(Exception):
    """A request that does not meet the contract. ``code`` is safe to return to the caller."""

    def __init__(self, code: str = "invalid_payload", detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def _pattern(validator, pattern, instance, schema):
    """``pattern`` with whole-string meaning: Python's ``$`` would otherwise accept a trailing newline."""

    if validator.is_type(instance, "string") and (
        instance.endswith("\n") or not re.search(pattern, instance)
    ):
        yield ValidationError(f"value does not match {pattern!r}")


_FORMATS = FormatChecker(formats=())


@_FORMATS.checks("date-time", raises=ValueError)
def _is_date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if "T" not in value.upper():
        return False
    return datetime.fromisoformat(value).tzinfo is not None


@_FORMATS.checks("uuid", raises=ValueError)
def _is_uuid(value: object) -> bool:
    return not isinstance(value, str) or str(uuid.UUID(value)) == value.lower()


_Validator = validators.extend(Draft202012Validator, {"pattern": _pattern})


def _refuse_constant(value: str) -> None:
    raise ValueError(f"{value} is not JSON")


class Contract:
    def __init__(self, schema_file: Path) -> None:
        schema = json.loads(Path(schema_file).read_text(encoding="utf-8"))
        if schema["$defs"]["schema_version"]["const"] != SCHEMA_VERSION:
            raise ValueError(f"{schema_file} is not the {SCHEMA_VERSION} schema")
        self._definitions = schema["$defs"]
        self._validators: dict[str, Any] = {}

    def validate(self, name: str, payload: object) -> None:
        """Check ``payload`` against the schema's ``$defs/<name>``."""

        validator = self._validators.get(name)
        if validator is None:
            if name not in self._definitions:
                raise KeyError(name)
            validator = _Validator(
                {"$defs": self._definitions, "$ref": f"#/$defs/{name}"}, format_checker=_FORMATS
            )
            self._validators[name] = validator
        error = next(validator.iter_errors(payload), None)
        if error is not None:
            # The path is safe to log; the value (which may be prompt text) is never included.
            raise ContractError(
                detail=f"{name}: invalid at {'/'.join(map(str, error.path)) or '.'}"
            )

    @staticmethod
    def parse(body: bytes) -> dict[str, Any]:
        """Decode one strict JSON object: UTF-8, no NaN/Infinity, no unpaired surrogates."""

        try:
            value = json.loads(body.decode("utf-8"), parse_constant=_refuse_constant)
            json.dumps(value, ensure_ascii=False).encode("utf-8")
        except (UnicodeError, ValueError, RecursionError) as error:
            raise ContractError("invalid_json") from error
        if not isinstance(value, dict):
            raise ContractError("invalid_json")
        return value
