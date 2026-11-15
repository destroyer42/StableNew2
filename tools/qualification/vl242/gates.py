"""Gate verdicts for the two-tier analysis (PR-AI-VL-242). The gate values are ``eval2.GATES``; this module only reads them.

Verdicts: ``PASS``, ``FAIL``, ``NOT_DECIDED`` (pilot: the interval still straddles the threshold), ``INSUFFICIENT_SAMPLE``
(a full run with fewer images than the gate needs) and ``NOT_APPLICABLE`` (the two-tier gate when the deep tier has not passed).

* A gate **fails clearly** at any stage when its 95 % interval lies entirely on the wrong side of the threshold (for a count
  gate: when a violation was observed). That is the only verdict a pilot can reach besides ``NOT_DECIDED``: **a pilot can stop
  a clearly failing tier but cannot pass one.**
* On a full run with the planned sample, a point gate passes when its point estimate meets the threshold; the floor gate
  passes when the one-sided 95 % lower bound of balanced accuracy is above the best floor; the deep-over-fast gate needs the
  F1 gain and an exact one-sided McNemar ``p <= 0.05`` favouring the deep tier.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tools.qualification.vl220 import eval2
from tools.qualification.vl220.eval2 import Gate
from tools.qualification.vl242.analysis import CONDITIONAL_RULES, RULE_DEEP_ONLY

PASS = "PASS"
FAIL = "FAIL"
NOT_DECIDED = "NOT_DECIDED"
INSUFFICIENT = "INSUFFICIENT_SAMPLE"
NOT_APPLICABLE = "NOT_APPLICABLE"

STAGE_PILOT = "pilot"
STAGE_FULL = "full"
STAGES = (STAGE_PILOT, STAGE_FULL)

MCNEMAR_ALPHA = 0.05
TWO_TIER_TIME_SHARE = 0.5
_EPS = 1e-9

LICENSE = (
    "A PASS licenses only this: usable for advisory review under Preview for this exact model, projector, runtime and "
    "scope (operator-selected images, closed findings the operator confirms in Review). It is not a promotion, not a "
    "qualified label and not a production entry point; those are separate owner decisions."
)


@dataclass(frozen=True, slots=True)
class Verdict:
    gate_id: str
    tier: str
    question: str
    verdict: str
    value: float | None
    threshold: float
    op: str
    detail: str

    def record(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id, "tier": self.tier, "question": self.question, "verdict": self.verdict,
            "value": self.value, "threshold": self.threshold, "op": self.op, "detail": self.detail,
        }  # fmt: skip


def _meets(value: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return value >= threshold - _EPS
    if op == "<=":
        return value <= threshold + _EPS
    if op == ">":
        return value > threshold + _EPS
    raise ValueError(op)


def _sample_short(gate: Gate, counts: Mapping[str, int]) -> str:
    short = [
        f"{key} {counts.get(key, 0)} < {need}"
        for key, need in gate.min_n.items()
        if counts.get(key, 0) < need
    ]
    return "; ".join(short)


def _interval_metric(tier: Mapping[str, Any], metric: str) -> Any:
    if metric == "valid_rate":
        return tier["structured"]["interval"]
    if metric == "false_alarm_rate":
        return tier["intervals"]["false_alarm_rate"]
    if metric == "recall":
        return tier["intervals"]["recall"]
    if metric == "finding_precision":
        return tier["intervals"]["finding_precision"]
    if metric == "balanced_accuracy_lower":
        return tier["intervals"]["balanced_accuracy"]
    raise KeyError(metric)


def _finish(gate: Gate, stage: str, counts: Mapping[str, int], value: float | None, clear_fail: bool,
            passes: bool, detail: str) -> Verdict:  # fmt: skip
    def make(verdict: str, extra: str = "") -> Verdict:
        text = detail if not extra else f"{detail}; {extra}" if detail else extra
        return Verdict(
            gate.gate_id, gate.tier, gate.question, verdict, value, gate.threshold, gate.op, text
        )

    if clear_fail:
        return make(FAIL, "the 95% interval lies on the wrong side of the threshold")
    if stage == STAGE_PILOT:
        return make(NOT_DECIDED, "a pilot can stop a clearly failing tier but cannot pass one")
    short = _sample_short(gate, counts)
    if short:
        return make(INSUFFICIENT, short)
    if value is None:
        # Fail closed: on the full sample an undefined value (e.g. no finding ever named) cannot pass.
        return make(FAIL, "undefined on the full sample")
    return make(PASS if passes else FAIL)


def _tier_gate(gate: Gate, stage: str, analysis: Mapping[str, Any]) -> Verdict:
    counts = analysis["counts"]
    tier = analysis["tiers"][gate.tier]
    if gate.metric == "resource_violations":
        resources = tier["resources"]
        value = float(resources["resource_violations"])
        detail = (
            f"memory over limit {resources['memory_violations']}, median {resources['median_seconds']} s"
            f"{' over budget' if resources['median_over_budget'] else ' within budget'}"
        )
        return _finish(
            gate, stage, counts, value, value > gate.threshold, value <= gate.threshold, detail
        )
    if gate.metric == "f1_gain":
        paired = analysis["paired"]
        gain = paired["f1_gain"]
        value = gain["point"]
        test = paired["correctness"]
        supported = (
            test["p_one_sided_deep_better"] <= MCNEMAR_ALPHA + _EPS
            and test["deep_right_fast_wrong"] > test["fast_right_deep_wrong"]
        )
        detail = (
            f"F1 deep {paired['f1_deep']} vs fast {paired['f1_fast']}, paired 95% [{gain['low']}, {gain['high']}]; "
            f"McNemar b={test['deep_right_fast_wrong']} c={test['fast_right_deep_wrong']} "
            f"one-sided p={test['p_one_sided_deep_better']}"
        )
        clear = gain["high"] is not None and gain["high"] < gate.threshold - _EPS
        passes = value is not None and _meets(value, gate.op, gate.threshold) and supported
        return _finish(gate, stage, counts, value, clear, passes, detail)
    interval = _interval_metric(tier, gate.metric)
    if gate.metric == "balanced_accuracy_lower":
        floor = float(analysis["best_floor_balanced_accuracy"])
        threshold_gate = Gate(gate.gate_id, gate.tier, gate.question, gate.metric, gate.op, floor, gate.min_n,
                              gate.basis, gate.support)  # fmt: skip
        value = interval["lower_95"]
        detail = (
            f"balanced accuracy {interval['point']}, one-sided 95% [{interval['lower_95']}, {interval['upper_95']}] "
            f"vs best floor {floor}"
        )
        clear = interval["upper_95"] is not None and interval["upper_95"] <= floor + _EPS
        passes = value is not None and _meets(value, ">", floor)
        verdict = _finish(threshold_gate, stage, counts, value, clear, passes, detail)
        return verdict
    value = interval["point"]
    low, high = interval["low"], interval["high"]
    detail = f"{value} (95% [{low}, {high}]"
    detail += f", n={interval['n']})" if "n" in interval else ")"
    if gate.op == ">=":
        clear = high is not None and high < gate.threshold - _EPS
    else:
        clear = low is not None and low > gate.threshold + _EPS
    passes = value is not None and _meets(value, gate.op, gate.threshold)
    if gate.support == "above_best_floor":
        floor = analysis["best_floor_finding_precision"]
        detail += f"; best floor {floor}"
        passes = passes and value is not None and (floor is None or value > floor + _EPS)
    return _finish(gate, stage, counts, value, clear, passes, detail)


def _two_tier_gate(
    gate: Gate, stage: str, analysis: Mapping[str, Any], deep_verdicts: Sequence[Verdict]
) -> Verdict:
    def make(verdict: str, value: float | None, detail: str) -> Verdict:
        return Verdict(
            gate.gate_id, gate.tier, gate.question, verdict, value, gate.threshold, gate.op, detail
        )

    rows = analysis["escalation"]
    deep_seconds = rows[RULE_DEEP_ONLY]["seconds_at_operator_share"]
    fa_limit = next(g.threshold for g in eval2.GATES if g.gate_id == "D2")
    met: list[str] = []
    best: float | None = None
    parts: list[str] = []
    for rule in CONDITIONAL_RULES:
        row = rows[rule]
        shortfall = row["recall_shortfall_vs_deep"]
        if shortfall is not None:
            best = shortfall if best is None else min(best, shortfall)
        ok = (
            shortfall is not None and _meets(shortfall, gate.op, gate.threshold)
            and row["false_alarm_rate"] is not None and row["false_alarm_rate"] <= fa_limit + _EPS
            and deep_seconds is not None and row["seconds_at_operator_share"] is not None
            and row["seconds_at_operator_share"] <= TWO_TIER_TIME_SHARE * deep_seconds + _EPS
        )  # fmt: skip
        parts.append(
            f"{rule}: recall shortfall {shortfall}, false alarm {row['false_alarm_rate']}, "
            f"time {row['time_vs_deep']} of deep{' (meets)' if ok else ''}"
        )
        if ok:
            met.append(rule)
    detail = "; ".join(parts)
    if stage == STAGE_PILOT:
        return make(NOT_DECIDED, best, f"{detail}; a pilot cannot pass a gate")
    deep_states = {v.verdict for v in deep_verdicts}
    if FAIL in deep_states:
        return make(
            NOT_APPLICABLE,
            best,
            f"{detail}; the deep tier failed a gate, so no two-tier design is licensed",
        )
    if deep_states != {PASS}:
        return make(INSUFFICIENT, best, f"{detail}; the deep tier gates are not all decided")
    short = _sample_short(gate, analysis["counts"])
    if short:
        return make(INSUFFICIENT, best, f"{detail}; {short}")
    return make(
        PASS if met else FAIL, best, f"{detail}; rules meeting the gate: {', '.join(met) or 'none'}"
    )


def evaluate(analysis: Mapping[str, Any]) -> list[Verdict]:
    """One verdict per gate in ``eval2.GATES`` order, at the stage the plan named."""

    stage = analysis["stage"]
    if stage not in STAGES:
        raise ValueError(stage)
    verdicts: list[Verdict] = []
    for gate in eval2.GATES:
        if gate.tier in eval2.TIERS:
            verdicts.append(_tier_gate(gate, stage, analysis))
        else:
            deep = [v for v in verdicts if v.tier == eval2.TIER_DEEP]
            verdicts.append(_two_tier_gate(gate, stage, analysis, deep))
    return verdicts


__all__ = [
    "FAIL",
    "INSUFFICIENT",
    "LICENSE",
    "NOT_APPLICABLE",
    "NOT_DECIDED",
    "PASS",
    "STAGES",
    "STAGE_FULL",
    "STAGE_PILOT",
    "Verdict",
    "evaluate",
]
