"""HTML fragments for controlled-motion evidence in the eval contact sheet (PR-VID-MOTION-410).

Same rules as ``video_eval_assessment_html``: every manifest- or operator-supplied string is escaped, the page runs no
script and loads nothing remote, and free text and media follow the report's content-visibility flag. The driving
reference is a media file like the source image, so it is hidden with it, never auto-played and loaded only on request
(``preload='none'``). Unavailable measurements read "unavailable", never zero.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.video.video_eval_assessment import Assessment, CellAssessment, MotionState, PairComparison
from src.video.video_eval_integrity import INTEGRITY_LABELS, KIND_LABELS
from src.video.video_eval_motion import MOTION_CATEGORY_LABELS, as_mapping, as_mapping_or_none
from src.video.video_eval_motion_metrics import LIMITATIONS, STATUS_OK
from src.video.video_eval_rubric import (
    ACTION_LABELS,
    ATTACHMENT_LABELS,
    BREAK_LABELS,
    FIDELITY_ANCHORS,
    MOTION_RUBRIC_VERSION,
    OBSERVATION_FIELDS,
    OBSERVATION_VALUE_LABELS,
)
from src.video.video_eval_transfer import LEVEL_LABELS, LEVELS, TransferSummary

HIDDEN = "[hidden in SFW mode]"
STATE_LABELS = {
    MotionState.NOT_APPLICABLE: "",
    MotionState.UNREVIEWED: "Motion unreviewed",
    MotionState.PARTIAL: "Motion partially reviewed",
    MotionState.REVIEWED: "Motion reviewed",
    MotionState.LEGACY_UNVERIFIED: "Motion rating without a recorded driving context (unverified, not counted)",
    MotionState.INAPPLICABLE: "Motion rating inapplicable to the current context (kept, not counted)",
    MotionState.UNAVAILABLE: "Motion context unavailable",
}
STYLE = """
.motion{margin-top:6px;font-size:12px;border-top:1px dashed #889;padding-top:4px}
.motion .badge{font-weight:bold}
.motion.m-inapplicable .badge,.motion.m-unavailable .badge,.motion.m-legacy_unverified .badge{color:#a33}
.motion.m-reviewed .badge{color:#276a2f}
.motion table,.casemotion table{font-size:11px;border-collapse:collapse}
.motion th,.casemotion th{text-align:left;font-weight:normal;padding-right:8px}
.casemotion{margin-top:6px;font-size:12px;border:1px solid #99a;padding:4px;max-width:260px}
.casemotion video{width:200px;display:block;margin:4px 0;background:#000}
.diag{color:#445;font-size:11px;margin-top:4px}
.integrity{margin-top:4px;font-size:12px;font-weight:bold}
.integrity.verified_comparable,.integrity.verified_with_disclosed_differences{color:#276a2f}
.integrity.incomparable,.integrity.changed_input,.integrity.changed_output,.integrity.missing_evidence,.integrity.failed_or_incomplete{color:#a33}
"""


def _esc(value: object) -> str:
    return html.escape(str(value))


def _alignment_html(alignment: Any) -> str:
    """The frozen spatial alignment, in words; empty for an unaligned job."""

    if not isinstance(alignment, Mapping) or not alignment:
        return ""
    shift = f"({alignment.get('translate_x')}, {alignment.get('translate_y')}) px"
    return _esc(
        f", spatially aligned: scale {alignment.get('scale')}, shift {shift}"
        + (", mirrored" if alignment.get("mirror") else "")
        + f", transform {str(alignment.get('transform_sha256') or '')[:12]}..."
    )


def _num(value: Any, suffix: str = "") -> str:
    if value is None:
        return "unavailable"
    return f"{value:g}{suffix}" if isinstance(value, (int, float)) else str(value)


def case_html(
    case: Mapping[str, Any], *, show_media: bool, effective: Mapping[str, Any] | None
) -> str:
    """The case's driving reference, intended action and expectation, with the effective driver a job consumed."""

    motion = case.get("motion")
    if not isinstance(motion, Mapping):
        return ""
    driving = as_mapping(motion.get("driving"))
    library = as_mapping_or_none(driving.get("library_asset"))
    window = as_mapping(motion.get("window"))
    prep = as_mapping(motion.get("preparation"))
    notes = as_mapping(motion.get("annotations"))
    category = MOTION_CATEGORY_LABELS.get(str(motion.get("category")), str(motion.get("category")))
    rows = [
        ("Motion category", category),
        (
            "Provenance",
            f"Motion Library asset {library.get('asset_id')}"
            if library
            else "local video (provenance not verified)",
        ),
        ("Driver SHA-256", str(driving.get("sha256") or "")[:16] + "..."),
        (
            "Window (frames)",
            f"{window.get('start_frame', 0)} to {_num(window.get('end_frame')) if window.get('end_frame') is not None else 'end'}",
        ),
        (
            "Preparation",
            f"{prep.get('mode', 'as_is')}, rate conversion {prep.get('fps_conversion', 'none')}",
        ),
    ]
    if show_media:
        rows.insert(1, ("Intended action", str(motion.get("action") or "")))
        rows.insert(2, ("Expected outcome", str(motion.get("expected_outcome") or "")))
        if motion.get("direction"):
            rows.append(("Direction", str(motion["direction"])))
    else:
        rows.insert(1, ("Intended action", HIDDEN))
    for key in ("framing", "viewpoint", "source_compatibility"):
        if notes.get(key):
            rows.append((key.replace("_", " ").capitalize(), str(notes[key])))
    out = ["<div class='casemotion'><b>Driving-motion reference</b><table>"]
    out.extend(f"<tr><th>{_esc(a)}</th><td>{_esc(b)}</td></tr>" for a, b in rows)
    out.append("</table>")
    if effective:
        prepared = bool(effective.get("prepared"))
        out.append(
            "<div class='diag'>effective driving input: "
            + (
                f"prepared derivative {_esc(str(effective.get('driver_effective_sha256') or '')[:16])}... "
                f"(original {_esc(str(effective.get('driver_original_sha256') or '')[:16])}...)"
                + _alignment_html(effective.get("alignment_detail"))
                if prepared
                else "the original file, used as bound (not prepared)"
            )
            + "</div>"
        )
    else:
        out.append(
            "<div class='diag'>effective driving input: not available from the admitted job; only the "
            "original binding is shown and it is not verified as what the model consumed</div>"
        )
    path = str(driving.get("path") or "")
    if show_media and path:
        uri = Path(path).resolve().as_uri()
        out.append(f"<video src='{_esc(uri)}' controls muted preload='none'></video>")
    elif path:
        out.append(f"<div class='diag'>driving video {HIDDEN}</div>")
    out.append("</div>")
    return "".join(out)


def _ratings_rows(cell: CellAssessment) -> list[tuple[str, str]]:
    ev = cell.evidence
    rows = [
        ("Requested action", ACTION_LABELS.get(ev.requested_action or "", "not assessed")),
        ("Subject attachment", ATTACHMENT_LABELS.get(ev.subject_attachment or "", "not assessed")),
        ("Motion fidelity", f"{ev.motion_fidelity} of 5" if ev.motion_fidelity else "not assessed"),
    ]
    for column, label, _question, _values in OBSERVATION_FIELDS:
        value = ev.observations.get(column)
        rows.append((label, OBSERVATION_VALUE_LABELS[column].get(value or "", "not assessed")))
    if ev.critical_identity_break:
        rows.append(
            (
                "Critical identity break",
                BREAK_LABELS.get(ev.critical_identity_break, "not assessed"),
            )
        )
    return rows


def _diagnostic_html(diagnostic: Mapping[str, Any] | None) -> str:
    if diagnostic is None:
        return ""
    status = str(diagnostic.get("status"))
    out = [
        f"<div class='diag'><b>Global image-motion diagnostic</b> ({_esc(status)}); not pose fidelity and not "
        "evidence that the intended subject moved."
    ]
    comparison = diagnostic.get("comparison")
    if isinstance(comparison, Mapping):
        out.append(
            "<table>"
            f"<tr><th>Trace similarity</th><td>{_esc(_num(comparison.get('trace_correlation')))}</td></tr>"
            f"<tr><th>Timing displacement</th><td>{_esc(_num(comparison.get('lag_seconds'), ' s'))}</td></tr>"
            f"<tr><th>Onset displacement</th><td>{_esc(_num(comparison.get('onset_displacement_seconds'), ' s'))}</td></tr>"
            f"<tr><th>Relative magnitude</th><td>{_esc(_num(comparison.get('relative_motion_magnitude')))}</td></tr>"
            f"<tr><th>Result frozen while driver moves</th><td>{_esc(_num(comparison.get('result_frozen_while_driver_active_seconds'), ' s'))}</td></tr>"
            f"<tr><th>Compared window</th><td>{_esc(_num(comparison.get('compared_seconds'), ' s'))} on a common time basis"
            f"{', different frame rates' if comparison.get('fps_differs') else ''}</td></tr>"
            "</table>"
        )
    for reason in diagnostic.get("reasons") or []:
        out.append(f"<div>{_esc(reason)}</div>")
    if status != STATUS_OK and not diagnostic.get("reasons"):
        out.append("<div>unavailable</div>")
    out.append("</div>")
    return "".join(out)


def cell_html(
    cell: CellAssessment | None, diagnostic: Mapping[str, Any] | None, *, show_text: bool
) -> str:
    if cell is None or cell.motion is None:
        return ""
    label = STATE_LABELS[cell.motion_state]
    out = [
        f"<div class='motion m-{cell.motion_state.value}'><span class='badge'>{_esc(label)}</span>"
    ]
    out.extend(f"<div class='diag'>{_esc(reason)}</div>" for reason in cell.motion_reasons)
    if cell.integrity is not None:
        out.append(
            f"<div class='integrity {cell.integrity.value}'>{_esc(INTEGRITY_LABELS[cell.integrity])}</div>"
        )
        out.extend(f"<div class='diag'>{_esc(reason)}</div>" for reason in cell.integrity_reasons)
    ev = cell.evidence
    if ev.has_motion_content or ev.requested_action:
        if not cell.motion_counts:
            out.append(
                "<div class='diag'>Recorded motion rating shown for reference only; it is not counted.</div>"
            )
        out.append(
            "<table>"
            + "".join(
                f"<tr><th>{_esc(a)}</th><td>{_esc(b)}</td></tr>" for a, b in _ratings_rows(cell)
            )
            + "</table>"
        )
        if ev.motion_comments:
            out.append(
                f"<div class='diag'>motion comments: {_esc(ev.motion_comments) if show_text else HIDDEN}</div>"
            )
    out.append("</div>")
    out.append(_diagnostic_html(diagnostic))
    return "".join(out)


def pair_html(pair: PairComparison | None) -> str:
    if pair is None or pair.integrity is None:
        return ""
    integrity = pair.integrity
    out = [
        f"<div class='integrity {integrity.integrity.value}'>{_esc(KIND_LABELS[integrity.kind])}: "
        f"{_esc(INTEGRITY_LABELS[integrity.integrity])}</div>"
    ]
    if integrity.varied:
        out.append(f"<div class='diag'>differs in: {_esc(', '.join(integrity.varied))}</div>")
    out.extend(
        f"<div class='diag'>{_esc(text)}</div>"
        for text in (*integrity.disclosed, *integrity.reasons)
    )
    motion = pair.motion
    parts: list[str] = []
    for name, labels in (
        ("requested_action", ACTION_LABELS),
        ("subject_attachment", ATTACHMENT_LABELS),
    ):
        base, cand = motion.get(name, (None, None))
        if base or cand:
            parts.append(
                f"{name.replace('_', ' ')}: baseline {labels.get(base or '', 'not assessed')}, "
                f"candidate {labels.get(cand or '', 'not assessed')}"
            )
    delta = motion.get("motion_fidelity_delta")
    if delta is not None:
        parts.append(f"motion fidelity {delta:+d} vs baseline (points on the 1-5 anchors)")
    out.extend(f"<div class='diag'>{_esc(text)}</div>" for text in parts)
    return "".join(out)


def _percent(ratio: Mapping[str, Any]) -> str:
    value = ratio.get("value")
    shown = "unavailable" if value is None else f"{value * 100:.0f}%"
    return f"{shown} ({ratio['numerator']}/{ratio['denominator']}; {ratio['basis']})"


def transfer_html(transfer: TransferSummary | None) -> str:
    if transfer is None or not transfer.groups:
        return ""
    payload = transfer.to_payload()
    out = [
        "<h2>Motion transferability (this run)</h2>",
        "<p class='caveat'>Counts and denominators for this run only. A cell without a review is not rated and is "
        "never counted as a failed action; failed or unfinished jobs stay in the planned and completed counts. One "
        "source subject is repeated generation, not cross-subject evidence. These are decision-support summaries: "
        "nothing here ranks assets, promotes a workflow or updates the Motion Library.</p>",
    ]
    for level in LEVELS:
        groups = payload["levels"][level]
        if not groups:
            continue
        out.append(
            f"<h3>{_esc(LEVEL_LABELS[level])}</h3><table class='sum'><tr><th>Group</th><th>Attempts</th>"
            "<th>Subjects (evaluated / rated), seeds</th><th>Action</th><th>Attachment</th><th>Fidelity</th>"
            "<th>Readiness</th></tr>"
        )
        for group in groups:
            ratios = {item["name"]: item for item in group["ratios"]}
            fidelity = " ".join(f"{score}:{n}" for score, n in group["motion_fidelity"].items())
            out.append(
                "<tr>"
                f"<td>{_esc(group['label'])}</td>"
                f"<td>planned {group['planned_attempts']}, completed {group['completed_attempts']}, "
                f"failed or incomplete {group['failed_or_incomplete_attempts']}, verified comparable "
                f"{group['verified_comparable']}, rated {group['rated']}"
                f"{', duplicates excluded ' + str(group['duplicates_excluded']) if group['duplicates_excluded'] else ''}</td>"
                f"<td>{group['distinct_subjects_evaluated']} / {group['distinct_subjects_rated']}, {group['distinct_seeds']} seed(s)</td>"
                f"<td>{_esc(_percent(ratios['Action achieved']))}<br>{_esc(_percent(ratios['Action achieved or partially achieved']))}</td>"
                f"<td>{_esc(_percent(ratios['Intended subject performs the motion']))}</td>"
                f"<td>{_esc(fidelity)}<br>{_esc(_percent(ratios['Critical identity break']))}</td>"
                f"<td>{_esc(group['readiness'])}"
                + "".join(
                    f"<div class='diag'>{_esc(r)}</div>"
                    for r in (*group["readiness_reasons"], *group["notes"])
                )
                + "</td></tr>"
            )
        out.append("</table>")
    if payload["duplicates_excluded"]:
        out.append(
            f"<p class='caveat'>Excluded as replays or duplicates: {_esc(', '.join(payload['duplicates_excluded']))}.</p>"
        )
    return "".join(out)


def cross_subject_html(assessment: Assessment | None) -> str:
    if assessment is None or not assessment.cross_subject:
        return ""
    out = ["<h3>Cross-subject groups (integrity)</h3><ul class='caveat'>"]
    for group in assessment.cross_subject:
        integrity = group.integrity
        out.append(
            f"<li>arm {_esc(group.arm_id)}: {', '.join(_esc(c) for c in group.case_ids)} - "
            f"{integrity.distinct_subjects} distinct subject(s), {_esc(INTEGRITY_LABELS[integrity.integrity])}"
            + "".join(f" ({_esc(note)})" for note in (*integrity.disclosed, *integrity.reasons))
            + "</li>"
        )
    out.append("</ul>")
    return "".join(out)


def representation_groups_html(assessment: Assessment | None) -> str:
    if assessment is None or not assessment.representation_groups:
        return ""
    out = [
        "<h3>Driving-representation groups (integrity)</h3><p class='caveat'>Cases that share a source image and "
        "arm but bind different drivers. Only drivers verified as representations of one movement are a controlled "
        "comparison; anything else is exploratory evidence.</p><ul class='caveat'>"
    ]
    for group in assessment.representation_groups:
        integrity = group.integrity
        kinds = ", ".join(_esc(k) for k in group.representations) or "unverified drivers"
        out.append(
            f"<li>arm {_esc(group.arm_id)}, {_esc(group.category)}: {', '.join(_esc(c) for c in group.case_ids)} ({kinds}) - "
            f"{_esc(INTEGRITY_LABELS[integrity.integrity])}"
            + "".join(f" ({_esc(note)})" for note in (*integrity.disclosed, *integrity.reasons))
            + "</li>"
        )
    out.append("</ul>")
    return "".join(out)


def rubric_html() -> str:
    anchors = " ".join(f"<b>{score}</b> {_esc(text)}" for score, text in FIDELITY_ANCHORS)
    rows = "".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(question)}</td></tr>"
        for _c, label, question, _v in OBSERVATION_FIELDS
    )
    return (
        "<details><summary>Motion rubric</summary>"
        f"<p class='caveat'>{_esc(MOTION_RUBRIC_VERSION)}. Requested action, subject attachment and motion fidelity "
        "are three separate judgments, each apart from visual quality and identity. Rate fidelity against the "
        f"<b>effective driving reference</b>, not motion magnitude or looks. {anchors} Blank or 'not assessed' means "
        "not assessed, never zero; 'not applicable' removes a field that does not fit the movement (a head turn has "
        f"no locomotion).</p><table class='sum'>{rows}</table></details>"
    )


def caveats_html() -> str:
    items = [
        *LIMITATIONS,
        "A motion judgment is bound to the SHA-256 of the clip and to the driving context (source image, driver, "
        "prepared derivative, workflow and length). If any of them changes, the earlier motion rating is kept for the "
        "record but is not counted for the new context.",
    ]
    return "<ul class='caveat'>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


__all__ = [
    "STATE_LABELS",
    "STYLE",
    "case_html",
    "caveats_html",
    "cell_html",
    "cross_subject_html",
    "pair_html",
    "representation_groups_html",
    "rubric_html",
    "transfer_html",
]
