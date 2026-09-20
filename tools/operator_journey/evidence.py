"""Evidence bundle for an operator journey (machine JSON + human summary)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
HOLD = "HOLD"


@dataclass
class Check:
    phase: str
    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class JourneyEvidence:
    """Accumulates everything a journey observed; serialization is deterministic."""

    journey_id: str
    backend_mode: str
    repository_sha: str = "unknown"
    started_at: str = ""
    completed_at: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    variants: list[dict[str, Any]] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    action_trace: list[dict[str, Any]] = field(default_factory=list)
    thread_checkpoints: list[dict[str, Any]] = field(default_factory=list)
    gui_errors: list[str] = field(default_factory=list)
    thread_errors: list[str] = field(default_factory=list)
    log_errors: list[dict[str, Any]] = field(default_factory=list)
    isolation_violations: list[str] = field(default_factory=list)
    shutdown_noise: list[str] = field(default_factory=list)
    hold_reason: str = ""
    abort_reason: str = ""

    def now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def check(self, phase: str, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(phase, name, bool(passed), str(detail)))
        return bool(passed)

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def verdict(self) -> str:
        if self.hold_reason:
            return HOLD
        problems = (
            self.failed_checks
            or self.abort_reason
            or self.gui_errors
            or self.thread_errors
            or self.isolation_violations
        )
        return FAIL if problems else PASS

    @property
    def failed_assertion(self) -> str:
        if self.hold_reason:
            return f"prerequisite: {self.hold_reason}"
        if self.failed_checks:
            first = self.failed_checks[0]
            return f"{first.phase}/{first.name}: {first.detail}"
        if self.abort_reason:
            return self.abort_reason
        if self.gui_errors:
            return f"captured Tk error: {self.gui_errors[0].splitlines()[-1]}"
        if self.thread_errors:
            return f"captured thread error: {self.thread_errors[0].splitlines()[-1]}"
        if self.isolation_violations:
            return f"isolation: {self.isolation_violations[0]}"
        return ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "journey_id": self.journey_id,
            "repository_sha": self.repository_sha,
            "backend_mode": self.backend_mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "verdict": self.verdict,
            "failed_assertion": self.failed_assertion,
            "hold_reason": self.hold_reason,
            "abort_reason": self.abort_reason,
            "summary": self.summary,
            "variants": self.variants,
            "checks": [c.as_dict() for c in self.checks],
            "captured_errors": {
                "gui": self.gui_errors,
                "threads": self.thread_errors,
                "logs": self.log_errors,
            },
            "shutdown_noise_after_close": self.shutdown_noise,
            "isolation_violations": self.isolation_violations,
            "thread_checkpoints": self.thread_checkpoints,
            "action_trace": self.action_trace,
        }

    def to_json(self) -> str:
        """Deterministic serialization: stable key order, indentation and separators."""

        return json.dumps(self.as_dict(), indent=2, sort_keys=True, default=str, ensure_ascii=False)

    def summary_text(self) -> str:
        lines = [
            f"Operator journey: {self.journey_id}",
            f"Verdict: {self.verdict}",
            f"Backend: {self.backend_mode}   Repository SHA: {self.repository_sha}",
        ]
        if self.failed_assertion:
            lines.append(f"Failed assertion: {self.failed_assertion}")
        for key in ("experiment_id", "model", "lora", "requested_seed", "evidence_dir"):
            if key in self.summary:
                lines.append(f"{key}: {self.summary[key]}")
        for variant in self.variants:
            lines.append(
                "  variant {value}: job={job_id} status={status} seeds={seeds} "
                "controlled={controlled}".format(
                    value=variant.get("value"),
                    job_id=variant.get("job_id"),
                    status=variant.get("job_status"),
                    seeds=variant.get("actual_all_seeds"),
                    controlled=variant.get("controlled_evidence_valid"),
                )
            )
        passed = sum(1 for c in self.checks if c.passed)
        lines.append(f"Checks: {passed}/{len(self.checks)} passed")
        for check in self.failed_checks:
            lines.append(f"  FAILED {check.phase}/{check.name}: {check.detail}")
        return "\n".join(lines) + "\n"

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "evidence.json").write_text(self.to_json(), encoding="utf-8")
        (directory / "summary.txt").write_text(self.summary_text(), encoding="utf-8")
        return directory / "evidence.json"
