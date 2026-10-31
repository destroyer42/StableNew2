"""Evidence validators for GUI-PORT-742. Pure functions: a measurement is rejected, never repaired or inferred."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any


class EvidenceError(ValueError):
    """A sample, sequence or record that cannot support a conclusion."""


# ----- measurement samples -------------------------------------------------------------------------------------------
def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def summarize(
    values: Sequence[float], *, expected_n: int | None = None, label: str = "sample"
) -> dict[str, Any]:
    """min/median/p95/max. ``p95`` is nearest-rank and only reported for n >= 20 (otherwise it equals the maximum)."""

    if not values:
        raise EvidenceError(f"{label}: no samples")
    bad = [v for v in values if not _is_number(v) or v < 0]
    if bad:
        raise EvidenceError(f"{label}: invalid sample(s) {bad[:3]!r}")
    if expected_n is not None and len(values) != expected_n:
        raise EvidenceError(f"{label}: expected {expected_n} samples, got {len(values)}")
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": ordered[math.ceil(0.95 * n) - 1] if n >= 20 else None,
        "max": ordered[-1],
    }


def validate_sequence(sent: int, delivered: Sequence[int], *, lossless: bool) -> None:
    """Reject duplicates, reordering and missing updates.

    ``lossless`` dispatcher bursts must deliver ``0..sent-1`` exactly once. Hot AppState keys coalesce by design, so a
    coalesced stream must be strictly increasing, non-empty, no longer than ``sent`` and end with the final update.
    """

    seq = list(delivered)
    if lossless:
        if seq != list(range(sent)):
            missing = sorted(set(range(sent)) - set(seq))
            dupes = len(seq) - len(set(seq))
            raise EvidenceError(
                f"lossless sequence broken: {len(missing)} missing, {dupes} duplicate"
            )
        return
    if not seq or len(seq) > sent:
        raise EvidenceError("coalesced sequence empty or longer than sent")
    if any(b <= a for a, b in zip(seq, seq[1:], strict=False)):
        raise EvidenceError("coalesced sequence duplicated or reordered an update")
    if seq[-1] != sent - 1:
        raise EvidenceError("coalesced sequence did not deliver the final update")


# ----- visibility ----------------------------------------------------------------------------------------------------
def validate_visibility(
    first: Mapping[str, Any] | None,
    result: Mapping[str, Any] | None,
    toolkit: str,
    *,
    require_second_window: bool = False,
) -> None:
    """A timestamp is only valid for a window that was mapped (and, for Qt, exposed) before the result."""

    if not first or not result:
        raise EvidenceError("missing first_visible or result event")
    if first.get("visible") is not True:
        raise EvidenceError("window was not visible at the first-visible timestamp")
    if toolkit == "qt" and first.get("exposed") is not True:
        raise EvidenceError("Qt window was not exposed at the first-visible timestamp")
    if require_second_window and result.get("warm_visible_rendered") is not True:
        raise EvidenceError("second window was never verified as rendered")
    if not isinstance(first.get("clock_ns"), int) or first["clock_ns"] > result.get("clock_ns", 0):
        raise EvidenceError("first-visible clock missing or after the result")


# ----- process records -----------------------------------------------------------------------------------------------
def validate_process_record(record: Mapping[str, Any], *, require_containment: bool = True) -> None:
    if record.get("timeout"):
        raise EvidenceError("child timed out")
    if record.get("exit_code") != 0:
        raise EvidenceError(f"child exit code {record.get('exit_code')!r}")
    if record.get("result") is None:
        raise EvidenceError("child produced no structured result")
    if require_containment and not record.get("contained"):
        raise EvidenceError("child was not launched in an owned container")
    if record.get("surviving_descendants"):
        raise EvidenceError("owned descendants survived child exit")
    if record["result"].get("status") != "PASS":
        raise EvidenceError("child result is not PASS")


# ----- DPI -----------------------------------------------------------------------------------------------------------
def interpret_dpi(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a DPI record. A simulated scale is never reported as actual, and a claim the monitor contradicts fails."""

    reasons: list[str] = []
    requested = str(record.get("requested", ""))
    monitor, window = record.get("monitor_dpi"), record.get("window_dpi")
    simulated = record.get("simulated_factor")
    if record.get("awareness") != "per_monitor_v2":
        reasons.append(
            "process is not per-monitor-v2 DPI aware; scaling evidence is not qualifying"
        )
    if not _is_number(monitor) or not _is_number(window):
        reasons.append("monitor or window DPI missing")
    else:
        if simulated is None and window != monitor:
            reasons.append(
                f"window DPI {window} disagrees with monitor DPI {monitor} without simulation"
            )
        if requested.startswith("actual-"):
            wanted = int(requested.split("-", 1)[1]) / 100 * 96
            if simulated is not None:
                reasons.append("simulation active but actual scaling was claimed")
            if abs(monitor - wanted) > 1:
                reasons.append(f"claimed {requested} but monitor DPI is {monitor}")
    if requested.startswith("simulated-") and simulated is None:
        reasons.append("simulated scaling claimed without a recorded factor")
    kind = "SIMULATED" if simulated is not None else "ACTUAL"
    return {
        "classification": kind,
        "effective_percent": round(window / 96 * 100) if _is_number(window) else None,
        "valid": not reasons,
        "reasons": reasons,
    }


# ----- reachability --------------------------------------------------------------------------------------------------
REQUIRED_CONTROLS = (
    "nav",
    "search",
    "status",
    "date_from",
    "date_to",
    "apply",
    "clear",
    "notice",
    "queue_table",
    "history_table",
    "details",
    "result_line",
    "status_line",
)


def evaluate_reachability(
    controls: Mapping[str, Mapping[str, Any]],
    client: tuple[int, int],
    required: Sequence[str] = REQUIRED_CONTROLS,
) -> list[str]:
    """Issues (empty means reachable): missing, hidden, zero-size, offscreen, text-clipped or overlapping controls."""

    issues: list[str] = []
    width, height = client
    for name in required:
        c = controls.get(name)
        if c is None:
            issues.append(f"{name}: missing")
            continue
        if not c.get("visible"):
            issues.append(f"{name}: not visible")
        if c["w"] <= 0 or c["h"] <= 0:
            issues.append(f"{name}: zero size")
        if c["x"] < 0 or c["y"] < 0 or c["x"] + c["w"] > width or c["y"] + c["h"] > height:
            issues.append(f"{name}: outside the {width}x{height} client area")
        if c.get("text_clipped"):
            issues.append(f"{name}: text clipped")
    present = [n for n in required if n in controls and controls[n].get("visible")]
    for i, a in enumerate(present):
        for b in present[i + 1 :]:
            ca, cb = controls[a], controls[b]
            if (
                ca["x"] < cb["x"] + cb["w"]
                and cb["x"] < ca["x"] + ca["w"]
                and ca["y"] < cb["y"] + cb["h"]
                and cb["y"] < ca["y"] + ca["h"]
            ):
                issues.append(f"{a} overlaps {b}")
    return issues


# ----- cross-toolkit parity ------------------------------------------------------------------------------------------
def compare_parity(
    tk_steps: Sequence[Mapping[str, Any]], qt_steps: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Differences in the semantic outcome of the shared scenario (empty means identical)."""

    diffs: list[str] = []
    tk, qt = {s["name"]: s for s in tk_steps}, {s["name"]: s for s in qt_steps}
    if list(tk) != list(qt):
        diffs.append(f"step lists differ: {sorted(set(tk) ^ set(qt))}")
    for name in tk.keys() & qt.keys():
        a, b = tk[name], qt[name]
        if not (a["ok"] and b["ok"]):
            diffs.append(f"{name}: not passed on both toolkits (tk={a['ok']}, qt={b['ok']})")
        if a["expected"] != b["expected"]:
            diffs.append(f"{name}: expected outcomes differ")
        if a["observed"] != b["observed"]:
            diffs.append(f"{name}: observed outcomes differ")
    return diffs


# ----- dispatcher confound -------------------------------------------------------------------------------------------
def dispatch_policy_ratio(
    native_qt_ms: float, matched_qt_ms: float, tk_ms: float
) -> dict[str, Any]:
    """Split a Qt-vs-Tk latency gap into scheduling policy and everything else, from three medians.

    ``policy_share`` is the fraction of the native gap that disappears when Qt uses Tk's scheduling policy. It is only
    defined when Qt-native is faster than Tk; a share near 1 means the gap is policy, not framework.
    """

    for label, value in (
        ("native_qt_ms", native_qt_ms),
        ("matched_qt_ms", matched_qt_ms),
        ("tk_ms", tk_ms),
    ):
        if not _is_number(value) or value < 0:
            raise EvidenceError(f"{label}: invalid median {value!r}")
    gap = tk_ms - native_qt_ms
    share = None if gap <= 0 else (matched_qt_ms - native_qt_ms) / gap
    return {
        "native_gap_ms": gap,
        "residual_gap_ms": tk_ms - matched_qt_ms,
        "policy_share": None if share is None else max(0.0, min(1.0, share)),
        "native_speedup": None if native_qt_ms == 0 else tk_ms / native_qt_ms,
        "matched_speedup": None if matched_qt_ms == 0 else tk_ms / matched_qt_ms,
    }
