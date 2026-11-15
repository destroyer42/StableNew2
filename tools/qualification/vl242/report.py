"""Plain-text report for the two-tier analysis (PR-AI-VL-242): one table per question and one verdict line per gate.

The report holds aggregate numbers only (no case id, image, prompt or answer), so it can be read outside the evaluation root.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tools.qualification.vl220 import eval2
from tools.qualification.vl242.analysis import RULES
from tools.qualification.vl242.gates import LICENSE, Verdict


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _ci(interval: Mapping[str, Any] | None) -> str:
    if not interval or interval.get("low") is None:
        return "-"
    return f"{_fmt(interval.get('point'))} [{_fmt(interval['low'])}, {_fmt(interval['high'])}]"


def _table(title: str, header: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = [f"## {title}", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += [
        "| " + " | ".join(_fmt(cell) if not isinstance(cell, str) else cell for cell in row) + " |"
        for row in rows
    ]
    return [*lines, ""]


def render(analysis: Mapping[str, Any], verdicts: Sequence[Verdict]) -> str:
    tiers = analysis["tiers"]
    floors = analysis["floors"]
    counts = analysis["counts"]
    out = [
        "# AI-VL-242 two-tier evaluation report",
        "",
        f"Plan `{analysis['plan_sha256']}`, stage **{analysis['stage']}**. Images {counts['images']} "
        f"(clean {counts['clean']}, defective {counts['defective']}, multi-subject {counts['multi_subject']}), "
        f"pairs {counts['pairs']}. Intervals: Wilson 95% for proportions, stratified percentile bootstrap "
        f"({eval2.BOOTSTRAP_RESAMPLES} resamples, seed {eval2.BOOTSTRAP_SEED}) otherwise. qualified: false.",
        "",
    ]
    out += _table(
        "Structured validity",
        ["system", "valid / cases", "valid rate 95%", "invalid reasons"],
        [
            [tier, f"{t['structured']['valid']} / {t['structured']['cases']}", _ci(t["structured"]["interval"]),
             ", ".join(f"{k} {v}" for k, v in t["structured"]["invalid_reasons"].items()) or "-"]
            for tier, t in tiers.items()
        ],
    )  # fmt: skip

    def detection_row(name: str, summary: Mapping[str, Any]) -> list[Any]:
        ivl = summary["intervals"]
        return [
            name,
            _ci(ivl["recall"]),
            _ci(ivl["false_alarm_rate"]),
            _ci(ivl["f1"]),
            _ci(ivl["balanced_accuracy"]),
        ]

    out += _table(
        "Image-level defect detection (confirmed defect vs confirmed clean)",
        ["system", "recall 95%", "clean false alarm 95%", "F1 95%", "balanced accuracy 95%"],
        [detection_row(tier, t) for tier, t in tiers.items()]
        + [
            detection_row(f"floor: {name}", f)
            for name, f in floors.items()
            if "image_detection" in f
        ],
    )

    def triage_row(name: str, summary: Mapping[str, Any]) -> list[Any]:
        tri = summary["finding_triage"]
        cat = tri["category_only"]
        return [
            name,
            _ci(summary["intervals"]["finding_precision"]),
            tri["recall"],
            cat["precision"],
            cat["recall"],
        ]

    out += _table(
        "Finding-level triage on confirmed-defect images (category and region)",
        ["system", "precision 95%", "recall", "category-only precision", "category-only recall"],
        [triage_row(tier, t) for tier, t in tiers.items()]
        + [triage_row(f"floor: {name}", f) for name, f in floors.items() if "finding_triage" in f],
    )
    out += _table(
        "Clean-image false alarms and hallucination proxy",
        ["system", "clean images not cleared", "findings on clean images", "per clean image",
         "unmatched findings on defective images (may be unrecorded defects)"],
        [
            [tier, f"{t['image_detection']['not_cleared']} / {t['image_detection']['clean']}",
             t["hallucination"]["findings_on_clean_images"], t["hallucination"]["findings_per_clean_image"],
             t["hallucination"]["unmatched_findings_on_defective_images"]]
            for tier, t in tiers.items()
        ],
    )  # fmt: skip
    paired = analysis["paired"]
    out += _table(
        "Paired comparison, deep vs fast on the same images (exact McNemar; paired bootstrap)",
        ["subset", "images", "deep right, fast wrong", "fast right, deep wrong", "one-sided p", "two-sided p"],
        [
            [name, p["images"], p["deep_right_fast_wrong"], p["fast_right_deep_wrong"], p["p_one_sided_deep_better"],
             p["p_two_sided"]]
            for name, p in (("all images", paired["correctness"]), ("defective", paired["defective_images"]),
                            ("clean", paired["clean_images"]))
        ],
    )  # fmt: skip
    out += [
        f"F1 fast {_fmt(paired['f1_fast'])}, deep {_fmt(paired['f1_deep'])}; gain {_ci(paired['f1_gain'])}; "
        f"balanced-accuracy gain {_ci(paired['balanced_accuracy_gain'])}. At least "
        f"{paired['minimum_discordant_for_p_0_05']} discordant images are needed before any p <= 0.05 is possible.",
        "",
    ]

    def pair_row(name: str, summary: Mapping[str, Any]) -> list[Any]:
        ba = summary["before_after"]
        if not ba["evaluated"]:
            return [name, "not evaluated", "-", "-", "-"]
        ivl = summary.get("intervals", {}).get("before_after_agreement")
        return [name, f"{ba['agree']} / {ba['scored']}", _ci(ivl) if ivl else _fmt(ba["agreement"]),
                ba["helped_binary_agreement"], ba["inconclusive_excluded"]]  # fmt: skip

    out += _table(
        "Before/after usefulness vs the human judgment (inconclusive excluded; no benefit = no clear difference)",
        [
            "system",
            "agree / scored",
            "agreement 95%",
            "helped vs not agreement",
            "inconclusive excluded",
        ],
        [pair_row(tier, t) for tier, t in tiers.items()]
        + [pair_row(f"floor: {n}", f) for n, f in floors.items()],
    )
    subject_rows: list[list[Any]] = []
    for tier, t in tiers.items():
        sub = t["multi_subject"]
        subject_rows.append(
            [tier, f"{sub['agree']} / {sub['multi_subject_images']}", _ci(t["intervals"].get("subject_agreement"))]
            if sub["evaluated"] else [tier, "not evaluated", sub["reason"]]
        )  # fmt: skip
    florence = analysis.get("florence")
    if florence:
        sub = florence["multi_subject"]
        subject_rows.append(
            ["Florence-2", f"{sub['agree']} / {sub['multi_subject_images']}", _ci(sub)]
            if "agree" in sub else ["Florence-2", "not evaluated", sub["reason"]]
        )  # fmt: skip
    out += _table("Multi-subject consistency (subject count on images with two or more)",
                  ["system", "agree / images", "agreement 95%"], subject_rows)  # fmt: skip
    if florence:
        out += [
            "Florence-2 cannot answer: "
            + "; ".join(f"{k} ({v})" for k, v in florence["not_addressable"].items()),
            "",
        ]
    out += _table(
        "Not evaluated (no human reference in the export; never guessed)",
        ["dimension", "why"], [[k, v] for k, v in analysis["not_evaluated"].items()],
    )  # fmt: skip
    out += _table(
        "Resources (reported apart from quality)",
        ["system", "mean s/image", "median s", "max s", "peak working set GiB", "memory over limit", "wall over limit"],
        [
            [tier, r["mean_seconds"], r["median_seconds"], r["max_seconds"],
             round(r["peak_working_set_bytes"] / 1024**3, 2), r["memory_violations"], r["wall_violations"]]
            for tier, r in ((tier, t["resources"]) for tier, t in tiers.items())
        ],
    )  # fmt: skip
    escalation = analysis["escalation"]
    out += _table(
        "Escalation simulation (both tiers' real answers and times on the same images)",
        ["rule", "recall", "clean false alarm", "F1", "finding precision", "escalated", "mean s/image (this set)",
         f"s/image at defect share {analysis['operator_defect_share']}", "time vs deep", "recall shortfall vs deep",
         "s/image at shares 0.25 / 0.5 / 0.75"],
        [
            [rule, escalation[rule]["recall"], escalation[rule]["false_alarm_rate"], escalation[rule]["f1"],
             escalation[rule]["finding_precision"], escalation[rule]["escalation_rate"],
             escalation[rule]["mean_seconds_per_image"], escalation[rule]["seconds_at_operator_share"],
             escalation[rule]["time_vs_deep"], escalation[rule]["recall_shortfall_vs_deep"],
             " / ".join(_fmt(v) for v in escalation[rule]["seconds_by_share"].values())]
            for rule in RULES
        ],
    )  # fmt: skip
    out += [
        "Operator-requested only is the `never` row (no request) and the `deep_only` row (a request).",
        "",
    ]
    out += ["## Gate verdicts", ""]
    out += [
        f"- **{v.gate_id} {v.verdict}**: {v.tier} {v.question} ({v.op} {_fmt(v.threshold)}): {v.detail}"
        for v in verdicts
    ]
    out += ["", LICENSE, ""]
    return "\n".join(out)


__all__ = ["render"]
