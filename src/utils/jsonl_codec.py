"""Unified JSONL codec used by history/queue/diagnostics persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

JsonObject = dict[str, Any]
SchemaValidator = Callable[[JsonObject], tuple[bool, list[str]]]
Logger = Callable[[str], None]


class JSONLCodec:
    """Deterministic JSONL read/write helper for StableNew v2.6."""

    def __init__(
        self,
        *,
        schema_validator: SchemaValidator | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._schema_validator = schema_validator
        self._logger = logger or (lambda _: None)

    def read_jsonl(self, path: str | Path) -> list[JsonObject]:
        """Read all JSON objects from the given path."""
        return list(self.iter_jsonl(path))

    def iter_jsonl(self, path: str | Path) -> Iterator[JsonObject]:
        """Iterate over JSON objects stored one per line."""
        path_obj = Path(path)
        if not path_obj.exists():
            return iter(())
        try:
            with path_obj.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    item = line.strip()
                    if not item:
                        continue
                    parsed = self._parse_line(item, path_obj, line_number)
                    if parsed is None:
                        continue
                    yield parsed
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger(f"JSONL read error ({path_obj}): {exc}")

    def write_jsonl(self, path: str | Path, records: Iterable[JsonObject]) -> None:
        """Write the provided objects, one per line, using deterministic JSON."""
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with path_obj.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
                handle.write("\n")

    def _parse_line(self, line: str, path: Path, line_number: int) -> JsonObject | None:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            self._logger(f"JSONL decode error ({path}, line {line_number}): {exc}")
            return None
        if not isinstance(parsed, dict):
            return None
        if self._schema_validator:
            try:
                valid, errors = self._schema_validator(parsed)
            except Exception as exc:
                self._logger(
                    f"JSONL validator threw exception ({path}, line {line_number}): {exc}"
                )
                return None
            if not valid:
                self._logger(
                    f"JSONL validation failed ({path}, line {line_number}): {errors}"
                )
                return None
        return parsed
