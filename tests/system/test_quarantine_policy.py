"""Flake-watch policy (audit P1-5): a flaky test is fixed or quarantined with an owner and an expiry, never retried quietly.

A test that fails and later passes without a code change is flaky. The census is a blocking gate, so it must be repaired
or moved to ``tests/quarantine/`` (ignored by pytest) with a first-line header naming who owns the repair and when the
quarantine ends. An expired quarantine fails this test, which forces the decision: fix it, extend it deliberately, or delete it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUARANTINE = ROOT / "tests" / "quarantine"
MAX_QUARANTINE_DAYS = 30
HEADER = re.compile(
    r"^# quarantined: (?P<since>\d{4}-\d{2}-\d{2}); owner: (?P<owner>\S.*?); expires: (?P<expires>\d{4}-\d{2}-\d{2}); reason: (?P<reason>\S.*)$"
)


def header_problems(text: str, today: date) -> list[str]:
    first = text.splitlines()[0] if text.strip() else ""
    match = HEADER.match(first)
    if not match:
        return [
            "first line must be `# quarantined: YYYY-MM-DD; owner: <name>; expires: YYYY-MM-DD; reason: <why>`"
        ]
    since, expires = date.fromisoformat(match["since"]), date.fromisoformat(match["expires"])
    problems = []
    if expires < today:
        problems.append(
            f"quarantine expired on {expires}: fix the test, extend deliberately, or delete it"
        )
    if expires - since > timedelta(days=MAX_QUARANTINE_DAYS):
        problems.append(f"quarantine longer than {MAX_QUARANTINE_DAYS} days")
    return problems


def test_every_quarantined_test_has_an_owner_a_reason_and_an_unexpired_deadline() -> None:
    offenders = {
        path.relative_to(ROOT).as_posix(): problems
        for path in sorted(QUARANTINE.rglob("test_*.py"))
        if (problems := header_problems(path.read_text(encoding="utf-8"), date.today()))
    }
    assert offenders == {}


def test_a_well_formed_header_passes() -> None:
    text = "# quarantined: 2026-10-16; owner: rob; expires: 2026-11-10; reason: wall-clock flake\nimport pytest\n"
    assert header_problems(text, date(2026, 10, 20)) == []


def test_a_missing_or_malformed_header_is_rejected() -> None:
    assert header_problems("import pytest\n", date(2026, 10, 20))
    assert header_problems("# quarantined: soon; owner: rob\n", date(2026, 10, 20))
    assert header_problems("", date(2026, 10, 20))


def test_an_expired_quarantine_is_rejected() -> None:
    text = "# quarantined: 2026-09-01; owner: rob; expires: 2026-09-20; reason: flake\n"
    assert any("expired" in p for p in header_problems(text, date(2026, 10, 20)))


def test_an_open_ended_quarantine_is_rejected() -> None:
    text = "# quarantined: 2026-10-01; owner: rob; expires: 2027-10-01; reason: flake\n"
    assert any("longer than" in p for p in header_problems(text, date(2026, 10, 20)))
