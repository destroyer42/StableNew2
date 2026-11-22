"""Adopt a repository job into a storyboard tree by the storyboard link its plan carries (PR-VID-STORY-380, spec 7.5/7.7).

Pure tree arithmetic over one job's frozen NJR; the caller reads the repository and saves the tree once. The rules:

* a job whose plan is not policy v2 or names another storyboard is ignored;
* a resume (``sequence_resume`` on its stage) joins the takes holding the attempt it resumed (else its plan's takes);
* a job of pending takes (no attempts yet) becomes their first attempt;
* a replay (``sequence_replay_of``, or a re-run of takes that already have attempts) becomes new sibling takes with
  ``replay_of`` set, never a silent replacement; a chain replay becomes a new chain.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.pipeline.njr_core_v26 import thaw_json
from src.video.sequence_plan import (
    SEQUENCE_POLICY_VERSION_V2,
    STAGE_VIDEO_WORKFLOW,
    StoryboardPlanLink,
)
from src.video.sequence_resume import REPLAY_KEY, RESUME_KEY, SequenceResumeError, plan_from_njr
from src.video.storyboard import timestamp
from src.video.storyboard_tree import StoryboardTree, Take


def _block(config: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = config.get(key)
    return value if isinstance(value, Mapping) else None


def _lineage_parent(njr: Any, block: Mapping[str, Any] | None) -> str:
    """The job a resume or replay was made from: its directive block, else the replay provenance."""

    if block is not None and block.get("parent_job_id"):
        return str(block["parent_job_id"])
    metadata = getattr(getattr(njr, "provenance", None), "metadata", None)
    if isinstance(metadata, Mapping) and metadata.get("replay") and metadata.get("parent_job_id"):
        return str(metadata["parent_job_id"])
    return ""


def storyboard_link(
    njr: Any, storyboard_id: str
) -> tuple[StoryboardPlanLink, dict[str, Any]] | None:
    """The plan's storyboard link and the ``video_workflow`` stage config, when the job is a take of this storyboard."""

    try:
        plan = plan_from_njr(njr, STAGE_VIDEO_WORKFLOW)
    except SequenceResumeError:
        return None
    link = plan.storyboard
    if plan.policy_version != SEQUENCE_POLICY_VERSION_V2 or link is None:
        return None
    if link.storyboard_id != storyboard_id:
        return None
    stage = next(s for s in njr.stage_chain if s.stage_type == STAGE_VIDEO_WORKFLOW)
    return link, thaw_json(stage.extra)


def adopt_job(
    tree: StoryboardTree, job_id: str, njr: Any, *, new_id: Callable[[], str]
) -> StoryboardTree:
    """``tree`` with ``job_id`` adopted (see the module docstring); ``tree`` itself when nothing applies."""

    found = storyboard_link(njr, tree.storyboard_id)
    if found is None:
        return tree
    link, config = found
    by_id = {take.take_id: take for take in tree.takes}
    resume = _block(config, RESUME_KEY)
    if resume is not None:
        parent_job = _lineage_parent(njr, resume)
        targets = [t.take_id for t in tree.takes if parent_job and parent_job in t.attempts]
        for take_id in targets or [i for i in link.take_ids if i in by_id]:
            tree = tree.with_attempt(take_id, job_id)
        return tree
    if not link.take_ids or any(take_id not in by_id for take_id in link.take_ids):
        return tree
    originals = [by_id[take_id] for take_id in link.take_ids]
    replay = _block(config, REPLAY_KEY)
    if replay is None and all(not take.attempts for take in originals):
        for take in originals:
            tree = tree.with_attempt(take.take_id, job_id)
        return tree
    parent_job = _lineage_parent(njr, replay)
    holders = sorted(
        (t for t in tree.takes if parent_job and parent_job in t.attempts),
        key=lambda t: t.chain_position,
    )
    if len(holders) == len(originals):
        originals = holders  # a replay of a replay take is a replay of that take
    batch_id = new_id()
    now = timestamp()
    previous: str | None = None
    for original in originals:
        take = Take.from_dict(
            {
                **original.to_dict(),
                "take_id": new_id(),
                "parent_id": original.parent_id if previous is None else previous,
                "batch_id": batch_id,
                "attempts": [job_id],
                "replay_of": original.take_id,
                "mark": "none",
                "created_at": now,
            }
        )
        tree = tree.with_take(take)
        previous = take.take_id
    return tree


__all__ = ["adopt_job", "storyboard_link"]
