"""GUI-540 end-to-end logical contract: authored template + LoRA + style -> save/reload -> canonical compile -> admission.

Synthetic data only. The authoring helpers are the same pure functions the Prompt tab calls; the compile and admission
steps are the existing canonical ones, so this proves the redesigned controls change no prompt semantics.
"""

from __future__ import annotations

from pathlib import Path

from src.controller.job_service import JobService
from src.gui.app_state_v2 import PackJobEntry
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui_v2.lora_authoring_view import plan_trigger_insertion
from src.gui_v2.prompt_template_view import seed_template_values
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.queue.job_queue import JobQueue
from src.training.style_lora_manager import StyleLoRAManager
from src.utils.config import ConfigManager
from src.utils.prompt_templates import compose_prompt_text, load_prompt_templates
from tests.controller.test_job_service_njr_submission import _Runner
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    _write_style_catalog,
)

STYLE_PHRASE = "cinematic grit lighting"


def _author_pack(packs_dir: Path) -> Path:
    state = PromptWorkspaceState()
    state.new_pack("authored_pack", slot_count=2)
    definition = load_prompt_templates()["establishing_wide"]
    values, seeded = seed_template_values(definition, {"scene": "a lone lighthouse keeper"})
    assert seeded and values["scene"] == "a lone lighthouse keeper"
    state.set_slot_template(0, definition.id, values)
    state.set_slot_text(0, "rain on the cobblestones")
    plan = plan_trigger_insertion(
        state.get_current_prompt_text(), ["sunlit film grain", STYLE_PHRASE], [STYLE_PHRASE]
    )
    assert plan.inserted == ("sunlit film grain",) and plan.auto_applied == (STYLE_PHRASE,)
    state.set_slot_text(0, plan.new_text(state.get_slot(0).text))
    state.set_slot_loras(0, [("pack_style", 0.45)])
    state.set_slot_text(1, "an untouched second slot")
    preset = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in BASE_PACK_CONFIG.items()
    }
    preset["txt2img"]["model"] = "juggernautXL.safetensors"
    preset["style_lora"] = {"enabled": True, "style_id": "cinematic_grit"}
    state.current_pack.preset_data = preset
    return (
        state.save_current_pack_as(packs_dir / "authored_pack.json")
        or packs_dir / "authored_pack.json"
    )


def test_authored_template_lora_and_style_survive_save_compile_and_admission(
    tmp_path: Path,
) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack_path = _author_pack(packs_dir)

    reloaded = PromptWorkspaceState()
    reloaded.load_pack(pack_path)
    slot = reloaded.get_slot(0)
    assert (
        slot.template_id == "establishing_wide"
        and slot.template_variables["scene"] == "a lone lighthouse keeper"
    )
    assert slot.text == "rain on the cobblestones, sunlit film grain"
    assert slot.loras == [("pack_style", 0.45)]
    assert reloaded.get_pack_style_lora_config() == {"enabled": True, "style_id": "cinematic_grit"}
    authored = compose_prompt_text(slot.template_id, slot.template_variables, slot.text)
    assert reloaded.get_current_prompt_text() == authored

    catalog_path, _weight = _write_style_catalog(tmp_path)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs_dir),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=packs_dir,
        style_lora_manager=StyleLoRAManager(catalog_path=catalog_path, webui_root=None),
    )
    entry = PackJobEntry(
        pack_id=pack_path.name,
        pack_name="authored_pack",
        config_snapshot={"style_lora": reloaded.get_pack_style_lora_config()},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert len(records) == 1
    record = records[0]
    assert authored in record.positive_prompt  # the editor's authored preview is what compiles
    assert record.positive_prompt.count("sunlit film grain") == 1
    assert (
        record.positive_prompt.count(STYLE_PHRASE) == 1
    )  # the automatic style trigger is applied exactly once
    assert [(tag.name, tag.weight) for tag in record.lora_tags] == [
        ("pack_style", 0.45),
        ("style_cinematic_grit", 0.65),
    ]
    assert record.extra_metadata["style_lora"]["applied"] is True

    queue = JobQueue()
    service = JobService(queue, runner=_Runner(queue))
    job_ids = service.submit_njrs(records)
    admitted = queue.get_job(job_ids[0])
    assert admitted is not None and admitted.snapshot is not None
    snapshot = admitted.snapshot
    assert snapshot["effective_prompts"]["positive"] == record.positive_prompt
    assert snapshot["normalized_job"]["workload"]["positive_prompt"] == record.positive_prompt
    frozen_tags = snapshot["normalized_job"]["provenance"]["lora_tags"]
    assert [(tag["name"], tag["weight"]) for tag in frozen_tags] == [
        (tag.name, tag.weight) for tag in record.lora_tags
    ]
    assert (
        snapshot["normalized_job"]["workload"]["metadata"]["style_lora"]["trigger_phrase"]
        == STYLE_PHRASE
    )


def test_an_unavailable_saved_style_compiles_as_inactive_without_editing_the_pack(
    tmp_path: Path,
) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack_path = _author_pack(packs_dir)
    before = pack_path.read_bytes()
    catalog_path, _weight = _write_style_catalog(tmp_path, missing_file=True)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs_dir),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=packs_dir,
        style_lora_manager=StyleLoRAManager(catalog_path=catalog_path, webui_root=None),
    )
    entry = PackJobEntry(
        pack_id=pack_path.name,
        pack_name="authored_pack",
        config_snapshot={"style_lora": {"enabled": True, "style_id": "cinematic_grit"}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    record = builder.build_jobs([entry])[0]

    assert STYLE_PHRASE not in record.positive_prompt
    assert [tag.name for tag in record.lora_tags] == ["pack_style"]
    assert record.extra_metadata["style_lora"]["applied"] is False
    assert pack_path.read_bytes() == before  # compiling never rewrites the authored pack
