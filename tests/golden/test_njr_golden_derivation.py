"""P4-2A golden NJRs for the derivation routes that re-identify an existing record (assessment sites V1 and V2).

Replay of a PromptPack parent that belonged to a batch (its active batch keys move, inert, under ``replay_origin``),
and the history variation compiler on a PromptPack-built parent.  Ids are injected through ``id_fn``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.batch_membership import build_selected_retry_descriptor
from tests.golden.test_njr_golden_generation import _entry, _pack_builder
from tests.golden.test_njr_golden_p4_2 import assert_golden
from tests.pipeline.test_history_variation_compiler_610a import _source as variation_source
from tests.pipeline.test_prompt_pack_job_builder import _write_native_pack


def prompt_pack_parent(tmp_path: Path) -> NormalizedJobRecord:
    builder, manager = _pack_builder(tmp_path)
    pack = _write_native_pack(manager.packs_dir / "parent-pack.json", text="A knight at dawn")
    (record,) = builder.build_jobs([_entry(pack, prompt_text="A knight at dawn")])
    return record


def test_replay_of_a_prompt_pack_parent_that_belonged_to_a_batch(tmp_path: Path) -> None:
    parent = prompt_pack_parent(tmp_path)
    metadata = {
        **thaw_json(parent.provenance.metadata),
        "batch": build_selected_retry_descriptor("batch-old", source_index=1, source_count=3),
        "batch_id": "batch-old",
    }
    member = replace(parent, provenance=replace(parent.provenance, metadata=metadata))
    plain = compile_replay_intent(ReplayIntent(member), id_fn=lambda: "replay-plain")
    retried = compile_replay_intent(
        ReplayIntent(
            member,
            parent_artifact_id="artifact-1",
            batch=build_selected_retry_descriptor("batch-new", source_index=0, source_count=2),
        ),
        id_fn=lambda: "replay-retry",
    )
    assert "replay_origin" in plain.extra_metadata
    assert_golden(
        "replay_prompt_pack_batch_parent",
        {"parent": member.to_dict(), "plain": plain.to_dict(), "selected_retry": retried.to_dict()},
        tmp_path,
    )


def test_history_variation_of_a_prompt_pack_parent(tmp_path: Path) -> None:
    source = variation_source()
    draft = HistoryVariationDraft.from_source(source, parent_artifact_id="artifact-2").with_edits(
        positive_prompt="a blue fox, <lora:fox:0.8>",
        negative_prompt="ugly",
        seed=77,
        steps=45,
        cfg_scale=8.0,
    )
    unchanged = HistoryVariationDraft.from_source(source)
    assert_golden(
        "history_variation",
        {
            "source": source.to_dict(),
            "edited": compile_history_variation(draft, id_fn=lambda: "variation-1").to_dict(),
            "unchanged": compile_history_variation(
                unchanged, id_fn=lambda: "variation-2"
            ).to_dict(),
        },
        tmp_path,
    )
