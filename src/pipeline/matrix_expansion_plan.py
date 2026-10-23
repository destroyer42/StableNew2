"""Pure PromptPack Matrix expansion plan.

This is the single owner of Matrix semantics: which dimensions are active, their order, the theoretical
combination count, the effective limit and where it came from, and which combinations are selected.
``PromptPackNormalizedJobBuilder`` consumes it to build executable entries; the Matrix editor consumes it to
project counts and bounded examples. Neither keeps an executable algorithm of its own.

Semantics are the accepted compiler's, unchanged:

* a disabled Matrix, or one with no dimension that has both a name and values, expands to nothing;
* combinations are ordered as the Cartesian product of the dimensions in authored order, last dimension fastest;
* the effective limit is a positive ``matrix.limit``, else the randomizer ``max_variants`` hint, else 8;
* ``random`` selects that many unique combination *positions* without replacement and keeps them in position
  order; every other mode value (``fanout``, ``sequential``, unknown or missing) is the first N positions.

The only addition is an optional ``sample_seed``: when a valid one is stored, random selection uses a local
``random.Random(seed)`` and is reproducible; without one it draws from a fresh OS-seeded local generator, which is
the historical "may differ on every compile" behavior. Process-global ``random`` state is never read or written.

The module has no Tk, filesystem, queue or backend dependency, and never enumerates the full product.
"""

from __future__ import annotations

import math
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.pipeline.resolution_layer import MATRIX_TOKEN_RE
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

MATRIX_EXPANSION_CONTRACT = "matrix_expansion/1"
DEFAULT_MATRIX_EXPANSION_LIMIT = 8
MATRIX_SAMPLE_SEED_MAX = 2**32 - 1
#: Above this many selected combinations per row the editor warns (the limit itself is unchanged).
LARGE_SELECTION_THRESHOLD = 100

MODE_RANDOM = "random"
KNOWN_MATRIX_MODES = ("fanout", "sequential", MODE_RANDOM)
#: Mode the compiler applies when the pack stores none.
COMPILER_DEFAULT_MODE = "sequential"

LIMIT_SOURCE_MATRIX = "matrix.limit"
LIMIT_SOURCE_RANDOMIZER = "randomizer.max_variants"
LIMIT_SOURCE_DEFAULT = "default"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class MatrixIssue:
    """One authoring observation. Never repairs or rewrites the stored declaration."""

    code: str
    message: str
    severity: str = SEVERITY_WARNING
    subject: str = ""


@dataclass(frozen=True)
class MatrixDimension:
    name: str
    values: tuple[Any, ...]


def matrix_randomizer_limit_hint(
    randomizer_metadata: Mapping[str, Any] | None,
    config_snapshot: Mapping[str, Any] | None,
) -> int:
    """The randomizer ``max_variants`` the compiler falls back to when ``matrix.limit`` is not positive."""

    def positive(value: Any) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    hint = positive((randomizer_metadata or {}).get("max_variants"))
    if hint <= 0:
        randomization = (config_snapshot or {}).get("randomization", {})
        if isinstance(randomization, Mapping):
            hint = positive(randomization.get("max_variants"))
    return hint


def parse_sample_seed(raw: Any) -> tuple[int | None, bool]:
    """``(seed, invalid)``: a stored seed is valid only as a whole number in ``0..2**32-1`` (never coerced)."""

    if raw is None:
        return None, False
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= MATRIX_SAMPLE_SEED_MAX:
        return None, True
    return raw, False


def _configured_limit(raw: Any) -> int:
    try:
        return max(int(raw or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass(frozen=True)
class MatrixExpansionPlan:
    """Counts, limit provenance, issues and selection rules for one authored Matrix declaration."""

    enabled: bool
    mode: str | None
    dimensions: tuple[MatrixDimension, ...]
    #: Product of the dimension sizes (1 when nothing expands). Exact, never enumerated.
    theoretical_count: int
    effective_limit: int
    limit_source: str
    selected_count: int
    sample_seed: int | None
    sample_seed_invalid: bool
    raw_sample_seed: Any
    issues: tuple[MatrixIssue, ...]

    @property
    def expands(self) -> bool:
        """False for a disabled or empty Matrix: the compiler keeps the single unexpanded entry."""
        return bool(self.dimensions)

    @property
    def is_random(self) -> bool:
        return self.mode == MODE_RANDOM

    @property
    def effective_mode(self) -> str:
        return self.mode if self.mode is not None else COMPILER_DEFAULT_MODE

    @property
    def excluded_count(self) -> int:
        return max(self.theoretical_count - self.selected_count, 0) if self.expands else 0

    @property
    def truncated(self) -> bool:
        return self.excluded_count > 0

    @property
    def sample_is_reproducible(self) -> bool:
        return self.is_random and self.sample_seed is not None

    @property
    def samples_subset(self) -> bool:
        """True when random mode actually has to choose (a limit below the total)."""
        return self.expands and self.is_random and self.selected_count < self.theoretical_count

    def dimension_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.dimensions)

    def make_rng(self) -> random.Random:
        """Local generator: seeded when a valid ``sample_seed`` is stored, else OS-seeded. Never global state."""
        return random.Random(self.sample_seed) if self.sample_seed is not None else random.Random()

    def selected_indexes(self, rng: random.Random | None = None) -> tuple[int, ...]:
        """Cartesian positions the compiler expands, in expansion order."""
        if not self.expands:
            return ()
        if not self.samples_subset:
            return tuple(range(self.selected_count))
        return tuple(sorted(self._sample_positions(self.selected_count, rng or self.make_rng())))

    def preview_indexes(self, max_rows: int, rng: random.Random | None = None) -> tuple[int, ...]:
        """At most ``max_rows`` positions for display.

        Exact (the leading rows of the real selection) for ordered modes and for a seeded random Matrix;
        an illustrative draw for an unseeded random Matrix, which is *not* what a later compile will pick.
        """
        rows = max(0, min(int(max_rows), self.selected_count))
        if not self.expands or rows == 0:
            return ()
        if not self.samples_subset:
            return tuple(range(rows))
        if self.sample_seed is not None:
            return self.selected_indexes()[
                :rows
            ]  # the stored seed decides; an injected generator never overrides it
        return tuple(sorted(self._sample_positions(rows, rng or self.make_rng())))

    def _sample_positions(self, count: int, rng: random.Random) -> list[int]:
        if self.theoretical_count <= sys.maxsize:
            return rng.sample(range(self.theoretical_count), count)
        chosen: set[int] = set()
        while len(chosen) < count:
            chosen.add(rng.randrange(self.theoretical_count))
        return list(chosen)

    def combination_at(self, index: int) -> tuple[Any, ...]:
        """Values at Cartesian position ``index`` (mixed radix, last dimension varies fastest)."""
        if not 0 <= index < self.theoretical_count:
            raise IndexError("Matrix combination position out of range")
        values: list[Any] = []
        remaining = index
        for dimension in reversed(self.dimensions):
            remaining, position = divmod(remaining, len(dimension.values))
            values.append(dimension.values[position])
        values.reverse()
        return tuple(values)

    def combination_mapping(self, index: int) -> dict[str, Any]:
        return dict(zip(self.dimension_names(), self.combination_at(index), strict=True))

    def provenance(self, selected_ordinal: int, combination_index: int) -> dict[str, Any]:
        """Bounded, content-free expansion evidence frozen into each NJR (no values, no combination list)."""
        payload: dict[str, Any] = {
            "contract": MATRIX_EXPANSION_CONTRACT,
            "mode": self.effective_mode,
            "selection": "random_sample" if self.is_random else "ordered_prefix",
            "theoretical_count": self.theoretical_count,
            "effective_limit": self.effective_limit,
            "limit_source": self.limit_source,
            "selected_count": self.selected_count,
            "selected_ordinal": selected_ordinal,
            "combination_index": combination_index,
            "sample_seed": self.sample_seed if self.is_random else None,
        }
        if self.is_random and self.sample_seed_invalid:
            payload["sample_seed_invalid"] = True
        return payload


def _dimension_issues(
    names: Sequence[str], values_by_name: Mapping[str, tuple[Any, ...]]
) -> list[MatrixIssue]:
    issues: list[MatrixIssue] = []
    by_alias: dict[str, list[str]] = {}
    for name in names:
        alias = normalize_matrix_slot_name(name)
        by_alias.setdefault(alias, []).append(name)
        values = values_by_name[name]
        if len(set(map(repr, values))) < len(values):
            issues.append(
                MatrixIssue(
                    "duplicate_values",
                    f"'{name}' repeats a value; repeated values add duplicate combinations.",
                    SEVERITY_INFO,
                    name,
                )
            )
        if any(not isinstance(item, str) for item in values):
            issues.append(
                MatrixIssue(
                    "non_text_values",
                    f"'{name}' has a value that is not text.",
                    SEVERITY_WARNING,
                    name,
                )
            )
    for alias, group in by_alias.items():
        if alias and len(group) > 1:
            issues.append(
                MatrixIssue(
                    "ambiguous_alias",
                    f"{', '.join(repr(item) for item in group)} read as the same token ('{alias}'); "
                    "a spelling that matches none of them exactly resolves to the first.",
                    SEVERITY_WARNING,
                    group[0],
                )
            )
    return issues


def plan_matrix_expansion(
    matrix_config: Any,
    *,
    randomizer_limit: int | None = None,
) -> MatrixExpansionPlan:
    """Plan one stored ``pack_data.matrix`` declaration. Pure: the input is read, never modified."""

    issues: list[MatrixIssue] = []
    config: Mapping[str, Any] = matrix_config if isinstance(matrix_config, Mapping) else {}
    if matrix_config not in (None, {}) and not isinstance(matrix_config, Mapping):
        issues.append(
            MatrixIssue("matrix_malformed", "The stored Matrix is not an object; it is ignored.")
        )
    enabled = bool(config.get("enabled"))
    raw_mode = config.get("mode")
    mode = raw_mode if isinstance(raw_mode, str) else None
    if raw_mode is not None and mode is None:
        issues.append(
            MatrixIssue(
                "mode_malformed", "The stored Matrix mode is not text; it is treated as ordered."
            )
        )
    elif mode is not None and mode not in KNOWN_MATRIX_MODES:
        issues.append(
            MatrixIssue(
                "mode_unrecognized",
                f"Mode '{mode}' is not recognized; it expands like 'fanout' (ordered combinations).",
                SEVERITY_INFO,
            )
        )

    names: list[str] = []
    values_by_name: dict[str, tuple[Any, ...]] = {}
    if enabled:
        slots = config.get("slots", [])
        if not isinstance(slots, list | tuple):
            issues.append(
                MatrixIssue("slots_malformed", "The stored Matrix dimensions are not a list.")
            )
            slots = []
        for slot in slots:
            if not isinstance(slot, Mapping):
                issues.append(
                    MatrixIssue(
                        "dimension_malformed",
                        "A stored Matrix dimension is not an object; skipped.",
                    )
                )
                continue
            name = slot.get("name")
            values = slot.get("values", [])
            if not name or not values:
                if name or values:
                    issues.append(
                        MatrixIssue(
                            "dimension_incomplete",
                            f"Dimension '{name or '(unnamed)'}' needs both a name and at least one value; skipped.",
                            SEVERITY_WARNING,
                            str(name or ""),
                        )
                    )
                continue
            if not isinstance(name, str) or not isinstance(values, list | tuple):
                issues.append(
                    MatrixIssue(
                        "dimension_malformed",
                        f"Dimension {name!r} has a name or values of an unsupported type; skipped.",
                        SEVERITY_WARNING,
                        str(name),
                    )
                )
                continue
            if name in values_by_name:
                issues.append(
                    MatrixIssue(
                        "duplicate_name",
                        f"Dimension '{name}' is defined more than once; the last definition's values are used.",
                        SEVERITY_WARNING,
                        name,
                    )
                )
            else:
                names.append(name)
            values_by_name[name] = tuple(values)
    dimensions = tuple(MatrixDimension(name, values_by_name[name]) for name in names)
    issues.extend(_dimension_issues(names, values_by_name))

    theoretical = math.prod(len(item.values) for item in dimensions) if dimensions else 1

    raw_limit = config.get("limit")
    configured = _configured_limit(raw_limit)
    if configured > 0:
        effective, source = configured, LIMIT_SOURCE_MATRIX
    elif randomizer_limit is not None and randomizer_limit > 0:
        effective, source = int(randomizer_limit), LIMIT_SOURCE_RANDOMIZER
    else:
        effective, source = DEFAULT_MATRIX_EXPANSION_LIMIT, LIMIT_SOURCE_DEFAULT
    if raw_limit is not None and configured <= 0:
        issues.append(
            MatrixIssue(
                "limit_unusable",
                f"The stored limit {raw_limit!r} is not a positive whole number, so it does not mean 'unlimited'; "
                f"the {source} limit of {effective} applies.",
                SEVERITY_WARNING,
            )
        )

    seed, seed_invalid = parse_sample_seed(config.get("sample_seed"))
    if seed_invalid and mode == MODE_RANDOM:
        issues.append(
            MatrixIssue(
                "sample_seed_invalid",
                f"The stored sample seed {config.get('sample_seed')!r} is not a whole number from 0 to "
                f"{MATRIX_SAMPLE_SEED_MAX}; selection is not reproducible until it is corrected.",
                SEVERITY_WARNING,
            )
        )

    selected = min(theoretical, effective) if dimensions else 1
    if selected > LARGE_SELECTION_THRESHOLD:
        issues.append(
            MatrixIssue(
                "large_selection",
                f"{selected:,} combinations per prompt row will be compiled, and each becomes at least one job. "
                "Preview and the queue will be large; lower the limit if that is not intended.",
                SEVERITY_WARNING,
            )
        )
    return MatrixExpansionPlan(
        enabled=enabled,
        mode=mode,
        dimensions=dimensions,
        theoretical_count=theoretical,
        effective_limit=effective,
        limit_source=source,
        selected_count=selected,
        sample_seed=seed,
        sample_seed_invalid=seed_invalid,
        raw_sample_seed=config.get("sample_seed"),
        issues=tuple(issues),
    )


def unresolved_matrix_tokens(text: str, dimension_names: Sequence[str]) -> tuple[str, ...]:
    """Token names in ``text`` that no dimension resolves (exact name, then normalized alias).

    Informational only: the compiler leaves such tokens in the prompt and this never rewrites text.
    """

    exact = set(dimension_names)
    aliases = {normalize_matrix_slot_name(name) for name in dimension_names}
    missing: list[str] = []
    for match in MATRIX_TOKEN_RE.finditer(text or ""):
        token = match.group(1)
        if token in exact:
            continue
        alias = normalize_matrix_slot_name(token)
        if alias and alias in aliases:
            continue
        if token not in missing:
            missing.append(token)
    return tuple(missing)
