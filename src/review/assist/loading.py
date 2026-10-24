"""Pure checkpoint-key accounting for the two Smart Review models; no model library is imported (PR-IMG-REVIEW-320).

Both loaders are strict: every tensor the model needs must be in the pinned file, every extra tensor must be explained, and
nothing is ever initialized silently. A high-level ``from_pretrained`` only warns about a missing key and fills it with random
values, so the workers use these checks and ``load_state_dict(strict=True)`` instead (the loading evidence is the
REVIEW-320 offline qualification of the two exact checkpoints).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence

from src.conditioning.reference_map.contracts import CODE_INFERENCE, ReferenceMapError

#: The only Transformers line the two exports were qualified against (5.17.0); a later 5.x is allowed, 6.x is not.
QUALIFIED_TRANSFORMERS = (5, 17, 0)
MAX_REASONS = 8


def transformers_reason(version: str) -> str | None:
    """``None`` when the installed Transformers is inside the qualified line, otherwise a stable reason code."""

    parts = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    if parts is None:
        return "transformers_unparsable"
    found = tuple(int(part) for part in parts.groups())
    if found[0] > QUALIFIED_TRANSFORMERS[0]:
        return "transformers_too_new"
    if found < QUALIFIED_TRANSFORMERS:
        return "transformers_too_old"
    return None


def _fail(reasons: Sequence[str]) -> ReferenceMapError:
    return ReferenceMapError(
        CODE_INFERENCE,
        "The model files do not match this model's layout.",
        reasons=tuple(reasons[:MAX_REASONS]),
    )


def split_unexpected(
    file_shapes: Mapping[str, Sequence[int]],
    expected_shapes: Mapping[str, Sequence[int]],
    ignored_patterns: Collection[str],
) -> list[str]:
    """Keys of the file that the model must not receive, after proving the rest is exactly the model's own state.

    Raises ``ReferenceMapError`` when a model entry is missing, a shape differs, or an extra tensor is not explained by
    ``ignored_patterns`` (the model class's own list of tensors it knowingly leaves unused).
    """

    problems: list[str] = []
    ignored = [
        key
        for key in sorted(file_shapes)
        if key not in expected_shapes and _matches(key, ignored_patterns)
    ]
    extra = [
        key for key in sorted(file_shapes) if key not in expected_shapes and key not in ignored
    ]
    missing = [key for key in sorted(expected_shapes) if key not in file_shapes]
    problems += [f"unexpected:{key}" for key in extra]
    problems += [f"missing:{key}" for key in missing]
    problems += [
        f"shape:{key}"
        for key in sorted(set(file_shapes) & set(expected_shapes))
        if list(file_shapes[key]) != list(expected_shapes[key])
    ]
    if problems:
        raise _fail(problems)
    return ignored


def _matches(key: str, patterns: Collection[str]) -> bool:
    return any(re.search(pattern, key) for pattern in patterns)


def plan_tied_aliases(
    file_shapes: Mapping[str, Sequence[int]],
    expected_shapes: Mapping[str, Sequence[int]],
    declared_aliases: Mapping[str, str],
) -> dict[str, str]:
    """Missing model entries that the model itself declares as aliases of a tensor the file does contain.

    Returns ``{alias: root}``. Any other missing entry, any shape disagreement and any extra tensor raises
    ``ReferenceMapError``; no weight is ever invented.
    """

    def root(key: str) -> str:
        seen: set[str] = set()
        while key in declared_aliases:
            if key in seen:
                raise _fail([f"alias_cycle:{key}"])
            seen.add(key)
            key = declared_aliases[key]
        return key

    problems: list[str] = []
    plan: dict[str, str] = {}
    for key in sorted(expected_shapes):
        if key in file_shapes:
            if list(file_shapes[key]) != list(expected_shapes[key]):
                problems.append(f"shape:{key}")
            continue
        target = root(key)
        if (
            key in declared_aliases
            and target in file_shapes
            and list(file_shapes[target]) == list(expected_shapes[key])
        ):
            plan[key] = target
        else:
            problems.append(f"missing:{key}")
    problems += [f"unexpected:{key}" for key in sorted(set(file_shapes) - set(expected_shapes))]
    if problems:
        raise _fail(problems)
    return plan


__all__ = [
    "QUALIFIED_TRANSFORMERS",
    "plan_tied_aliases",
    "split_unexpected",
    "transformers_reason",
]
