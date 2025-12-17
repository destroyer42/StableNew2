from __future__ import annotations

from src.utils.snapshot_builder_v2 import build_job_snapshot, normalized_job_from_snapshot
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


def test_snapshot_preserves_pack_metadata() -> None:
    njr = make_test_njr(
        prompt_pack_id="pack-abc", prompt_pack_name="Pack ABC", prompt_source="pack"
    )
    job = make_test_job_from_njr(njr, prompt_source="pack")

    snapshot = build_job_snapshot(job, njr, run_config={"prompt_source": "pack"})
    reconstructed = normalized_job_from_snapshot(snapshot)

    assert reconstructed is not None
    assert reconstructed.prompt_source == "pack"
    assert reconstructed.prompt_pack_id == "pack-abc"
    assert reconstructed.prompt_pack_name == "Pack ABC"


def test_legacy_snapshot_mode_flag() -> None:
    njr = make_test_njr(prompt_pack_id="", prompt_source="pack")
    job = make_test_job_from_njr(njr, prompt_source="pack")

    snapshot = build_job_snapshot(job, njr, run_config={"prompt_source": "pack"})
    reconstructed = normalized_job_from_snapshot(snapshot)

    assert reconstructed is not None
    assert reconstructed.extra_metadata.get("legacy_snapshot_mode") in {True, False}
