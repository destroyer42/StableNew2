"""N5: packs x models batch - real compiler, exact totals, one named batch through JobService.submit_njrs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller_services import pack_model_batch_service as batch
from src.controller.app_controller_services.gui_config_service import PackDraftConfig
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.image_backends import model_policy_warnings as mpw
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.policy_warnings import CODE_IMAGE_MODEL_UNQUALIFIED, PolicyWarning
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.file_io import read_prompt_pack
from src.utils.prompt_packs import PromptPackInfo
from tests.controller.test_job_service_unit import FakeRunner
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)

MODELS = ("juggernautXL_v9.safetensors [a1b2c3d4e5]", "ponyDiffusion_v6.safetensors")


class Harness:
    def __init__(self, tmp_path: Path, *, pipeline: dict[str, Any] | None = None) -> None:
        self.config_manager = StubConfigManager(tmp_path)
        self.packs = {
            name: PromptPackInfo(
                name=name,
                path=_write_native_pack(self.config_manager.packs_dir / f"{name}.json", text=text),
            )
            for name, text in (
                ("castles", "a castle on a hill"),
                ("portraits", "a portrait of a knight"),
            )
        }
        self.builder = PromptPackNormalizedJobBuilder(
            config_manager=self.config_manager,
            job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
            packs_dir=self.config_manager.packs_dir,
        )
        base_config = copy.deepcopy(BASE_PACK_CONFIG)
        base_config["pipeline"].update(pipeline or {})
        self.base = batch.BatchBase(
            draft_config=PackDraftConfig(
                base_config=base_config,
                global_prompt_policy={
                    "positive_enabled": False,
                    "positive_text": "",
                    "negative_enabled": False,
                    "negative_text": "",
                },
                stage_overrides=None,
            ),
            stage_flags={"txt2img": True, "img2img": False, "adetailer": False, "upscale": False},
            randomizer_metadata={"enabled": False, "max_variants": 0},
        )
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.service = JobService(
            JobQueue(repository=self.repository),
            runner=FakeRunner(),
            require_normalized_records=True,
        )
        self.submit_calls: list[int] = []
        original = self.service.submit_njrs

        def spy(records, policy):  # type: ignore[no-untyped-def]
            self.submit_calls.append(len(records))
            return original(records, policy)

        self.service.submit_njrs = spy  # type: ignore[method-assign]
        controller = object.__new__(PipelineController)
        controller._job_service = self.service
        controller._app_controller = None
        controller.can_enqueue_learning_jobs = lambda _count: (True, "")
        controller._is_queue_submission_blocked = lambda: False
        controller._sort_jobs_by_model = lambda rows: rows
        self.app = SimpleNamespace(pipeline_controller=controller)

    def sources(self, *names: str) -> list[batch.PackSource]:
        return [
            batch.PackSource(
                name, self.packs[name], {}, tuple(read_prompt_pack(self.packs[name].path))
            )
            for name in names
        ]

    def plan(
        self, request: batch.BatchRequest, compile_entries=None, stats=None
    ) -> batch.BatchPlan:
        cells = batch.compile_cells(
            request,
            self.base,
            self.sources(*request.pack_ids),
            compile_entries or self.builder.build_jobs,
        )
        return batch.build_plan(request, cells, stats)

    def queued(self) -> list[Any]:
        return [job._normalized_record for job in self.repository.list_job_models()]


def _request(**kwargs: Any) -> batch.BatchRequest:
    values = {"name": "night run", "pack_ids": ("castles", "portraits"), "models": MODELS}
    values.update(kwargs)
    return batch.BatchRequest(**values)


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_every_pack_compiles_once_per_model_with_only_the_checkpoint_changed(harness: Harness):
    plan = harness.plan(_request())

    assert [(cell.pack_id, cell.model) for cell in plan.cells] == [
        ("castles", MODELS[0]),
        ("castles", MODELS[1]),
        ("portraits", MODELS[0]),
        ("portraits", MODELS[1]),
    ]
    assert all(not cell.problem and cell.jobs == 1 for cell in plan.cells)
    for cell in plan.cells:
        (record,) = cell.records
        assert record.base_model == cell.model
        assert record.steps == BASE_PACK_CONFIG["txt2img"]["steps"]
        assert record.config["model"] == cell.model
    assert plan.jobs == 4 and plan.images == 4


def test_totals_count_what_queue_will_submit(tmp_path: Path):
    harness = Harness(tmp_path, pipeline={"images_per_prompt": 3, "loop_count": 2})
    plan = harness.plan(_request())

    assert plan.jobs == len(plan.records) == 8  # 2 packs x 2 models x 2 runs
    assert plan.images == 24  # 3 images per run
    assert batch.submit_batch(harness.app, plan, batch_id="b-1") == 8
    assert len(harness.queued()) == plan.jobs


def test_queue_is_one_admission_and_every_job_records_its_batch_and_cell(harness: Harness):
    plan = harness.plan(_request())

    assert batch.submit_batch(harness.app, plan, batch_id="batch-42") == 4
    assert harness.submit_calls == [4]
    stored = harness.queued()
    identities = [batch.batch_identity(record) for record in stored]
    assert {identity["batch_id"] for identity in identities} == {"batch-42"}
    assert {identity["name"] for identity in identities} == {"night run"}
    assert {(i["cell"]["pack_id"], i["cell"]["model_key"]) for i in identities} == {
        ("castles", "juggernautxl_v9"),
        ("castles", "ponydiffusion_v6"),
        ("portraits", "juggernautxl_v9"),
        ("portraits", "ponydiffusion_v6"),
    }
    assert all(identity["cells"] == 4 and identity["jobs"] == 4 for identity in identities)
    # The reader works on a stored snapshot too (the phone gateway reads snapshots, not live records).
    snapshot = json.loads(json.dumps({"normalized_job": stored[0].to_dict()}))
    assert batch.batch_identity(snapshot) == identities[0]


def test_the_stamp_changes_provenance_only(harness: Harness):
    plan = harness.plan(_request(pack_ids=("castles",), models=MODELS[:1]))
    (record,) = plan.records
    (stamped,) = batch.stamp_batch(plan, "b")

    assert stamped.job_id == record.job_id
    assert stamped.config == record.config
    assert batch.batch_identity(record) is None
    before = {k: v for k, v in stamped.extra_metadata.items() if k != batch.BATCH_METADATA_KEY}
    assert before == record.extra_metadata


def test_a_cell_that_cannot_compile_is_listed_and_the_rest_still_queue(harness: Harness):
    def compile_entries(entries):  # type: ignore[no-untyped-def]
        if entries[0].config_snapshot["txt2img"]["model"] == MODELS[1]:
            raise ValueError("This checkpoint needs a LoRA selection review; use the Pipeline tab.")
        return harness.builder.build_jobs(entries)

    plan = harness.plan(_request(), compile_entries)

    blocked = [cell for cell in plan.cells if cell.problem]
    assert [(cell.pack_id, cell.model) for cell in blocked] == [
        ("castles", MODELS[1]),
        ("portraits", MODELS[1]),
    ]
    assert plan.jobs == 2 and plan.queueable
    text = "\n".join(plan.summary_lines())
    assert "not queued. This checkpoint needs a LoRA selection review" in text
    assert batch.submit_batch(harness.app, plan, batch_id="b") == 2


def test_an_unreadable_pack_is_one_reported_row(harness: Harness):
    sources = [
        batch.PackSource("gone", problem="The PromptPack was not found."),
        *harness.sources("castles"),
    ]
    cells = batch.compile_cells(
        _request(pack_ids=("gone", "castles")), harness.base, sources, harness.builder.build_jobs
    )
    assert [cell.problem for cell in cells if cell.pack_id == "gone"] == [
        "The PromptPack was not found."
    ] * 2
    assert sum(cell.jobs for cell in cells) == 2


def test_n1_warnings_show_once_and_are_frozen_on_every_job(harness: Harness):
    warning = PolicyWarning(
        CODE_IMAGE_MODEL_UNQUALIFIED,
        "ponyDiffusion_v6",
        "Unqualified model",
        "No profile.",
        "Pick a module.",
    )
    mpw.publish_shown_warnings({MODELS[1]: warning})
    try:
        plan = harness.plan(_request())
        assert plan.warnings == (warning,)
        assert "\n".join(plan.summary_lines()).count(warning.text()) == 1
        batch.submit_batch(harness.app, plan, batch_id="b")
    finally:
        mpw.publish_shown_warnings({})
    accepted = {
        record.base_model: [
            item["code"] for item in record.extra_metadata.get("accepted_warnings", [])
        ]
        for record in harness.queued()
    }
    assert accepted[MODELS[1]] == [CODE_IMAGE_MODEL_UNQUALIFIED]
    assert accepted[MODELS[0]] == []


def test_stage_choices_apply_to_every_cell(harness: Harness):
    plan = harness.plan(_request(pack_ids=("castles",), adetailer=True))
    for cell in plan.cells:
        (record,) = cell.records
        assert "adetailer" in record.stage_chain_labels


def test_eta_uses_recent_history_and_says_where_each_part_came_from(harness: Harness):
    class Stats:
        def get_estimate_for_chain(self, chain):  # type: ignore[no-untyped-def]
            return 90.0 if tuple(chain) == ("txt2img",) else None

    plan = harness.plan(_request(), stats=Stats())
    assert plan.eta_seconds == 360.0 and plan.eta_jobs_from_history == 4
    assert "about 6 min" in plan.summary_lines()[1]

    defaults = harness.plan(_request())
    assert defaults.eta_jobs_from_history == 0 and defaults.eta_seconds == 4 * 30.0
    assert any("per-stage defaults" in line for line in defaults.summary_lines())


def test_request_problems_and_default_name():
    assert batch.BatchRequest("x", (), ()).problems() == [
        "Pick at least one PromptPack.",
        "Pick at least one model.",
    ]
    duplicate = batch.BatchRequest("x", ("p",), ("sdxl\\m.safetensors [abc]", "M"))
    assert duplicate.problems() == ["The same model is picked twice."]
    from datetime import date

    assert batch.default_batch_name(["castles", "portraits"], 3, today=date(2026, 11, 26)) == (
        "2026-11-26 castles +1 x 3 model(s)"
    )


def test_request_batch_plan_captures_on_the_calling_thread_and_compiles_in_the_background(
    harness: Harness,
):
    submitted: list[tuple[str, Any]] = []
    app = SimpleNamespace(
        _capture_pack_draft_config=lambda: harness.base.draft_config,
        _build_stage_flags=lambda: dict(harness.base.stage_flags),
        _build_randomizer_metadata=lambda: dict(harness.base.randomizer_metadata),
        _background_tasks=SimpleNamespace(
            submit=lambda key, work, **kwargs: submitted.append((key, work))
        ),
    )
    errors: list[Exception] = []
    batch.request_batch_plan(app, _request(), on_result=lambda _plan: None, on_error=errors.append)
    assert [key for key, _work in submitted] == [
        "batch:plan"
    ] and not errors  # nothing compiled yet

    batch.request_batch_plan(
        app, batch.BatchRequest("x", (), MODELS), on_result=lambda _p: None, on_error=errors.append
    )
    assert len(submitted) == 1 and "Pick at least one PromptPack." in str(errors[0])
