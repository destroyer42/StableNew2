"""Deterministic, evidence-bound phone follow-ups. Only the existing Preview can compile them."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Any

from PIL import Image

from src.ai_assist.contracts import SUGGESTION_SCHEMA_ID, VIDEO_STAGE, AssistRequest, SuggestionKind
from src.ai_assist.validators import validate_output
from src.app.site_media_files import SiteOutputError, open_scoped
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_admission import PhonePreviewInput
from src.app.site_phone_credentials import IDENTIFIER, PhoneGrant
from src.app.site_phone_video import PhoneVideo
from src.app.site_rating_sync import fingerprint
from src.gui_v2.history_iterate_model import assess_history_iterate
from src.image_backends.model_policy import EVIDENCE_REGISTRY
from src.learning.model_capabilities import policy_context, project_learning_capabilities
from src.learning.model_policy_service import resolve_policy
from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from src.pipeline.job_models_v2 import NormalizedJobRecord, OutputPlan
from src.pipeline.njr_core_v26 import thaw_json
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.utils.image_metadata import ImageMetadataContractV26, read_image_metadata
from src.utils.njr_identity import snapshot_fingerprint
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
from src.video.video_eval_ratings_store import ARTIFACT_COLUMN
from src.video.video_eval_rubric import parse_rating_row
from src.video.video_eval_suite import EvalCase
from src.video.video_execution_resolver import VIDEO_EXECUTION_KEY
from src.video.video_review_group import ArmState, classify_entry
from src.video.workflow_frame_count import legal_frame_counts

_DIGEST = re.compile(r"[a-f0-9]{64}")
_RUN = re.compile(r"\d{8}_\d{6}_[A-Za-z0-9_-]{1,150}")
_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _checked_source(raw: Any, grant: PhoneGrant) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise SiteOutputError("invalid_followup")
    kind = raw.get("kind")
    if kind in ("rating", "returned"):
        if not grant.native_review:
            raise SiteOutputError("phone_scope_refused")
        fields = {"kind", "id", "digest"}
        if kind == "returned":
            fields |= {"result_id", "result_digest"}
        if (
            raw.keys() == fields
            and _matches(IDENTIFIER, raw["id"])
            and _matches(_DIGEST, raw["digest"])
            and (
                kind == "rating"
                or (
                    _matches(IDENTIFIER, raw["result_id"])
                    and _matches(_DIGEST, raw["result_digest"])
                )
            )
        ):
            return raw
    if kind == "evaluation":
        if not grant.rating:
            raise SiteOutputError("phone_scope_refused")
        if (
            raw.keys() == {"kind", "run", "case", "baseline", "candidate"}
            and _matches(_RUN, raw["run"])
            and all(_matches(_KEY, raw[field]) for field in ("case", "baseline", "candidate"))
            and raw["baseline"] != raw["candidate"]
        ):
            return raw
    raise SiteOutputError("invalid_followup")


def _validate_advice(
    objective: str, *, target: str | None = None, workflow: str | None = None
) -> None:
    """Apply the same closed-list stage, target, workflow and count limits as advisory AI plans."""
    stage = VIDEO_STAGE if workflow else "txt2img"
    request = AssistRequest(
        "operator-followup",
        SuggestionKind.PLAN_PROPOSAL,
        goal_text=objective,
        allowed_stages=(stage,),
        allowed_targets=(target,) if target else (),
        allowed_workflows=(workflow,) if workflow else (),
    )
    result = validate_output(
        json.dumps(
            {
                "schema": SUGGESTION_SCHEMA_ID,
                "status": "ok",
                "kind": request.kind.value,
                "steps": [
                    {
                        "stage": stage,
                        "target": target,
                        "workflow": workflow,
                        "count": 2,
                        "rationale": objective,
                    }
                ],
            }
        ),
        request,
    )
    if result.suggestion is None:
        raise SiteOutputError("followup_ineligible")


def verified_history_source(
    repository: JobRepository, path: Path, raw: bytes
) -> tuple[NormalizedJobRecord, str]:
    """The History job that wrote the image at ``path`` (whose bytes are ``raw``), and its snapshot fingerprint.

    The image's embedded job id and NJR fingerprint must name a History entry whose recorded output is exactly this
    file and whose recipe Iterate can reproduce; anything else is ``followup_provenance_unverified``. Shared by the
    hosted relay's follow-ups and the review gateway's "more like this" (RG-140).
    """

    metadata = read_image_metadata(path, source_bytes=raw)
    job_id = metadata.get(ImageMetadataContractV26.KEY_JOB_ID)
    entry = repository.get_job(job_id) if job_id else None
    assessment = assess_history_iterate(entry, is_file=lambda value: Path(value).absolute() == path)
    record = assessment.njr
    if not assessment.pipeline.supported or entry is None or record is None:
        raise SiteOutputError("followup_provenance_unverified")
    snapshot = snapshot_fingerprint(entry.snapshot or {})
    if (
        Path(assessment.image_path or "").absolute() != path
        or metadata.get(ImageMetadataContractV26.KEY_NJR_SHA256) != snapshot
        or type(record.seed) is not int
        or record.seed < 0
        or assessment.recorded_seed not in (None, record.seed)
    ):
        raise SiteOutputError("followup_provenance_unverified")
    return record, snapshot


@dataclass(frozen=True)
class _Plan:
    objective: str
    variable: str
    baseline: int
    choices: tuple[int, ...]
    controls: tuple[str, ...]
    evidence: tuple[str, ...]
    finding: str
    revision: str
    compile: Callable[[int], PhonePreviewInput]

    def view(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "variable": self.variable,
            "baseline": self.baseline,
            "suggested": self.choices[0],
            "choices": self.choices,
            "controls": self.controls,
            "evidence": self.evidence,
            "finding": self.finding,
            "revision": self.revision,
            "job_count": 2,
        }


class PhoneFollowup:
    def __init__(self, repository: JobRepository, video: PhoneVideo) -> None:
        self._repository = repository
        self._video = video

    def suggest(
        self, catalog: SiteOutputCatalog, grant: PhoneGrant, body: dict[str, Any]
    ) -> dict[str, Any]:
        if body.keys() != {"scope", "source"} or body["scope"] != catalog.scope:
            raise SiteOutputError("invalid_followup")
        return self._plan(catalog, grant, body["source"]).view()

    def preview(
        self, catalog: SiteOutputCatalog, grant: PhoneGrant, body: dict[str, Any]
    ) -> PhonePreviewInput:
        if (
            body.keys() != {"kind", "scope", "source", "revision", "value", "reviewed"}
            or body["scope"] != catalog.scope
            or body["reviewed"] is not True
            or not _matches(_DIGEST, body["revision"])
            or type(body["value"]) is not int
        ):
            raise SiteOutputError("invalid_followup")
        plan = self._plan(catalog, grant, body["source"])
        if plan.revision != body["revision"]:
            raise SiteOutputError("followup_evidence_changed")
        if body["value"] not in plan.choices:
            raise SiteOutputError("invalid_followup_value")
        draft = plan.compile(body["value"])

        def require_current() -> None:
            draft.require_current()
            try:
                current = self._plan(catalog, grant, body["source"])
            except (SiteOutputError, ValueError, OSError) as exc:
                raise SiteOutputError("followup_evidence_changed") from exc
            if current.revision != plan.revision:
                raise SiteOutputError("followup_evidence_changed")

        return replace(draft, require_current=require_current)

    def _plan(self, catalog: SiteOutputCatalog, grant: PhoneGrant, raw: Any) -> _Plan:
        catalog.require_active()
        source = _checked_source(raw, grant)
        return (
            self._evaluation(catalog, source)
            if source["kind"] == "evaluation"
            else self._image(catalog, source)
        )

    def _image(self, catalog: SiteOutputCatalog, source: dict[str, str]) -> _Plan:
        review = catalog.native_review
        if review is None:
            raise SiteOutputError("phone_scope_refused")
        item, raw, digest = catalog.library.image(source["id"])
        if digest != source["digest"]:
            raise SiteOutputError("media_changed")
        path = catalog.library.path_for(item)
        if source["kind"] == "returned":
            resolver = catalog.review_outputs
            if resolver is None or not any(
                child["item"]["id"] == source["result_id"]
                and child["digest"] == source["result_digest"]
                for child in catalog.library.review_results(source["id"], digest, resolver)
            ):
                raise SiteOutputError("followup_provenance_unverified")
            finding = "The returned rework is observational evidence. Test steps on the source image’s original generation recipe."
            evidence_revision = source["result_digest"]
        else:
            rating = review.inspect(source["id"], digest)["rating"]
            if rating["score"] is None:
                raise SiteOutputError("followup_rating_required")
            finding = (
                f"Native Review score {rating['score']}/5. The score alone cannot identify a cause."
            )
            evidence_revision = rating["revision"]

        record, snapshot = verified_history_source(self._repository, path, raw)
        policy = resolve_policy(
            record.base_model, config={"backend_options": record.backend_options}
        )
        try:
            project_learning_capabilities(policy, record.base_model, "txt2img").require("steps")
        except ValueError as exc:
            raise SiteOutputError("followup_ineligible") from exc
        verified_policy = policy.qualified or (
            policy.family == "sdxl" and policy.evidence == EVIDENCE_REGISTRY
        )
        if not verified_policy or not 1 <= record.steps <= 150:
            raise SiteOutputError("followup_ineligible")
        baseline = record.steps
        choices = tuple(
            value
            for value in (baseline + 5, baseline - 5, baseline + 10, baseline - 10)
            if 1 <= value <= 150
        )
        objective = (
            "Does changing sampling steps improve the image’s Review score at the same seed?"
        )
        _validate_advice(objective, target=policy.policy_id)

        def compile_plan(value: int) -> PhonePreviewInput:
            draft = HistoryVariationDraft.from_source(record, parent_artifact_id=f"sha256:{digest}")
            jobs = tuple(
                replace(
                    compile_history_variation(draft.with_edits(steps=steps)),
                    output_plan=OutputPlan(str(catalog.library.root), filename_template="{seed}"),
                )
                for steps in (baseline, value)
            )
            return PhonePreviewInput("Image sampling steps follow-up", jobs, catalog.require_active)

        return _Plan(
            objective,
            "Sampling steps",
            baseline,
            choices,
            (
                f"Checkpoint {PureWindowsPath(record.base_model).name}",
                f"Seed {record.seed}",
                f"{record.width} × {record.height}",
                "Prompts, sampler, scheduler, CFG and remaining recipe settings",
            ),
            (
                "Two completed images with their recorded settings",
                "Review both outputs with the same scoring criteria",
            ),
            finding,
            fingerprint(
                [
                    catalog.scope,
                    source,
                    evidence_revision,
                    snapshot,
                    policy_context(policy, record.base_model, "txt2img"),
                    choices,
                ]
            ),
            compile_plan,
        )

    def _evaluation(self, catalog: SiteOutputCatalog, source: dict[str, str]) -> _Plan:
        run = catalog.get_run(source["run"], review=True)
        pair = {key: source[key] for key in ("case", "baseline", "candidate")}
        if pair not in run["pairs"]:
            raise SiteOutputError("followup_provenance_unverified")
        rows = [
            next(
                row
                for row in run["clips"]
                if row["case"] == source["case"] and row["arm_id"] == source[key]
            )
            for key in ("baseline", "candidate")
        ]
        blocks = []
        snapshots = []
        for row in rows:
            rating = row["rating"]
            if (
                rating.get(ARTIFACT_COLUMN) != row["artifact_sha256"]
                or not parse_rating_row(rating).complete
            ):
                raise SiteOutputError("followup_rating_required")
            clip, _status = catalog.verify_media(row["clip"])
            entry = self._repository.get_job(row["job_id"])
            if entry is None or entry.status is not JobStatus.COMPLETED or not entry.snapshot:
                raise SiteOutputError("followup_provenance_unverified")
            state, _reason, recorded_clip = classify_entry(entry)
            if (
                state is not ArmState.PLAYABLE
                or recorded_clip is None
                or Path(recorded_clip).absolute() != clip
            ):
                raise SiteOutputError("followup_provenance_unverified")
            record = normalized_job_from_snapshot(entry.snapshot)
            if record is None or record.job_id != row["job_id"]:
                raise SiteOutputError("followup_provenance_unverified")
            block = record.config.get("video_workflow")
            if not isinstance(block, Mapping) or not isinstance(
                block.get("source_preparation"), Mapping
            ):
                raise SiteOutputError("followup_provenance_unverified")
            blocks.append(thaw_json(block))
            snapshots.append(snapshot_fingerprint(entry.snapshot))
        baseline, candidate = blocks
        original, _status = catalog.verify_media(rows[0]["source"])
        if rows[0]["source_sha256"] != rows[1]["source_sha256"] or any(
            Path(str(block["source_preparation"].get("original_source_path", ""))).absolute()
            != original
            for block in blocks
        ):
            raise SiteOutputError("followup_provenance_unverified")
        workflow = str(baseline.get("workflow_id", "")), str(baseline.get("workflow_version", ""))
        spec = self._video.followup_workflow(workflow)
        frames = baseline.get("frame_count")
        seed = baseline.get("seed")
        prompt, negative = baseline.get("prompt"), baseline.get("negative_prompt")
        if (
            type(frames) is not int
            or frames not in legal_frame_counts(spec)
            or type(seed) is not int
            or not 0 <= seed < 2**31
            or not isinstance(prompt, str)
            or not 1 <= len(prompt.strip()) <= 2000
            or not isinstance(negative, str)
            or len(negative) > 1000
        ):
            raise SiteOutputError("followup_provenance_unverified")
        choices = tuple(
            sorted(
                (value for value in legal_frame_counts(spec) if value != frames),
                key=lambda value: (abs(value - frames), value),
            )
        )
        if not choices:
            raise SiteOutputError("followup_workflow_unavailable")
        dimensions = baseline["source_preparation"].get("target_dimensions")
        changes = [
            label
            for key, label in (
                ("workflow_id", "workflow"),
                ("workflow_version", "workflow version"),
                ("frame_count", "frame count"),
                ("fps", "FPS"),
                ("seed", "seed"),
                ("prompt", "motion prompt"),
                ("negative_prompt", "negative prompt"),
            )
            if baseline.get(key) != candidate.get(key)
        ]
        if dimensions != candidate["source_preparation"].get("target_dimensions"):
            changes.append("generation resolution")
        other_keys = set(baseline) | set(candidate)
        known_keys = {
            "workflow_id",
            "workflow_version",
            "frame_count",
            "fps",
            "seed",
            "prompt",
            "negative_prompt",
            "source_preparation",
        }
        mirrored = {"workflow_id", "workflow_version"}
        execution = [
            {
                key: value
                for key, value in block.get(VIDEO_EXECUTION_KEY, {}).items()
                if key not in mirrored
            }
            for block in blocks
        ]
        if execution[0] != execution[1] or any(
            baseline.get(key) != candidate.get(key)
            for key in other_keys - known_keys - {VIDEO_EXECUTION_KEY}
        ):
            changes.append("other execution settings")
        finding = (
            "The prior pair changed " + ", ".join(changes) + " together. It cannot isolate a cause."
            if len(changes) > 1
            else "The prior pair motivates a new comparison. Test frame count on one approved workflow."
        )
        objective = "Does a different frame count preserve subject identity and deliver the requested motion?"
        _validate_advice(objective, workflow=spec.workflow_id)
        with open_scoped(catalog.library.root, original) as stream, Image.open(stream) as image:
            size = image.size
        case = EvalCase("case-1", original, rows[0]["source_sha256"], prompt, negative)

        def compile_plan(value: int) -> PhonePreviewInput:
            return self._video.followup(catalog, case, size, spec, seed, (frames, value))

        return _Plan(
            objective,
            "Generation frame count",
            frames,
            choices,
            (
                f"{spec.display_name} {spec.workflow_version}",
                f"Seed {seed}",
                f"Graph {spec.pinned_revision}",
                "Source image, prompts, generation resolution, model and FPS",
            ),
            (
                "Two playable clips linked to the same verified source",
                "Blind ratings for identity and requested motion",
            ),
            finding,
            fingerprint(
                [
                    catalog.scope,
                    source,
                    snapshots,
                    [
                        {
                            key: row[key]
                            for key in ("job_id", "source_sha256", "artifact_sha256", "rating")
                        }
                        for row in rows
                    ],
                    spec.pinned_revision,
                    choices,
                ]
            ),
            compile_plan,
        )
