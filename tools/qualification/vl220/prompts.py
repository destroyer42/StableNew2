"""The question text for one visual case (PR-AI-VL-220, revised by PR-AI-VL-222). Pure and deterministic: the same case always
renders the same text.

The text states the question, lists the elements to judge with their ids, names the one answer shape the response schema allows
(with the case's real ids, in order, and a neutral ``<true or false>`` placeholder rather than a literal ``true`` the model
could copy) and, for object lists, says how to name an object. It carries no reference data (a case has none). The response
grammar bounds the structure; this text tells the model what each field means.

``mtmd-cli`` places the image marker and applies the chat template itself (see ``docs/work_packages/AI-VL-222_visual_diagnostic.md``),
so nothing here mentions a media marker.
"""

from __future__ import annotations

from tools.qualification.vl220 import contract
from tools.qualification.vl220.contract import Case

_HEAD = (
    "You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON "
    'object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.'
)

#: One sentence per defect category, so ``extra_limb`` and friends mean the same thing to the model as to the label.
_DEFECT_GLOSSARY = (
    "Categories: extra_limb means more arms or legs than a person has, missing_limb means fewer, fused_limb means limbs "
    "joined together, distorted means a badly shaped body part, wrong_count means a wrong number of fingers or toes, "
    "other is anything else."
)

#: How an object is named in a ``describe`` answer; generic on purpose (the example is not in any synthetic scene).
_NAMING = 'Name each object with its color and its kind, for example "blue car", in lower case.'

#: The unscored free-text control request of the diagnostic (no schema, no JSON). It is not a case.
CONTROL_PROMPT = "Describe this image in two or three plain sentences. Say what shapes or figures you see, their colors and where they are."


def _ids(case: Case) -> str:
    return ", ".join(key for key, _ in case.elements)


def _shape(case: Case) -> str:
    base = f'"schema":"{contract.RESPONSE_SCHEMA}","status":"ok","kind":"{case.kind}"'
    if case.kind in (contract.KIND_ADHERENCE, contract.KIND_CONSISTENCY):
        entries = ",".join(
            '{"id":"' + key + '","value":<true or false>}' for key, _ in case.elements
        )
        return "{" + base + ',"answers":[' + entries + "]}"
    if case.kind == contract.KIND_DEFECT:
        return (
            "{" + base + ',"findings":[{"region":"<one of: ' + ", ".join(contract.REGIONS) + '>",'
            '"category":"<one of: ' + ", ".join(contract.DEFECT_CATEGORIES) + '>",'
            '"severity":"<one of: ' + ", ".join(contract.SEVERITIES) + '>"}]}'
        )
    if case.kind == contract.KIND_BEFORE_AFTER:
        return (
            "{" + base + ',"preferred":"<one of: ' + ", ".join(contract.PREFERENCES) + '>",'
            '"reason":"<one of: ' + ", ".join(contract.PREFERENCE_REASONS) + '>"}'
        )
    return "{" + base + ',"objects":["<object name>"]}'


def _guidance(case: Case) -> str:
    if case.kind == contract.KIND_ADHERENCE:
        return (
            "For every listed element give true if it is clearly visible in the image, otherwise false. "
            f"Answer every element, once, in this order, using exactly these ids: {_ids(case)}."
        )
    if case.kind == contract.KIND_CONSISTENCY:
        return (
            "For every listed subject give true if it looks unchanged between the two panels, otherwise false. "
            f"Answer every subject, once, in this order, using exactly these ids: {_ids(case)}."
        )
    if case.kind == contract.KIND_DEFECT:
        return (
            "List every anatomical defect you can see. Use an empty findings list when there is none. "
            + _DEFECT_GLOSSARY
        )
    if case.kind == contract.KIND_BEFORE_AFTER:
        return (
            "You are given two images: image a is the first and image b is the second. Choose the one that is more useful "
            "for the request, or tie."
        )
    text = (
        "List only the objects you can actually see. Do not guess at hidden or unclear things. "
        + _NAMING
    )
    if case.vocabulary:
        text += " Use only names from this list: " + ", ".join(case.vocabulary) + "."
    return text


def render_visual_prompt(case: Case) -> str:
    """The prompt file text for ``case``. ``mtmd-cli`` puts the image marker(s) in front and applies the model's chat template."""

    lines = [_HEAD, "", f"Request: {case.prompt}", _guidance(case)]
    if case.elements:
        lines.append("Elements:")
        lines.extend(f"- {key}: {text}" for key, text in case.elements)
    lines += ["", "Answer shape: " + _shape(case), ""]
    return "\n".join(lines)


def render_control_prompt() -> str:
    """The free-text control prompt file text (diagnostic only; ``mtmd-cli`` adds the image marker and chat template)."""

    return CONTROL_PROMPT + "\n"


__all__ = ["CONTROL_PROMPT", "render_control_prompt", "render_visual_prompt"]
