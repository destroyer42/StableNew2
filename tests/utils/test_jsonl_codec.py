from __future__ import annotations

from pathlib import Path

from src.utils.jsonl_codec import JSONLCodec


def test_write_and_read_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    codec = JSONLCodec()
    records = [{"job_id": "a", "priority": 1}, {"job_id": "b", "priority": 2}]

    codec.write_jsonl(path, records)
    assert path.exists()
    assert codec.read_jsonl(path) == records


def test_jsonl_uses_sorted_keys_and_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "sorted.jsonl"
    codec = JSONLCodec()
    codec.write_jsonl(path, [{"b": 2, "a": 1}])

    line = path.read_text(encoding="utf-8").rstrip("\n")
    assert line == '{"a":1,"b":2}'


def test_corrupt_lines_are_reported_and_skipped(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.jsonl"
    path.write_text('{"ok":1}\nnot valid\n{"ok":2}\n', encoding="utf-8")
    logs: list[str] = []
    codec = JSONLCodec(logger=lambda message: logs.append(message))

    entries = codec.read_jsonl(path)
    assert entries == [{"ok": 1}, {"ok": 2}]
    assert any("decode error" in msg for msg in logs)


def test_schema_validator_runs_and_logs(tmp_path: Path) -> None:
    path = tmp_path / "validated.jsonl"
    path.write_text('{"ok":1}\n{"ok":0}\n', encoding="utf-8")
    logs: list[str] = []

    def validator(obj: dict[str, int]) -> tuple[bool, list[str]]:
        valid = obj.get("ok") == 1
        return (
            valid,
            [] if valid else ["invalid ok value"],
        )

    codec = JSONLCodec(schema_validator=validator, logger=lambda message: logs.append(message))
    entries = codec.read_jsonl(path)
    assert entries == [{"ok": 1}]
    assert any("validation failed" in msg for msg in logs)


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    codec = JSONLCodec()
    entries = codec.read_jsonl(tmp_path / "missing.jsonl")
    assert entries == []
