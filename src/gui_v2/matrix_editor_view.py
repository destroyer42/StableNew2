"""Matrix editor wording, counts and bounded examples (PR-GUI-UX-560).

Pure and toolkit-independent. Everything here is a read-only projection of ``MatrixExpansionPlan``, the one owner of
Matrix semantics; this module keeps no combination algorithm of its own and never modifies the pack. Examples are
substituted with the compiler's own token resolver, so what the editor shows is what ``[[token]]`` resolution does.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from src.gui.models.prompt_pack_model import MatrixConfig
from src.pipeline.matrix_expansion_plan import (
    KNOWN_MATRIX_MODES,
    LIMIT_SOURCE_DEFAULT,
    LIMIT_SOURCE_MATRIX,
    LIMIT_SOURCE_RANDOMIZER,
    MODE_RANDOM,
    SEVERITY_INFO,
    MatrixExpansionPlan,
    plan_matrix_expansion,
    unresolved_matrix_tokens,
)
from src.pipeline.resolution_layer import substitute_matrix_tokens

MAX_EXAMPLE_ROWS = 6

#: Operator wording per stored mode value. The stored values themselves are never relabeled.
MODE_TITLES: Mapping[str, str] = {
    "fanout": "All combinations (fanout)",
    "sequential": "Sequential (legacy)",
    "random": "Random sample",
}
MODE_HELP: Mapping[str, str] = {
    "fanout": (
        "Uses the first N combinations in order, where N is the limit. The last dimension changes fastest."
    ),
    "sequential": (
        "A legacy name. Today it expands exactly like fanout. It does not control the order jobs run in the queue."
    ),
    "random": (
        "Picks up to N different combinations at random, where N is the limit. "
        "Add a sample seed to repeat the same pick."
    ),
}
UNKNOWN_MODE_HELP = (
    "This mode is not one of the three above; it expands like fanout (ordered combinations)."
)

TOKEN_HELP = (
    "A dimension is a name with a list of values. Write [[name]] in a prompt and each combination replaces it "
    "with one value. Example: 'A [[character]] in a [[location]]' with character = knight, ranger and "
    "location = forest, castle gives 4 combinations."
)
SEED_FIELD_HELP = (
    "Sample seed: repeats which combinations are picked. It is separate from the image seed and the randomizer seed, "
    "and does not change how an image is drawn."
)
UNSEEDED_RANDOM_NOTICE = (
    "Random selections can change when you rebuild Preview. "
    "The current accepted Preview is the set queued for execution."
)
PREVIEW_AUTHORITY_NOTE = (
    "These counts are planned. Preview shows the jobs that were actually compiled."
)


@dataclass(frozen=True)
class StarterDimension:
    label: str
    name: str
    values: tuple[str, ...]


STARTER_DIMENSIONS: tuple[StarterDimension, ...] = (
    StarterDimension("Character or subject", "character", ("knight", "ranger", "mage")),
    StarterDimension(
        "Outfit or appearance", "outfit", ("leather armor", "silk robe", "winter coat")
    ),
    StarterDimension(
        "Scene or location", "location", ("misty forest", "stone castle", "desert market")
    ),
    StarterDimension("Lighting", "lighting", ("golden hour", "overcast", "candlelight")),
    StarterDimension(
        "Camera or framing", "framing", ("close-up portrait", "waist-up", "wide shot")
    ),
)


@dataclass(frozen=True)
class MatrixEditorView:
    mode_title: str
    mode_help: str
    show_seed: bool
    seed_help: str
    seed_error: str
    count_lines: tuple[str, ...]
    multiplicity_lines: tuple[str, ...]
    warnings: tuple[str, ...]
    examples_heading: str
    example_rows: tuple[str, ...]
    examples_footer: str
    exact_examples: bool
    plan: MatrixExpansionPlan


def parse_seed_entry(text: str) -> tuple[int | None, str]:
    """``(seed, error)`` for what the operator typed; an empty entry means 'no seed'."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None, ""
    if not cleaned.isascii() or not cleaned.isdigit():
        return None, "Enter a whole number from 0 to 4294967295, or leave it empty."
    value = int(cleaned)
    if value > 4294967295:
        return None, "Enter a whole number from 0 to 4294967295, or leave it empty."
    return value, ""


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}" if count == 1 else f"{count:,} {word}s"


def _limit_text(plan: MatrixExpansionPlan) -> str:
    source = {
        LIMIT_SOURCE_MATRIX: "this Matrix limit",
        LIMIT_SOURCE_RANDOMIZER: "the Pipeline randomizer's Max variants, because the Matrix limit is not a positive number",
        LIMIT_SOURCE_DEFAULT: "the built-in default, because the Matrix limit is not a positive number",
    }[plan.limit_source]
    return f"Limit in effect: {plan.effective_limit:,} (from {source})."


def build_matrix_editor_view(
    config: MatrixConfig,
    prompt_text: str = "",
    *,
    randomizer_limit: int | None = None,
    batch_runs: int | None = None,
    images_per_prompt: int | None = None,
    max_example_rows: int = MAX_EXAMPLE_ROWS,
    rng: random.Random | None = None,
) -> MatrixEditorView:
    """Project one editor state. Reads ``config``; allocates only what is shown."""
    plan = plan_matrix_expansion(config.to_mapping(), randomizer_limit=randomizer_limit)
    # The editor shows the declaration even while it is disabled, so counts always describe the authored dimensions.
    shown = (
        plan
        if plan.enabled
        else plan_matrix_expansion(
            {
                **(config.to_mapping() if isinstance(config.to_mapping(), dict) else {}),
                "enabled": True,
            },
            randomizer_limit=randomizer_limit,
        )
    )

    mode = shown.mode
    title = MODE_TITLES.get(
        mode or "", f"Mode: {mode}" if mode else "Sequential (legacy, default when unset)"
    )
    help_text = MODE_HELP.get(
        mode or "", MODE_HELP["sequential"] if mode is None else UNKNOWN_MODE_HELP
    )

    count_lines: list[str] = []
    multiplicity: list[str] = []
    if not shown.expands:
        count_lines.append(
            "No dimensions yet: add a name and at least one value to expand this prompt."
        )
    else:
        parts = ", ".join(f"{item.name} {len(item.values)}" for item in shown.dimensions)
        count_lines.append(f"Dimensions: {len(shown.dimensions)} ({parts}).")
        count_lines.append(f"Possible combinations: {shown.theoretical_count:,}.")
        count_lines.append(_limit_text(shown))
        count_lines.append(
            f"Compiled per prompt row: {shown.selected_count:,} of {shown.theoretical_count:,}."
        )
        if shown.truncated:
            count_lines.append(
                f"Not selected: {shown.excluded_count:,}. These combinations will not be queued; "
                "raise the limit to include more."
            )
        if not plan.enabled:
            count_lines.append("Matrix is off: nothing is expanded until it is enabled.")
        multiplicity.append(
            f"Each selected combination becomes a job for every prompt row you queue, times batch runs "
            f"(loop count), and each job makes images-per-prompt images. {PREVIEW_AUTHORITY_NOTE}"
        )
        if shown.selected_count and (batch_runs or images_per_prompt):
            runs = max(1, int(batch_runs or 1))
            per_job = max(1, int(images_per_prompt or 1))
            jobs = shown.selected_count * runs
            multiplicity.append(
                f"With this pack's saved settings (batch runs {runs}, images per prompt {per_job}): "
                f"about {_plural(jobs, 'job')} and {_plural(jobs * per_job, 'image')} per prompt row (estimate)."
            )

    warnings = [issue.message for issue in shown.issues if issue.severity != SEVERITY_INFO]
    warnings.extend(issue.message for issue in shown.issues if issue.severity == SEVERITY_INFO)
    if shown.expands and prompt_text:
        for token in unresolved_matrix_tokens(prompt_text, shown.dimension_names()):
            warnings.append(
                f"[[{token}]] in this prompt has no matching dimension; it stays in the prompt text as written."
            )

    show_seed = mode == MODE_RANDOM
    seed_error = ""
    if show_seed and shown.sample_seed_invalid:
        seed_error = "The stored seed is not a whole number from 0 to 4294967295; selection is not repeatable."
    if show_seed and shown.sample_seed is None:
        warnings.append(UNSEEDED_RANDOM_NOTICE)

    exact = False
    rows: list[str] = []
    heading = "Examples"
    footer = ""
    if shown.expands and prompt_text.strip():
        indexes = shown.preview_indexes(max_example_rows, rng)
        for position, index in enumerate(indexes, start=1):
            rows.append(
                f"{position}. {substitute_matrix_tokens(prompt_text, shown.combination_mapping(index))}"
            )
        if shown.is_random and shown.sample_seed is None:
            heading = "Illustrative examples (not frozen)"
            footer = "Random, no sample seed: a new Preview may pick different combinations."
        elif shown.is_random and shown.limit_source == LIMIT_SOURCE_MATRIX:
            exact = True
            heading = f"Selection for sample seed {shown.sample_seed}"
            footer = "Preview applies this same selection."
        elif shown.is_random:
            heading = "Examples (limit may change at compile)"
            footer = "The limit comes from the Pipeline randomizer, so Preview may select a different number."
        else:
            exact = True
            heading = "First combinations, in compile order"
        if shown.selected_count > len(rows):
            more = f"{shown.selected_count - len(rows):,} more selected combination(s) are not listed here."
            footer = f"{footer} {more}".strip()
    elif shown.expands:
        heading = "Examples"
        footer = "Type a prompt containing [[dimension]] tokens to see examples."

    return MatrixEditorView(
        mode_title=title,
        mode_help=help_text,
        show_seed=show_seed,
        seed_help=SEED_FIELD_HELP,
        seed_error=seed_error,
        count_lines=tuple(count_lines),
        multiplicity_lines=tuple(multiplicity),
        warnings=tuple(warnings),
        examples_heading=heading,
        example_rows=tuple(rows),
        examples_footer=footer,
        exact_examples=exact,
        plan=shown,
    )


def is_known_mode(mode: str | None) -> bool:
    return mode in KNOWN_MATRIX_MODES


def matrix_summary_line(config: MatrixConfig) -> str:
    """One line for the Prompt tab's info pane ("" without a usable dimension), from the same plan as the editor."""
    plan = build_matrix_editor_view(config, "").plan
    if not plan.expands:
        return ""
    line = f"Matrix combinations: {plan.theoretical_count:,} possible, {plan.selected_count:,} selected"
    if plan.truncated:
        line += f" (limit {plan.effective_limit:,}; {plan.excluded_count:,} not queued)"
    return line + ("" if config.enabled else " - Matrix is off")
