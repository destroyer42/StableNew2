from __future__ import annotations

from src.controller.pipeline_controller import PipelineController
from src.pipeline.executor import Pipeline
from src.pipeline.global_prompt_policy import (
    FROZEN_POLICY_SOURCE,
    apply_global_prompt_policy,
    has_frozen_global_prompt_policy,
)
from src.utils import StructuredLogger
from src.utils.config import ConfigManager
from tests.helpers.global_prompt_isolation import real_global_prompt_store_untouched  # noqa: F401


def test_policy_freezes_text_and_all_existing_negative_stage_flags() -> None:
    config = apply_global_prompt_policy(
        {"pipeline": {"txt2img_enabled": True}},
        positive_enabled=True,
        positive_text=" cinematic ",
        negative_enabled=False,
        negative_text=" watermark ",
    )

    assert has_frozen_global_prompt_policy(config)
    assert config["global_positive_prompt"] == "cinematic"
    assert config["global_negative_prompt"] == "watermark"
    assert config["global_prompt_policy_source"] == FROZEN_POLICY_SOURCE
    assert config["pipeline"] == {
        "txt2img_enabled": True,
        "apply_global_positive_txt2img": True,
        "apply_global_negative_txt2img": False,
        "apply_global_negative_img2img": False,
        "apply_global_negative_adetailer": False,
        "apply_global_negative_upscale": False,
    }


def test_executor_prefers_frozen_terms_over_mutable_config_manager() -> None:
    pipeline = Pipeline(object(), StructuredLogger())
    pipeline.config_manager.get_global_positive_prompt = lambda: "runtime-positive"
    pipeline.config_manager.get_global_negative_prompt = lambda: "runtime-negative"
    config = apply_global_prompt_policy(
        {},
        positive_enabled=True,
        positive_text="frozen-positive",
        negative_enabled=True,
        negative_text="frozen-negative",
    )

    assert pipeline._global_prompt_terms(config, "global_positive_prompt") == (
        "frozen-positive",
        FROZEN_POLICY_SOURCE,
    )
    assert pipeline._global_prompt_terms(config, "global_negative_prompt") == (
        "frozen-negative",
        FROZEN_POLICY_SOURCE,
    )


def test_frozen_executor_policy_never_reads_the_mutable_global_prompt_store(
    tmp_path, monkeypatch
) -> None:
    store = tmp_path / "global-prompts"
    store.mkdir()
    for name in ("global_positive.txt", "global_negative.txt"):
        (store / name).write_text("MUTABLE-STORE-SENTINEL", encoding="utf-8")
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=store,
    )
    pipeline = Pipeline(object(), StructuredLogger())
    pipeline.config_manager = manager
    reads: list[str] = []
    real_read_text = type(store).read_text

    def spy_read_text(self, *args, **kwargs):
        reads.append(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(store), "read_text", spy_read_text)
    frozen = apply_global_prompt_policy(
        {},
        positive_enabled=True,
        positive_text="frozen-positive",
        negative_enabled=True,
        negative_text="frozen-negative",
    )

    assert pipeline._global_prompt_terms(frozen, "global_positive_prompt")[0] == "frozen-positive"
    assert pipeline._global_prompt_terms(frozen, "global_negative_prompt")[0] == "frozen-negative"
    assert not [path for path in reads if str(store) in path]


def test_config_manager_persists_global_text_and_enabled_state(tmp_path) -> None:
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )

    assert manager.get_global_positive_enabled() is False
    assert manager.get_global_negative_enabled() is True
    assert manager.save_global_positive_state("sharp focus", True)
    assert manager.save_global_negative_state("blur", False)

    reloaded = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )
    assert reloaded.get_global_positive_prompt() == "sharp focus"
    assert reloaded.get_global_positive_enabled() is True
    assert reloaded.get_global_negative_prompt() == "blur"
    assert reloaded.get_global_negative_enabled() is False


def test_generic_config_merging_retains_the_frozen_policy(tmp_path) -> None:
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )
    controller = PipelineController(config_manager=manager)
    frozen = apply_global_prompt_policy(
        {"prompt": "subject"},
        positive_enabled=False,
        positive_text="positive",
        negative_enabled=True,
        negative_text="negative",
    )

    merged = controller.build_merged_config_for_run(
        model_name=None,
        runtime_overrides=frozen,
    )

    assert has_frozen_global_prompt_policy(merged)
    assert merged["global_positive_prompt"] == "positive"
    assert merged["global_negative_prompt"] == "negative"
