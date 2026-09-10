from pathlib import Path

from src.utils.lora_scanner import LoRAScanner


def test_lora_scan_regenerates_without_repository_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    webui_root = tmp_path / "webui"
    lora_file = webui_root / "models" / "Lora" / "example.safetensors"
    lora_file.parent.mkdir(parents=True)
    lora_file.write_bytes(b"test-lora")

    cache_file = Path("data/lora_cache.json")
    assert not cache_file.exists()

    resources = LoRAScanner(webui_root).scan_loras()

    assert set(resources) == {"example"}
    assert cache_file.exists()

