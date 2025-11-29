from copy import deepcopy

from src.utils.config import ConfigManager


def test_load_preset_merges_randomization_and_aesthetic(tmp_path):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    manager = ConfigManager(presets_dir=str(presets_dir))

    base = manager.get_default_config()
    minimal = deepcopy(base)
    minimal.pop("randomization")
    minimal.pop("aesthetic")
    minimal["txt2img"]["steps"] = 42

    manager.save_preset("custom", minimal)
    loaded = manager.load_preset("custom")

    assert loaded["txt2img"]["steps"] == 42
    assert "randomization" in loaded
    assert "aesthetic" in loaded
    assert loaded["randomization"]["prompt_sr"]["rules"] == []
    assert loaded["aesthetic"]["mode"] == "script"
