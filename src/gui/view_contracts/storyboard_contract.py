"""Toolkit-neutral capture and dirty-state for the existing sequence editor; no executable state."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.video.sequence_shots import ShotDraft
from src.video.storyboard import SETTING_KEYS, StoryboardDraft


class StoryboardSession:
    def __init__(self) -> None:
        self.draft = StoryboardDraft.new()
        self._saved = ""

    def opened(self, draft: StoryboardDraft) -> None:
        self.draft = draft
        self._saved = draft.fingerprint() if draft.revision else ""

    def saved(self, draft: StoryboardDraft) -> None:
        self.opened(draft)

    def reconcile_save(
        self, saved: StoryboardDraft, captured: StoryboardDraft, current: StoryboardDraft
    ) -> None:
        """Adopt durable identities without overwriting edits made while IO was running."""
        self.saved(saved)
        if current.fingerprint() == captured.fingerprint():
            return
        saved_shots = {
            old.shot_id: new for old, new in zip(captured.shots, saved.shots, strict=True)
        }
        shots = []
        for shot in current.shots:
            committed = saved_shots.get(shot.shot_id)
            shots.append(
                replace(
                    shot,
                    shot_id=committed.shot_id,
                    keyframe_sha256=committed.keyframe_sha256
                    if shot.keyframe_path == committed.keyframe_path
                    else shot.keyframe_sha256,
                )
                if committed is not None
                else shot
            )
        self.draft = replace(
            current,
            storyboard_id=saved.storyboard_id,
            created_at=saved.created_at,
            updated_at=saved.updated_at,
            revision=saved.revision,
            source_sha256=saved.source_sha256
            if current.source_path == saved.source_path
            else current.source_sha256,
            shots=tuple(shots),
        )

    def capture(
        self,
        source: str,
        form: dict[str, Any],
        shots: list[ShotDraft],
        *,
        title: str,
        clip_name: str,
        notes: str,
    ) -> StoryboardDraft:
        old = self.draft
        previous = {s.shot_id: s for s in old.shots}
        retained = []
        for shot in shots:
            before = previous.get(shot.shot_id)
            digest = (
                (before.keyframe_sha256 if before.keyframe_path == shot.keyframe_path else "")
                if before
                else shot.keyframe_sha256
            )
            retained.append(replace(shot, keyframe_sha256=digest))
        self.draft = replace(
            old,
            title=title,
            source_path=source,
            source_sha256=old.source_sha256 if source == old.source_path else "",
            workflow_id=str(form.get("workflow_id") or ""),
            workflow_version=str(form.get("workflow_version") or ""),
            settings=tuple(sorted((key, str(form[key])) for key in SETTING_KEYS if key in form)),
            shots=tuple(retained),
            clip_name=clip_name,
            notes=notes,
        )
        return self.draft

    @property
    def dirty(self) -> bool:
        return self.draft.fingerprint() != self._saved


__all__ = ["StoryboardSession"]
