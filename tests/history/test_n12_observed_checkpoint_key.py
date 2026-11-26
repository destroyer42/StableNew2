"""N12: N1b "ran N times here" matches on the canonical checkpoint key, whatever spelling the job or picker used."""

from __future__ import annotations

from pathlib import Path

import pytest

import src.history.observed_execution as oe
from src.image_backends import sdxl_target as st
from src.queue.job_repository import JobRepository
from src.utils.checkpoint_identity import checkpoint_key
from tests.history.test_n1b_observed_execution import _seed, _snapshot

PICKER_COLLISION_LABEL = "juggernautXL_v9 [juggernautXL_v9.safetensors [a1b2c3d4e5]]"


def test_runs_carry_the_canonical_key():
    for model in (
        "sdxl\\juggernautXL_v9.safetensors [abc]",
        PICKER_COLLISION_LABEL,
        "JuggernautXL_v9",
    ):
        (run,) = oe.runs_in_snapshot(_snapshot(model))
        assert run.model_key == checkpoint_key(model) == "juggernautxl_v9"


def test_the_needle_of_a_picker_collision_label_names_the_internal_file():
    assert oe.needle_for(PICKER_COLLISION_LABEL) == "juggernautXL_v9"


@pytest.fixture
def repository(tmp_path: Path) -> JobRepository:
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(
        repo,
        [
            ("j1", "sdxl/JuggernautXL_v9.safetensors", "completed"),
            ("j2", "juggernautXL_v9.safetensors [a1b2c3d4e5]", "completed"),
            ("j3", "juggernaut_xl_v9_other.safetensors", "completed"),
            ("j4", "100%_real_v1.safetensors", "completed"),
            ("j5", "100x_real_v1.safetensors", "completed"),
        ],
    )
    return repo


def test_a_differently_cased_job_still_counts(repository: JobRepository):
    runs = oe.read_observed_runs(oe.repository_reader(repository), "juggernautXL_v9.safetensors")
    assert [run.operation for run in runs] == [st.OP_TXT2IMG, st.OP_TXT2IMG]
    runs = oe.read_observed_runs(oe.repository_reader(repository), PICKER_COLLISION_LABEL)
    assert len(runs) == 2


def test_like_wildcards_in_a_name_are_literal(repository: JobRepository):
    snapshots, _cursor, _exhausted = repository.read_completed_snapshots_mentioning("100%_real")
    assert len(snapshots) == 1
    runs = oe.read_observed_runs(oe.repository_reader(repository), "100%_real_v1.safetensors")
    assert {run.model_key for run in runs} == {"100%_real_v1"}
