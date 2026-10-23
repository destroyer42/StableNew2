"""Which NJRs a queue submission admits: the accepted Preview, never a silent recompile (PR-GUI-UX-560).

``AppStateV2.preview_jobs`` is the authoritative Preview. Every change to a compile input (the job draft, relevant
settings, a saved PromptPack the draft uses) calls ``invalidate_preview``, which empties it, so a non-empty list is
current by construction. A submission therefore admits those frozen records as they are. Compiling again would
re-run Matrix selection (an unseeded random Matrix picks a new sample on every compile) and could queue jobs that
differ from the ones the operator reviewed.

Only when no Preview exists (it was invalidated and its rebuild has not finished, or it never ran) is the draft
compiled once, and that single compile is what is submitted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord


def accepted_preview_records(
    app_state: Any,
    compile_fresh: Callable[[], list[NormalizedJobRecord]],
) -> list[NormalizedJobRecord]:
    """The accepted Preview's frozen records, else one fresh compile of the draft."""
    accepted = list(getattr(app_state, "preview_jobs", None) or [])
    return accepted if accepted else list(compile_fresh() or [])
