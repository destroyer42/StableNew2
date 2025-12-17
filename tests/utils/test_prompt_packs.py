from src.pipeline.run_config import PromptSource, RunConfig
from src.utils.prompt_packs import (
    PromptPackInfo,
    build_run_config_for_manual_prompt,
    build_run_config_from_prompt_pack,
    discover_packs,
)


def test_discover_packs_returns_sorted_descriptors(tmp_path):
    pack_two = tmp_path / "beta.txt"
    pack_two.write_text("prompt")
    pack_one = tmp_path / "alpha.tsv"
    pack_one.write_text("hello\tneg")

    packs = discover_packs(tmp_path)

    assert [p.name for p in packs] == ["alpha", "beta"]
    assert packs[0].path == pack_one
    assert isinstance(packs[0], PromptPackInfo)


def test_discover_packs_ensures_directory(tmp_path):
    target = tmp_path / "nested" / "packs"
    assert not target.exists()

    packs = discover_packs(target)

    assert packs == []
    assert target.exists()


# ---------------------------------------------------------------------------
# PR-112: RunConfig builder tests
# ---------------------------------------------------------------------------


def test_build_run_config_from_prompt_pack_sets_source():
    """RunConfig built from prompt pack has prompt_source=PACK."""
    pack_data = {
        "prompts": {
            "p1": {"prompt": "A dragon", "negative_prompt": "blurry"},
            "p2": {"prompt": "A castle", "negative_prompt": "dark"},
        }
    }

    cfg = build_run_config_from_prompt_pack("pack-123", pack_data, ["p1", "p2"])

    assert cfg.prompt_source == PromptSource.PACK
    assert cfg.prompt_pack_id == "pack-123"
    assert cfg.prompt_keys == ["p1", "p2"]


def test_build_run_config_from_prompt_pack_populates_payload():
    """Prompt payload includes pack_id and selected prompts."""
    pack_data = {
        "prompts": {
            "p1": {"prompt": "A dragon", "negative_prompt": "blurry"},
            "p2": {"prompt": "A castle", "negative_prompt": "dark"},
            "p3": {"prompt": "A forest", "negative_prompt": "fog"},
        }
    }

    cfg = build_run_config_from_prompt_pack("pack-123", pack_data, ["p1", "p2"])

    assert cfg.prompt_payload["pack_id"] == "pack-123"
    assert set(cfg.prompt_payload["prompts"].keys()) == {"p1", "p2"}
    assert cfg.prompt_payload["prompts"]["p1"]["prompt"] == "A dragon"


def test_build_run_config_from_prompt_pack_preserves_base_config():
    """Base config fields are copied, then prompt fields overwritten."""
    base = RunConfig(run_mode="queue", source="api")
    pack_data = {"prompts": {"k1": {"prompt": "Test"}}}

    cfg = build_run_config_from_prompt_pack("pk1", pack_data, ["k1"], base_config=base)

    assert cfg.run_mode == "queue"
    assert cfg.source == "api"
    assert cfg.prompt_source == PromptSource.PACK


def test_build_run_config_for_manual_prompt_sets_source():
    """RunConfig built for manual prompt has prompt_source=MANUAL."""
    cfg = build_run_config_for_manual_prompt("A dragon", "no gore")

    assert cfg.prompt_source == PromptSource.MANUAL
    assert cfg.prompt_pack_id is None
    assert cfg.prompt_keys == []


def test_build_run_config_for_manual_prompt_populates_payload():
    """Prompt payload includes prompt and negative_prompt."""
    cfg = build_run_config_for_manual_prompt("A dragon", "no gore")

    assert cfg.prompt_payload["prompt"] == "A dragon"
    assert cfg.prompt_payload["negative_prompt"] == "no gore"


def test_build_run_config_for_manual_prompt_preserves_base_config():
    """Base config fields are copied, then prompt fields overwritten."""
    base = RunConfig(run_mode="queue", source="cli")

    cfg = build_run_config_for_manual_prompt("Test prompt", base_config=base)

    assert cfg.run_mode == "queue"
    assert cfg.source == "cli"
    assert cfg.prompt_source == PromptSource.MANUAL
    assert cfg.prompt_pack_id is None
