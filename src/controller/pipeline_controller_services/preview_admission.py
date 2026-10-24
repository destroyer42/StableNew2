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

The admission linearization point is that publish: ``accept_preview_result`` checks the claimed revision and
assigns the Preview in one step under the Preview lifecycle lock. A compile whose revision was superseded (the draft or
a relevant setting changed while it ran) is **refused** with ``PreviewSupersededError`` instead of being queued, so it
never reaches ``JobService``, never becomes the accepted Preview, and is never silently recompiled or re-sampled.
Records that passed that point are an ordinary admitted submission: a later draft edit affects subsequent work only, and
``release_admitted_draft`` clears the draft after a successful queue operation only while the Preview still *is* the
admitted records, so edits made after admission are never cleared. Explicit NJR submissions (replay, reprocess, video,
learning) do not use this module and keep their own contract.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord


class PreviewSupersededError(RuntimeError):
    """The draft changed while it was being compiled for admission; nothing was queued."""

    def __init__(self) -> None:
        super().__init__(
            "The draft changed while it was being compiled, so nothing was queued. "
            "Review the refreshed Preview and submit again."
        )


def accepted_preview_records(
    app_state: Any,
    compile_fresh: Callable[[], list[NormalizedJobRecord]],
) -> list[NormalizedJobRecord]:
    """The accepted Preview's frozen records, else one fresh compile of the draft (presented as the Preview).

    Raises ``PreviewSupersededError`` when the compile's revision was superseded before it could be committed.
    """
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
    if records and not app_state.accept_preview_result(records, revision=revision):
        raise PreviewSupersededError
    return records


def release_admitted_draft(app_state: Any, admitted: list[NormalizedJobRecord]) -> bool:
    """After a successful queue operation, clear the draft and Preview that produced ``admitted``.

    Only while the Preview still is exactly those records (``AppStateV2.clear_admitted_draft``); a draft edited after
    admission is left alone. A state double without the lifecycle keeps the plain clear.
    """
    clear = getattr(app_state, "clear_admitted_draft", None)
    if callable(clear):
        return bool(clear(admitted))
    for name, args in (("clear_job_draft", ()), ("set_preview_jobs", ([],))):
        method = getattr(app_state, name, None)
        if callable(method):
            method(*args)
    return True
