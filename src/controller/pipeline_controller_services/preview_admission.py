"""Which NJRs a queue submission admits: the accepted Preview, never a silent recompile (PR-GUI-UX-560).

``AppStateV2.preview_jobs`` is the authoritative Preview. Every change to a compile input (the job draft, relevant
settings, a saved PromptPack the draft uses) calls ``invalidate_preview``, which empties it, so a non-empty list is
current by construction. A submission therefore admits those frozen records as they are. Compiling again would
re-run Matrix selection (an unseeded random Matrix picks a new sample on every compile) and could queue jobs that
differ from the ones the operator reviewed.

Only when no Preview exists (it was invalidated and its rebuild has not finished, or it never ran) is the draft
compiled once, and that single compile is what is submitted. That path first *claims* the Preview revision, so a
build still in flight for the old revision can no longer publish a different selection, and then presents the
compiled records as the Preview, so what the operator sees is what was queued
(``AppStateV2.claim_preview_for_admission`` / ``accept_preview_result``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord


def accepted_preview_records(
    app_state: Any,
    compile_fresh: Callable[[], list[NormalizedJobRecord]],
) -> list[NormalizedJobRecord]:
    """The accepted Preview's frozen records, else one fresh compile of the draft (presented as the Preview)."""
    claim = getattr(app_state, "claim_preview_for_admission", None)
    if not callable(
        claim
    ):  # a state without the Preview lifecycle (a test double): read it as before
        accepted = list(getattr(app_state, "preview_jobs", None) or [])
        return accepted if accepted else list(compile_fresh() or [])
    accepted, revision = claim()
    if accepted:
        return list(accepted)
    records = list(compile_fresh() or [])
    if records:
        app_state.accept_preview_result(
            records, revision=revision
        )  # dropped if the draft changed meanwhile
    return records
