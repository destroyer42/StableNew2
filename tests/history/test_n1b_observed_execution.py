"""N1b observed-execution evidence: completed repository jobs, per checkpoint, operation and backend; bounded and
read-only, never on the calling thread."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import src.history.observed_execution as oe
from src.image_backends import sdxl_target as st
from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_model import Job
from src.queue.job_repository import JobRepository

SHA_A = "a" * 64
SHA_B = "b" * 64


def _snapshot(
    model: str = "juggernautXL_v9.safetensors [abc]",
    *,
    stages=("txt2img",),
    backend: str | None = "forge_webui",
    config: dict | None = None,
    provenance: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    workload = {"config": dict(config or {}), "metadata": dict(metadata or {})}
    if backend is not None:
        workload["backend_options"] = {"image": {"backend_id": backend}}
    return {
        "normalized_job": {
            "stages": [{"stage_type": kind, "enabled": True, "model": model} for kind in stages],
            "workload": workload,
            "provenance": dict(provenance or {}),
        }
    }


def _ops(snapshot: dict) -> set[tuple[str, str, str]]:
    return {(run.model_key, run.operation, run.backend_id) for run in oe.runs_in_snapshot(snapshot)}


def test_operations_are_derived_at_capability_level_from_the_stored_njr():
    key = "juggernautxl_v9"
    assert _ops(_snapshot()) == {(key, st.OP_TXT2IMG, "forge_webui")}
    rich = _snapshot(
        stages=("txt2img", "adetailer"),
        provenance={"positive_embeddings": ["easynegative"], "lora_tags": [{"name": "x", "weight": 1}]},
        config={
            "controlnet_units": {"units": [{"enabled": True, "modality": "canny"}, {"enabled": False, "modality": "depth"}]},
            "controlnet_openpose": {"enabled": True},
            "adetailer": {"adetailer_checkpoint_model": "fix.safetensors"},
        },
    )  # fmt: skip
    assert _ops(rich) == {
        (key, st.OP_TXT2IMG, "forge_webui"),
        (key, st.OP_TXT2IMG_EMBEDDING, "forge_webui"),
        (key, st.OP_TXT2IMG_LORA, "forge_webui"),
        (key, st.controlnet_operation("canny"), "forge_webui"),  # per modality (owner decision Q2)
        (key, st.controlnet_operation("openpose"), "forge_webui"),
        ("fix", st.OP_ADETAILER, "forge_webui"),
    }
    masked = _snapshot(stages=("img2img",), config={"img2img": {"image_edit_inputs": {}}})
    outpaint = _snapshot(
        stages=("img2img",),
        config={"img2img": {"image_edit_inputs": {}, "edit_operation": "outpaint"}},
    )
    assert _ops(masked) == {(key, st.OP_MASKED_INPAINT, "forge_webui")}
    assert _ops(outpaint) == {(key, st.OP_OUTPAINT, "forge_webui")}
    assert _ops(_snapshot(stages=("img2img",))) == {(key, st.OP_IMG2IMG, "forge_webui")}
    # A persisted record with no backend identity is the legacy A1111 default, never the new-work default.
    assert _ops(_snapshot(backend=None)) == {(key, st.OP_TXT2IMG, "a1111_webui")}
    assert oe.runs_in_snapshot({"normalized_job": {"stages": "garbage"}}) == ()


def test_a_recorded_checkpoint_sha256_travels_with_the_run():
    arm = {
        "model_comparison": {
            "checkpoint_evidence": {"authority": "asset_registry", "sha256": SHA_A.upper()}
        }
    }
    (run,) = oe.runs_in_snapshot(_snapshot(metadata=arm))
    assert run.sha256 == SHA_A


def test_the_needle_matches_the_stored_json_text_of_the_name():
    assert oe.needle_for("C:/models/juggernautXL_v9.safetensors [abc]") == "juggernautXL_v9"
    assert oe.needle_for("café.ckpt") == "caf\\u00e9"


# -- the repository reader --------------------------------------------------------------------------------------


def _job(job_id: str, model: str) -> Job:
    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {"model": model, "steps": 4, "cfg_scale": 5.0, "width": 64, "height": 64}
        },
    )
    record = replace(record, job_id=job_id)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


def _seed(repository: JobRepository, rows: list[tuple[str, str, str]]) -> None:
    for job_id, model, status in rows:
        repository.record_job_submission(_job(job_id, model))
        with repository.transaction() as connection:
            connection.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))


@pytest.fixture
def repository(tmp_path: Path) -> JobRepository:
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(
        repo,
        [
            ("j1", "seen.safetensors", "completed"),
            ("j2", "seen.safetensors", "failed"),
            ("j3", "other.safetensors", "completed"),
            ("j4", "seen.safetensors", "completed"),
            ("j5", "seen.safetensors", "queued"),
        ],
    )
    return repo


def test_only_completed_jobs_naming_the_checkpoint_are_read(repository: JobRepository):
    snapshots, cursor, exhausted = repository.read_completed_snapshots_mentioning("seen")
    assert exhausted and cursor == 0 and len(snapshots) == 2
    assert all("seen.safetensors" in json.dumps(json.loads(text)) for text in snapshots)
    runs = oe.read_observed_runs(oe.repository_reader(repository), "seen.safetensors")
    assert len(runs) == 2 and {run.model_key for run in runs} == {"seen"}


def test_the_read_is_bounded_by_rows_and_matches(repository: JobRepository):
    reader = oe.repository_reader(repository)
    assert len(oe.read_observed_runs(reader, "seen.safetensors", max_matches=1)) == 1
    # The newest window (rowids 4..5) holds one completed match; the bound stops before older rows.
    assert len(oe.read_observed_runs(reader, "seen.safetensors", max_rows=2, window=2)) == 1


def test_an_in_memory_repository_reads_under_its_lock_and_is_never_installed():
    memory = JobRepository(":memory:")
    _seed(memory, [("m1", "seen.safetensors", "completed")])
    assert len(memory.read_completed_snapshots_mentioning("seen")[0]) == 1
    assert oe.install_for_repository(memory) is None


# -- the non-blocking index -------------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _index(reader, *, spawn=None, current_sha=None, clock=None):
    pending: list = []
    index = oe.ObservedExecutionIndex(
        reader,
        current_sha=current_sha,
        spawn=spawn or pending.append,
        clock=clock or _Clock(),
    )
    return index, pending


def test_a_lookup_never_reads_on_the_calling_thread(repository: JobRepository):
    index, pending = _index(oe.repository_reader(repository))
    assert index.runs("seen.safetensors", st.OP_TXT2IMG, "forge_webui") == 0  # nothing read yet
    assert len(pending) == 1  # one background read scheduled
    assert index.runs("seen.safetensors", st.OP_TXT2IMG, "forge_webui") == 0
    assert len(pending) == 1  # not scheduled twice while it is pending
    pending.pop()()  # the worker runs
    # ``build_cli_njr`` records the Forge backend identity.
    assert index.runs("seen.safetensors", st.OP_TXT2IMG, "forge_webui") == 2
    assert index.runs("seen.safetensors", st.OP_TXT2IMG, "a1111_webui") == 0
    assert index.runs("seen.safetensors", st.OP_TXT2IMG_LORA, "forge_webui") == 0


def test_a_stale_answer_is_re_read_after_the_ttl(repository: JobRepository):
    clock = _Clock()
    index, pending = _index(oe.repository_reader(repository), clock=clock)
    index.runs("seen.safetensors", st.OP_TXT2IMG, "forge_webui")
    pending.pop()()
    clock.now = oe.TTL_SECONDS + 1
    assert (
        index.runs("seen.safetensors", st.OP_TXT2IMG, "forge_webui") == 2
    )  # the old answer, then a refresh
    assert len(pending) == 1


def test_a_different_recorded_sha256_does_not_count():
    arm = {"model_comparison": {"checkpoint_evidence": {"sha256": SHA_A}}}
    text = json.dumps(_snapshot("seen.safetensors", metadata=arm))

    def reader(_needle, _before, _window):
        return [text], 0, True

    same, pending = _index(reader, current_sha=lambda _name: SHA_A)
    same.runs("seen", st.OP_TXT2IMG, "forge_webui")
    pending.pop()()
    assert same.runs("seen", st.OP_TXT2IMG, "forge_webui") == 1
    changed, pending = _index(reader, current_sha=lambda _name: SHA_B)
    changed.runs("seen", st.OP_TXT2IMG, "forge_webui")
    pending.pop()()
    assert changed.runs("seen", st.OP_TXT2IMG, "forge_webui") == 0


def test_a_failing_repository_or_spawn_is_absent_evidence():
    def broken(*_args):
        raise OSError("disk unavailable")

    index, pending = _index(broken)
    index.runs("seen", st.OP_TXT2IMG, "forge_webui")
    pending.pop()()
    assert index.runs("seen", st.OP_TXT2IMG, "forge_webui") == 0

    def no_threads(_target):
        raise RuntimeError("shutting down")

    refused = oe.ObservedExecutionIndex(broken, spawn=no_threads)
    assert refused.runs("seen", st.OP_TXT2IMG, "forge_webui") == 0
    assert refused._pending == set()  # the next lookup may try again


def test_the_installed_index_feeds_every_gate(repository: JobRepository, monkeypatch):
    monkeypatch.setattr(oe, "_INDEX", None)
    assert oe.observed_runs_lookup() is None
    index = oe.install_for_repository(repository)
    assert index is not None and oe.observed_runs_lookup() == index.runs
    index.spawn = lambda target: target()  # synchronous for the test
    lookup = oe.observed_runs_lookup()
    lookup("seen.safetensors", st.OP_TXT2IMG, "forge_webui")
    target = st.assess_sdxl_target(
        _unknown(),
        model="seen.safetensors", operation=st.OP_TXT2IMG, backend_id="forge_webui",
        feature="Prompt Slot", observed=lookup,
    )  # fmt: skip
    assert target.status is st.TargetStatus.OBSERVED and target.observed_runs == 2


def _unknown():
    from src.image_backends.model_policy import resolve_model_policy

    return resolve_model_policy("seen.safetensors")
