from src.utils.aesthetic import detect_aesthetic_extension, find_aesthetic_extension_dir


def test_find_aesthetic_extension_dir_known_names(tmp_path):
    extensions_root = tmp_path / "extensions"
    target = extensions_root / "sd-webui-aesthetic-gradients"
    target.mkdir(parents=True)

    match = find_aesthetic_extension_dir(extensions_root)
    assert match == target


def test_detect_aesthetic_extension_accepts_fuzzy_names(tmp_path):
    root = tmp_path / "stable-diffusion-webui"
    target = root / "extensions" / "Custom-Aesthetic-Gradient-Pack"
    target.mkdir(parents=True)

    detected, path = detect_aesthetic_extension([root])
    assert detected is True
    assert path == target


def test_detect_aesthetic_extension_checks_multiple_roots(tmp_path):
    miss = tmp_path / "missing-root"
    hit = tmp_path / "sd-webui"
    target = hit / "extensions" / "stable-diffusion-webui-aesthetic-gradients-master"
    target.mkdir(parents=True)

    detected, path = detect_aesthetic_extension([miss, hit])
    assert detected is True
    assert path == target
