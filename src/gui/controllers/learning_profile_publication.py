"""Small UI adapter for explicit publication, using existing background/record/profile owners."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.generation_profiles.contract import GenerationProfile, ProfileError, ProfileRef
from src.learning.learning_record import evidence_file_lock
from src.learning.profile_publication import ProfilePublicationService, PublicationProposal


@dataclass(frozen=True)
class PublicationContext:
    experiment_id: str
    model: str
    stage: str
    snapshot: str


def controller_context(controller: Any) -> PublicationContext:
    from src.learning.model_policy_service import selected_model

    experiment = controller.learning_state.current_experiment
    if experiment is None:
        return PublicationContext("", "", "", "")
    # The editable baseline identifies the selected target; the domain verifies it against
    # durable frozen evidence, so editing a baseline cannot reinterpret a historical run.
    baseline = controller.authoring_baseline() or experiment.baseline_config
    return PublicationContext(
        str(experiment.experiment_id),
        selected_model(baseline, experiment.stage),
        experiment.stage,
        str(experiment.execution_snapshot_json or ""),
    )


class LearningProfilePublicationCoordinator:
    def __init__(
        self,
        *,
        service: ProfilePublicationService,
        records_path: Path,
        runner: Any,
        context: Callable[[], PublicationContext],
        catalogs: Callable[[], dict[str, Any]],
        show: Callable[[str, Any], None],
        refresh_catalog: Callable[[], None],
    ) -> None:
        self.service = service
        self.records_path = records_path
        self.runner = runner
        self.context = context
        self.catalogs = catalogs
        self.show = show
        self.refresh_catalog = refresh_catalog
        self.proposal: PublicationProposal | None = None
        self._context: PublicationContext | None = None
        self._generation = 0
        self._closed = False
        self._publishing = False

    def close(self) -> None:
        self._closed = True
        self.invalidate()
        self.runner.close()

    def invalidate(self) -> None:
        self._generation += 1
        self.proposal = None

    def _current(self, generation: int, context: PublicationContext) -> bool:
        return not self._closed and generation == self._generation and context == self.context()

    def _rows(self) -> list[dict[str, Any]]:
        if not self.records_path.exists():
            return []
        rows = []
        with self.records_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    # A damaged log is an explicit refusal, never silently skipped evidence.
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ProfileError("Learning evidence contains a malformed record.")
                    rows.append(row)
        return rows

    def review(self) -> None:
        if self._closed or self._publishing:
            return
        self.invalidate()
        context = self.context()
        generation = self._generation
        self._context = context
        if not context.experiment_id or context.stage != "txt2img":
            self.show(
                "error",
                "Select an ordinary txt2img experiment. Stage-specific Learning profiles are not supported yet.",
            )
            return
        if json.loads(context.snapshot or "{}").get("study_type", "ordinary") not in (
            "ordinary",
            "controlled_variable",
        ):
            self.show(
                "error",
                "Model Comparison and Two-Axis Grid cannot publish Base Generation settings.",
            )
            return
        catalogs = self.catalogs()
        self.show("busy", "Checking saved controlled evidence…")

        def work() -> PublicationProposal:
            with evidence_file_lock(self.records_path):
                return self.service.evaluate(
                    self._rows(),
                    context.model,
                    experiment_id=context.experiment_id,
                    catalogs=catalogs,
                )

        def result(proposal: PublicationProposal) -> None:
            if self._current(generation, context):
                self.proposal = proposal
                self.show("proposal", proposal)

        self.runner.submit(
            "learning-profile-review",
            work,
            on_result=result,
            on_error=lambda error: self.show("error", str(error))
            if self._current(generation, context)
            else None,
        )

    def publish(self, *, name: str, lineage: ProfileRef | None, confirmed: bool) -> None:
        if not confirmed:
            return
        if (
            self._closed
            or self._publishing
            or self.proposal is None
            or self._context != self.context()
        ):
            self.show("error", "Proposal is stale; review findings again before publication.")
            return
        proposal, context, generation = self.proposal, self._context, self._generation
        catalogs = self.catalogs()
        self._publishing = True
        self.show("busy", "Publishing confirmed Learning profile…")

        def work() -> GenerationProfile:
            with evidence_file_lock(self.records_path):
                # No Tk access in this worker. A context invalidation supersedes a queued write.
                if self._closed or generation != self._generation:
                    raise ProfileError("Proposal is stale; publication was cancelled.")
                return self.service.publish(
                    proposal,
                    self._rows(),
                    context.model,
                    name=name,
                    confirmed=True,
                    lineage=lineage,
                    catalogs=catalogs,
                )

        def result(profile: GenerationProfile) -> None:
            self.refresh_catalog()  # Refresh catalog only: never select or apply the profile.
            if self._current(generation, context):
                self.proposal = None
                self.show(
                    "success",
                    f"Published {profile.name}, revision {profile.revision}. Select it in Base Generation.",
                )

        def error(exc: Exception) -> None:
            if self._current(generation, context):
                self.show("error", str(exc))

        def complete(_latest: bool, _error: Exception | None) -> None:
            self._publishing = False

        self.runner.submit(
            "learning-profile-publish", work, on_result=result, on_error=error, on_complete=complete
        )
