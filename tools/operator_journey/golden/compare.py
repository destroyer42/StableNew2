"""Compare two golden-path evidence directories metric by metric: improved / unchanged / degraded / inconclusive.

Either side may be a sealed baseline archive (verified first; an unsealed or tampered archive is refused) or a plain run
folder (accepted with an ``unverified`` note).  Runs of different suites or modes are incompatible and refused.  A
metric is ``inconclusive`` when its value is absent on either side, was not assessed, or when the environments differ
in a way that makes the measure meaningless to compare (timings across displays, drivers or layouts).  Environment
differences are always listed, never hidden.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import baseline
from tools.operator_journey.golden.friction import friction_report, reachability

IMPROVED, UNCHANGED, DEGRADED, INCONCLUSIVE = "improved", "unchanged", "degraded", "inconclusive"
EXIT_OK, EXIT_DEGRADED, EXIT_INCOMPARABLE = 0, 1, 5
_VERDICT_RANK = {"PASS": 0, "HOLD": 1, "FAIL": 2, "NO-GO": 3}
_REACH_RANK = {"DIRECT": 0, "WITH_WORKAROUNDS": 1, "BLOCKED": 2}
_TIMING_TOLERANCE = 0.15
#: Environment fields whose difference makes timing comparisons meaningless.
_TIMING_FACTORS = ("desktop_driver", "layout", "display", "python", "platform", "machine")


class Incomparable(Exception):
    """The two evidence sets cannot be compared (missing, unsealed, tampered or from different suites/modes)."""


def _load(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_dir():
        raise Incomparable(f"{path} is not a directory")
    note = "unverified (plain run folder)"
    if (path / baseline.MANIFEST).exists() or (path / baseline.COMPLETE).exists():
        report = baseline.verify_archive(path)
        if report["status"] != "OK":
            raise Incomparable(f"{path} is {report['status']}: {'; '.join(report['problems'][:3])}")
        note = "verified archive"
    elif path.name.startswith(baseline.PARTIAL_PREFIX):
        raise Incomparable(f"{path} is an interrupted archive")
    evidence_path = path / "evidence.json"
    if not evidence_path.is_file():
        raise Incomparable(f"{path} has no evidence.json")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Incomparable(f"{evidence_path} is unreadable: {exc}") from exc
    if not isinstance(evidence.get("journeys"), dict) or not evidence.get("suite"):
        raise Incomparable(f"{evidence_path} is not golden-path journey evidence")
    return {"path": str(path), "evidence": evidence, "integrity": note}


def environment(evidence: dict[str, Any]) -> dict[str, Any]:
    prov = evidence.get("provenance") or {}
    display = evidence.get("display") or prov.get("display") or {}
    return {
        "suite": evidence.get("suite"),
        "suite_version": evidence.get("suite_version"),
        "mode": evidence.get("mode"),
        "desktop_driver": evidence.get("desktop_driver"),
        "layout": evidence.get("layout") or prov.get("layout"),
        "repository_sha": evidence.get("repository_sha"),
        "tree_state": prov.get("tree_state"),
        "python": prov.get("python"),
        "platform": prov.get("platform"),
        "machine": prov.get("machine"),
        "display": {k: display.get(k) for k in ("width", "height", "dpi", "scaling_percent")},
        "harness_sources": (prov.get("harness_sources") or {}).get("combined_sha256"),
    }


def _seconds(result: dict[str, Any]) -> float | None:
    from datetime import datetime

    try:
        start = datetime.fromisoformat(str(result["started_at"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(result["completed_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return round((end - start).total_seconds(), 2)


def _errors(result: dict[str, Any]) -> int:
    captured = result.get("captured_errors") or {}
    return (
        sum(len(captured.get(k) or []) for k in ("gui", "threads", "logs"))
        + len(result.get("isolation_violations") or [])
        + len(result.get("shutdown_noise_after_close") or [])
    )


def _media(result: dict[str, Any]) -> str | None:
    for obs in result.get("observations", []):
        if obs.get("name") in ("image_media", "video_media") and isinstance(obs.get("value"), dict):
            return obs["value"].get("sha256")
    return None


def journey_metrics(result: dict[str, Any], driver: str) -> dict[str, Any]:
    trace = result.get("action_trace") or []
    report = result.get("friction") or friction_report(trace)
    checks = result.get("checks") or []
    passed = sum(1 for c in checks if c.get("passed"))
    return {
        "verdict": result.get("verdict"),
        "checks_passed_ratio": round(passed / len(checks), 4) if checks else None,
        "workaround_count": report["workaround_count"] if trace else None,
        "reachability": (result.get("outcomes") or {}).get("reachability")
        or reachability(driver, str(result.get("verdict")), result.get("failed_assertion"), report),
        "error_count": _errors(result),
        "duration_s": _seconds(result),
        "action_count": len(trace) if trace else None,
        "media_sha256": _media(result),
    }


def _judge_lower_better(a: Any, b: Any, tolerance: float = 0.0) -> str:
    if a is None or b is None:
        return INCONCLUSIVE
    if abs(b - a) <= tolerance * max(abs(a), 1e-9):
        return UNCHANGED
    return IMPROVED if b < a else DEGRADED


def _judge(name: str, a: Any, b: Any, ctx: dict[str, Any]) -> tuple[str, str]:
    if name == "verdict":
        if a not in _VERDICT_RANK or b not in _VERDICT_RANK:
            return INCONCLUSIVE, "verdict missing"
        return _judge_lower_better(_VERDICT_RANK[a], _VERDICT_RANK[b]), ""
    if name == "checks_passed_ratio":
        if a is None or b is None:
            return INCONCLUSIVE, "no checks recorded on one side"
        return (UNCHANGED if a == b else IMPROVED if b > a else DEGRADED), ""
    if name == "reachability":
        if a not in _REACH_RANK or b not in _REACH_RANK:
            return INCONCLUSIVE, "reachability not assessed on one side (needs real pointer input)"
        return _judge_lower_better(_REACH_RANK[a], _REACH_RANK[b]), ""
    if name == "duration_s":
        if ctx["timing_factors"]:
            return INCONCLUSIVE, "timings are not comparable across: " + ", ".join(
                ctx["timing_factors"]
            )
        if ctx["verdicts"] != {"PASS"}:
            return INCONCLUSIVE, "a run that did not pass has a truncated duration"
        return _judge_lower_better(
            a, b, _TIMING_TOLERANCE
        ), f"tolerance {int(_TIMING_TOLERANCE * 100)}%"
    if name == "media_sha256":
        if a is None or b is None:
            return INCONCLUSIVE, "no produced media recorded on one side"
        return (
            (UNCHANGED, "")
            if a == b
            else (INCONCLUSIVE, "different bytes; visual quality needs operator review")
        )
    if name in ("workaround_count", "action_count") and ctx["verdicts"] != {"PASS"}:
        # A journey that stopped early performed fewer actions and met fewer controls; the counts are truncated.
        return INCONCLUSIVE, "a run that did not pass stopped early, so its counts are truncated"
    return _judge_lower_better(a, b), ""  # workaround_count, error_count, action_count


def compare(a_dir: Path, b_dir: Path) -> dict[str, Any]:
    """Compare run A (reference) with run B (candidate).  Raises ``Incomparable`` when they cannot be compared."""

    a, b = _load(a_dir), _load(b_dir)
    env_a, env_b = environment(a["evidence"]), environment(b["evidence"])
    for key in ("suite", "mode"):
        if env_a[key] != env_b[key]:
            raise Incomparable(f"different {key}: {env_a[key]!r} vs {env_b[key]!r}")
    major = lambda v: str(v or "").split(".")[0]  # noqa: E731
    if major(env_a["suite_version"]) != major(env_b["suite_version"]):
        raise Incomparable(
            f"incompatible suite versions: {env_a['suite_version']} vs {env_b['suite_version']}"
        )
    diffs = [{"key": k, "a": env_a[k], "b": env_b[k]} for k in env_a if env_a[k] != env_b[k]]
    timing_factors = [d["key"] for d in diffs if d["key"] in _TIMING_FACTORS]
    journeys: dict[str, Any] = {}
    counts = {IMPROVED: 0, UNCHANGED: 0, DEGRADED: 0, INCONCLUSIVE: 0}
    ids = sorted(set(a["evidence"]["journeys"]) | set(b["evidence"]["journeys"]))
    for jid in ids:
        ra, rb = a["evidence"]["journeys"].get(jid), b["evidence"]["journeys"].get(jid)
        if ra is None or rb is None:
            journeys[jid] = {"present": {"a": ra is not None, "b": rb is not None}, "metrics": {}}
            counts[INCONCLUSIVE] += 1
            continue
        ma = journey_metrics(ra, str(a["evidence"].get("desktop_driver")))
        mb = journey_metrics(rb, str(b["evidence"].get("desktop_driver")))
        ctx = {"timing_factors": timing_factors, "verdicts": {ma["verdict"], mb["verdict"]}}
        rows = {}
        for name in ma:
            result, note = _judge(name, ma[name], mb[name], ctx)
            rows[name] = {"a": ma[name], "b": mb[name], "result": result, "note": note}
            counts[result] += 1
        journeys[jid] = {"present": {"a": True, "b": True}, "metrics": rows}
    return {
        "a": {"path": a["path"], "integrity": a["integrity"]},
        "b": {"path": b["path"], "integrity": b["integrity"]},
        "environment": {"a": env_a, "b": env_b, "differences": diffs},
        "journeys": journeys,
        "counts": counts,
        "regressions": counts[DEGRADED],
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Golden-path evidence comparison",
        "",
        f"- A (reference): `{result['a']['path']}` ({result['a']['integrity']})",
        f"- B (candidate): `{result['b']['path']}` ({result['b']['integrity']})",
        f"- Improved {result['counts'][IMPROVED]}, unchanged {result['counts'][UNCHANGED]}, "
        f"degraded {result['counts'][DEGRADED]}, inconclusive {result['counts'][INCONCLUSIVE]}",
        "",
        "## Environmental differences",
    ]
    diffs = result["environment"]["differences"]
    lines += [f"- {d['key']}: `{d['a']}` -> `{d['b']}`" for d in diffs] or ["- none"]
    for jid, journey in result["journeys"].items():
        lines += ["", f"## {jid}"]
        if not journey["metrics"]:
            lines.append(
                f"- inconclusive: journey present A={journey['present']['a']} B={journey['present']['b']}"
            )
            continue
        lines += ["| metric | A | B | result | note |", "| --- | --- | --- | --- | --- |"]
        for name, row in journey["metrics"].items():
            lines.append(f"| {name} | {row['a']} | {row['b']} | {row['result']} | {row['note']} |")
    return "\n".join(lines) + "\n"


def write_comparison(result: dict[str, Any], out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / "comparison"
    if stem.with_suffix(".json").exists():
        raise baseline.ArchiveRefused(f"{stem}.json exists; comparisons are never overwritten")
    stem.with_suffix(".json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    stem.with_suffix(".md").write_text(baseline.redact_paths(markdown(result)), encoding="utf-8")
    return stem.with_suffix(".md")


__all__ = [
    "EXIT_DEGRADED",
    "EXIT_INCOMPARABLE",
    "EXIT_OK",
    "Incomparable",
    "compare",
    "markdown",
    "write_comparison",
]
