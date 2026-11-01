"""HTML fragments for the identity assessment in the eval contact sheet (PR-VID-QUALITY-351).

Every operator- or manifest-supplied string is escaped. The page runs no script and loads nothing remote.
Free text (notes) and the source image follow the report's content-visibility flag: when it is off, neither
is written into the page. The clips themselves are embedded exactly as before and are not content-screened;
the caveats say so rather than implying that hiding prompt text makes the page safe to share.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from pathlib import Path

from src.video.video_eval_assessment import (
    ArmSummary,
    Assessment,
    AssessmentState,
    CellAssessment,
    PairComparison,
    Verdict,
)
from src.video.video_eval_identity import Comparability, SourceReference
from src.video.video_eval_rubric import (
    ACTION_LABELS,
    BREAK_LABELS,
    CATEGORY_LABELS,
    SCORE_ANCHORS,
    SCORE_COLUMNS,
    SCORE_DIMENSIONS,
    SCORE_LABELS,
)

HIDDEN_TEXT = "[hidden in SFW mode]"

STATE_LABELS = {
    AssessmentState.UNREVIEWED: "Unreviewed",
    AssessmentState.PARTIAL: "Partially reviewed",
    AssessmentState.REVIEWED: "Reviewed",
    AssessmentState.IDENTITY_CONCERN: "IDENTITY CONCERN",
    AssessmentState.LEGACY_UNVERIFIED: "Legacy rating, artifact identity unverified",
    AssessmentState.STALE_ARTIFACT: "Stale: the clip changed after the review",
    AssessmentState.UNAVAILABLE: "Unavailable",
    AssessmentState.INCOMPARABLE: "Incomparable",
}
VERDICT_LABELS = {
    Verdict.INSUFFICIENT: "insufficient evidence",
    Verdict.INCOMPARABLE: "incomparable",
    Verdict.REGRESSION: "identity regression vs baseline",
    Verdict.IMPROVEMENT: "identity improvement vs baseline",
    Verdict.MIXED: "mixed identity change vs baseline",
    Verdict.NO_DIFFERENCE: "no identity difference vs baseline",
}
COMPARABILITY_LABELS = {
    Comparability.VERIFIED: "controlled pair verified",
    Comparability.NOT_FULLY_VERIFIED: "not fully verified",
    Comparability.INCOMPARABLE: "incomparable",
}

STYLE = """
.assess{margin-top:6px;font-size:12px;border-top:1px dashed #bbb;padding-top:4px}
.assess .badge{font-weight:bold}
.assess.s-identity_concern .badge,.assess.s-stale_artifact .badge,.assess.s-incomparable .badge{color:#a33}
.assess.s-reviewed .badge{color:#276a2f}
.assess table{font-size:11px;border-collapse:collapse}.assess th{text-align:left;font-weight:normal;padding-right:8px}
.assess .reason,.srcnote{color:#666;font-size:11px}
.vs{margin-top:4px;font-size:12px;font-weight:bold}
.vs.identity_regression,.vs.mixed,.vs.incomparable{color:#a33}.vs.identity_improvement{color:#276a2f}
img.source{max-width:200px;max-height:200px;display:block;margin:4px 0;border:1px solid #ccc}
.banner{border:2px solid #999;padding:8px;margin:12px 0;max-width:900px}
.banner.concerns{border-color:#a33}.banner.ready{border-color:#276a2f}
table.sum{border-collapse:collapse;font-size:12px;margin:8px 0}
table.sum td,table.sum th{border:1px solid #ccc;padding:3px 8px;text-align:left;vertical-align:top}
"""


def _esc(value: object) -> str:
    return html.escape(str(value))


def _signed(delta: int) -> str:
    return f"{delta:+d}" if delta else "0"


def source_html(ref: SourceReference | None, *, show_media: bool) -> str:
    if ref is None:
        return "<div class='srcnote'>source image: not in the run manifest</div>"
    label = f"source image: {ref.status.value}"
    if ref.displayable and show_media:
        uri = Path(ref.path).resolve().as_uri()
        return (
            f"<img class='source' src='{_esc(uri)}' alt='source image for case {_esc(ref.case_id)}'>"
            f"<div class='srcnote'>{_esc(label)} (digest matches the admitted suite)</div>"
        )
    if ref.displayable:
        return f"<div class='srcnote'>{_esc(label)}; image {HIDDEN_TEXT}</div>"
    return f"<div class='srcnote'><b>{_esc(label)}</b>: {_esc(ref.message)}</div>"


def cell_html(cell: CellAssessment | None, pair: PairComparison | None, *, show_text: bool) -> str:
    if cell is None:
        return ""
    ev = cell.evidence
    out = [
        f"<div class='assess s-{cell.state.value}'><span class='badge'>{_esc(STATE_LABELS[cell.state])}</span>"
    ]
    for reason in cell.reasons:
        out.append(f"<div class='reason'>{_esc(reason)}</div>")
    if ev.has_content:
        if not cell.counts:
            out.append(
                "<div class='reason'>Recorded rating shown for reference only; it is not counted.</div>"
            )
        rows = [
            f"<tr><th>{_esc(label)}</th><td>{_esc(ev.scores.get(column) or 'not assessed')}</td></tr>"
            for column, label in SCORE_LABELS.items()
        ]
        rows.append(f"<tr><th>Overall</th><td>{_esc(ev.overall or 'not assessed')}</td></tr>")
        rows.append(
            "<tr><th>Requested action</th><td>"
            f"{_esc(ACTION_LABELS.get(ev.requested_action or '', 'not assessed'))}</td></tr>"
        )
        rows.append(
            "<tr><th>Critical identity break</th><td>"
            f"{_esc(BREAK_LABELS.get(ev.critical_identity_break or '', 'not assessed'))}</td></tr>"
        )
        if ev.failure_categories:
            names = ", ".join(CATEGORY_LABELS[key] for key in ev.failure_categories)
            rows.append(f"<tr><th>Failure categories</th><td>{_esc(names)}</td></tr>")
        if ev.first_failure_seconds is not None:
            rows.append(
                f"<tr><th>First failure</th><td>{_esc(f'{ev.first_failure_seconds:g}')} s</td></tr>"
            )
        out.append("<table>" + "".join(rows) + "</table>")
        for issue in ev.issues:
            out.append(f"<div class='reason'>invalid entry: {_esc(issue)}</div>")
    if ev.notes:
        out.append(
            f"<div class='reason'>notes: {_esc(ev.notes) if show_text else HIDDEN_TEXT}</div>"
        )
    out.append("</div>")
    if pair is not None:
        out.append(_pair_html(pair))
    return "".join(out)


def _pair_html(pair: PairComparison) -> str:
    out = [
        f"<div class='vs {pair.verdict.value}'>{_esc(VERDICT_LABELS[pair.verdict])} "
        f"<span class='reason'>({_esc(COMPARABILITY_LABELS[pair.comparability])})</span></div>"
    ]
    parts = []
    for column in SCORE_COLUMNS:
        delta = pair.differences.get(column)
        if delta is not None:
            word = "improved" if delta > 0 else "declined" if delta < 0 else "same"
            parts.append(f"{SCORE_LABELS[column]} {_signed(delta)} ({word})")
    if parts:
        out.append(f"<div class='reason'>{_esc('; '.join(parts))}</div>")
    if any(pair.critical_break):
        base, cand = (BREAK_LABELS.get(v or "", "not assessed") for v in pair.critical_break)
        out.append(
            f"<div class='reason'>critical identity break: baseline {_esc(base)}, candidate {_esc(cand)}</div>"
        )
    if any(pair.requested_action):
        base, cand = (ACTION_LABELS.get(v or "", "not assessed") for v in pair.requested_action)
        out.append(
            f"<div class='reason'>requested action: baseline {_esc(base)}, candidate {_esc(cand)}</div>"
        )
    for reason in pair.reasons:
        out.append(f"<div class='reason'>{_esc(reason)}</div>")
    return "".join(out)


def _counts(counts: Mapping[int, int]) -> str:
    return " ".join(f"{score}:{n}" for score, n in counts.items())


def _arm_rows(summary: ArmSummary) -> list[tuple[str, str]]:
    motion = summary.motion
    return [
        (
            "Cases (applicable / completed / measurable)",
            f"{summary.applicable_cases} / {summary.completed_cases} / {summary.measurable_cases}",
        ),
        ("Identity-reviewed (complete, bound)", str(summary.identity_reviewed_cases)),
        ("Critical identity failures", str(summary.critical_identity_failures)),
        (
            f"Source fidelity counts by score ({summary.valid_source_fidelity} valid)",
            _counts(summary.source_fidelity_counts),
        ),
        (
            f"Subject stability counts by score ({summary.valid_subject_stability} valid)",
            _counts(summary.subject_stability_counts),
        ),
        (
            "Motion achieved / partial / not / cannot assess",
            f"{motion['achieved']} / {motion['partially_achieved']} / {motion['not_achieved']} / {motion['cannot_assess']}",
        ),
        ("Temporal concerns", str(summary.temporal_concerns)),
        ("Scene concerns", str(summary.scene_concerns)),
        (
            "Cases without a verified baseline pair",
            "n/a (baseline)" if summary.is_baseline else str(summary.without_verified_baseline),
        ),
        ("Numeric guardrail flags", str(summary.numeric_flagged)),
        (
            "Review states",
            ", ".join(f"{state} {n}" for state, n in summary.states.items() if n) or "none",
        ),
    ]


def summary_html(assessment: Assessment) -> str:
    klass = {"IDENTITY CONCERNS": "concerns", "READY FOR OWNER REVIEW": "ready"}.get(
        assessment.readiness.value, ""
    )
    out = [
        f"<div class='banner {klass}'><b>{_esc(assessment.readiness.value)}</b>",
        "<div class='reason'>This is a review aid, not an approval, and no arm is ranked or promoted. "
        "Ready for owner review means every case has a verified, fully reviewed comparison and no critical "
        "identity break was recorded.</div><ul>",
    ]
    out.extend(f"<li>{_esc(reason)}</li>" for reason in assessment.readiness_reasons)
    out.append("</ul></div><h2>Identity and continuity summary</h2>")
    out.append("<table class='sum'><tr><th></th>")
    for arm in assessment.arms:
        marker = " (baseline)" if arm.is_baseline else ""
        out.append(f"<th>{_esc(arm.label)}{_esc(marker)}</th>")
    out.append("</tr>")
    labels = [label for label, _ in _arm_rows(assessment.arms[0])] if assessment.arms else []
    for index, label in enumerate(labels):
        out.append(f"<tr><th>{_esc(label)}</th>")
        for arm in assessment.arms:
            out.append(f"<td>{_esc(_arm_rows(arm)[index][1])}</td>")
        out.append("</tr>")
    out.append("<tr><th>Readiness</th>")
    for arm in assessment.arms:
        out.append(f"<td>{_esc(arm.readiness.value) if arm.readiness else 'baseline'}</td>")
    out.append("</tr></table>")
    return "".join(out)


def rubric_html() -> str:
    rows = "".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(question)}</td></tr>"
        for _column, label, question in SCORE_DIMENSIONS
    )
    anchors = " ".join(f"<b>{score}</b> {_esc(text)}" for score, text in SCORE_ANCHORS)
    return (
        "<details><summary>Review rubric</summary>"
        f"<table class='sum'>{rows}</table><p class='caveat'>Scores 1-5, higher is better. {anchors} "
        "A blank cell means not assessed, not zero. Critical identity break is a separate Yes / No / Cannot "
        "assess answer; an intended turn, expression change, occlusion or camera move is not a break.</p></details>"
    )


def caveats_html(*, show_text: bool) -> str:
    items = [
        "Numeric metrics come from a downscaled preview of at most the first 120 frames (256 px). They are "
        "guardrails and cannot establish identity; judge faces, clothing and objects on the original clip, "
        "and record the time you actually saw a failure.",
        "Ratings are ordinal operator judgments. Differences are counted in points; they are not "
        "probabilities and not proof that a changed setting caused them.",
        "A frozen clip with a stable subject is not a motion success, and a well-moving clip with a "
        "different subject is not an identity success; the two are recorded separately.",
        "Each rating is bound to the SHA-256 of the clip it was made on. A replaced clip makes its rating "
        "stale; ratings without a recorded digest are legacy and uncounted until re-reviewed.",
    ]
    if not show_text:
        items.append(
            "SFW mode hides prompts, notes and the source image on this page. It does not screen the "
            "embedded clips, which are shown as before, so this page is not safe to share on that basis."
        )
    return "<ul class='caveat'>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


__all__ = [
    "HIDDEN_TEXT",
    "STYLE",
    "caveats_html",
    "cell_html",
    "rubric_html",
    "source_html",
    "summary_html",
]
