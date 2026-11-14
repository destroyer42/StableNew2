"""The question text for one visual case (PR-AI-VL-220). Pure and deterministic: the same case always renders the same text.

The text states the question, lists the elements to judge and shows the one answer shape the response schema allows. It carries
no reference data (a case has none). The response grammar bounds the structure; this text only tells the model what each
field means.
"""

from __future__ import annotations

from tools.qualification.vl220 import contract
from tools.qualification.vl220.contract import Case

_HEAD = (
    "You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON "
    'object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.'
)


def _shape(case: Case) -> str:
    base = f'"schema":"{contract.RESPONSE_SCHEMA}","status":"ok","kind":"{case.kind}"'
    if case.kind in (contract.KIND_ADHERENCE, contract.KIND_CONSISTENCY):
        return '{' + base + ',"answers":[{"id":"<element id>","value":true}]}'
    if case.kind == contract.KIND_DEFECT:
        return (
            '{' + base + ',"findings":[{"region":"<one of: ' + ", ".join(contract.REGIONS) + '>",'
            '"category":"<one of: ' + ", ".join(contract.DEFECT_CATEGORIES) + '>",'
            '"severity":"<one of: ' + ", ".join(contract.SEVERITIES) + '>"}]}'
        )
    if case.kind == contract.KIND_BEFORE_AFTER:
        return (
            '{' + base + ',"preferred":"<one of: ' + ", ".join(contract.PREFERENCES) + '>",'
            '"reason":"<one of: ' + ", ".join(contract.PREFERENCE_REASONS) + '>"}'
        )
    return '{' + base + ',"objects":["<short object name>"]}'


def _guidance(case: Case) -> str:
    if case.kind == contract.KIND_ADHERENCE:
        return "For every listed element give true if it is clearly visible in the image, otherwise false. Answer every element."
    if case.kind == contract.KIND_CONSISTENCY:
        return "For every listed subject give true if it looks unchanged between the two panels, otherwise false. Answer every subject."
    if case.kind == contract.KIND_DEFECT:
        return "List every anatomical defect you can see. Use an empty findings list when there is none."
    if case.kind == contract.KIND_BEFORE_AFTER:
        return "Image a is the first image and image b is the second. Choose the one that is more useful for the request, or tie."
    return "List only the objects you can actually see. Do not guess at hidden or unclear things."


def render_visual_prompt(case: Case) -> str:
    """The prompt file text for ``case``. ``mtmd-cli`` applies the model's own chat template around it."""

    lines = [_HEAD, "", f"Request: {case.prompt}", _guidance(case)]
    if case.elements:
        lines.append("Elements:")
        lines.extend(f"- {key}: {text}" for key, text in case.elements)
    lines += ["", "Answer shape: " + _shape(case), ""]
    return "\n".join(lines)


__all__ = ["render_visual_prompt"]
