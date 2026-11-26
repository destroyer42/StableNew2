"""N12: one canonical checkpoint key (characterization first, then the cases the old spellings split)."""

from __future__ import annotations

import pytest

from src.utils.checkpoint_identity import checkpoint_key, same_checkpoint


def _pre_n12_probe_key(name: object) -> str:
    """Verbatim copy of ``model_readiness_probe.checkpoint_key`` before N12 (persisted ``model_key`` values use it)."""

    base = str(name or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for ext in (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".gguf"):
        if lowered.endswith(ext):
            return lowered[: -len(ext)]
    return lowered


# Spellings seen in stored NJRs, Learning records, registry rows and Forge/A1111 listings.
CORPUS = (
    "",
    None,
    "juggernautXL_v9.safetensors",
    "JuggernautXL_v9.safetensors [a1b2c3d4e5]",
    "sdxl\\juggernautXL_v9.safetensors [a1b2c3d4e5]",
    "sdxl/juggernautXL_v9.safetensors",
    "C:\\webui\\models\\Stable-diffusion\\sdxl\\juggernautXL_v9.safetensors",
    "juggernautXL_v9",
    "  juggernautXL_v9.ckpt  ",
    "flux1-dev-Q8_0.gguf",
    "zimage.sft",
    "model.pth",
    "model.pt",
    "Model.SafeTensors",
    "name with spaces.safetensors [0123abcd]",
    "nested/model.safetensors",
)


@pytest.mark.parametrize("name", CORPUS)
def test_canonical_key_preserves_every_pre_n12_probe_key(name):
    # Profile identities persist ``model_key`` from the old probe key; the canonical key must not move them.
    assert checkpoint_key(name) == _pre_n12_probe_key(name)


def test_forge_title_model_name_filename_and_registry_path_share_one_key():
    spellings = (
        "sdxl\\juggernautXL_v9.safetensors [a1b2c3d4e5]",  # Forge /sd-models title
        "juggernautXL_v9",  # A1111 model_name
        "C:\\webui\\models\\Stable-diffusion\\sdxl\\juggernautXL_v9.safetensors",  # filename
        "sdxl/juggernautXL_v9.safetensors",  # registry relative path
        "JuggernautXL_v9.safetensors",  # Learning record written from a display name
    )
    assert {checkpoint_key(s) for s in spellings} == {"juggernautxl_v9"}


def test_picker_collision_label_resolves_to_the_internal_name():
    # base_generation_panel_v2 labels a display-name collision ``"{display} [{internal}]"``.
    assert (
        checkpoint_key("juggernautXL_v9 [sdxl\\juggernautXL_v9.safetensors [a1b2c3d4e5]]")
        == "juggernautxl_v9"
    )
    assert (
        checkpoint_key("juggernautXL_v9 [juggernautXL_v9.safetensors [a1b2c3d4e5]]")
        == "juggernautxl_v9"
    )
    assert checkpoint_key("juggernautXL_v9 [other/renamed_copy.safetensors]") == "renamed_copy"


def test_stacked_hash_suffixes_are_all_removed():
    assert checkpoint_key("model.safetensors [abc123] [def456]") == "model"
    assert checkpoint_key("model.safetensors[abc123]") == "model"


def test_brackets_inside_a_filename_are_kept():
    assert checkpoint_key("model [v2].safetensors") == "model [v2]"


def test_same_checkpoint_needs_two_non_empty_names():
    assert same_checkpoint("sdxl\\m.safetensors [abc]", "M")
    assert not same_checkpoint("", "")
    assert not same_checkpoint(None, "m")
    assert not same_checkpoint("a.safetensors", "b.safetensors")


@pytest.mark.parametrize("name", CORPUS)
def test_backend_profile_matchers_agree_with_the_canonical_key(name):
    from src.image_backends.forge_klein_profile import _model_key as klein_key
    from src.image_backends.model_policy import _model_key as policy_key

    assert policy_key(name) == checkpoint_key(name)
    if not str(name or "").strip().lower().endswith(".gguf"):  # Klein profiles name no GGUF file
        assert klein_key(name) == checkpoint_key(name)
