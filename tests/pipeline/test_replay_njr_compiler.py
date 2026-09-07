from __future__ import annotations

from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from tests.helpers.job_helpers import make_test_njr


def test_replay_compiler_assigns_new_identity_and_parent_lineage() -> None:
    original = make_test_njr(job_id="original", prompt_source="manual", prompt_pack_id="")

    replay = compile_replay_intent(ReplayIntent(original), id_fn=lambda: "replay-1")

    assert replay.job_id == "replay-1"
    assert replay.source.kind.value == "history_replay"
    assert replay.source.parent_job_id == "original"
    assert replay.provenance.metadata["parent_job_id"] == "original"
    assert replay.to_dict()["workload"] == original.to_dict()["workload"]
