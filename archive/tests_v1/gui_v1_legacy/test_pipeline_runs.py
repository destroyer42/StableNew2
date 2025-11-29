class DummyPipeline:
    def __init__(self):
        self.calls = []

    def run_pack_pipeline(
        self,
        *,
        pack_name,
        prompt,
        config,
        run_dir,
        prompt_index,
        batch_size,
        variant_index=0,
        variant_label=None,
    ):
        self.calls.append(
            {
                "pack": pack_name,
                "prompt": prompt,
                "config": config,
                "batch_size": batch_size,
                "run_dir": run_dir,
                "variant_index": variant_index,
                "variant_label": variant_label,
            }
        )
        return {"summary": [{"pack": pack_name, "prompt": prompt}]}


def test_multiple_pipeline_runs_use_current_preset(tmp_path, monkeypatch, minimal_gui_app):
    """Ensure consecutive runs snapshot the preset/pack configs without hanging."""

    pack_a = tmp_path / "packs" / "heroes.txt"
    pack_b = tmp_path / "packs" / "villains.txt"
    pack_a.parent.mkdir(parents=True, exist_ok=True)
    for pack in (pack_a, pack_b):
        pack.write_text("prompt block", encoding="utf-8")

    monkeypatch.setattr(
        minimal_gui_app,
        "_get_selected_packs",
        lambda: [pack_a, pack_b],
    )

    prompts = [{"positive": "hero prompt"}]
    monkeypatch.setattr("src.gui.main_window.read_prompt_pack", lambda _path: prompts)

    pipeline = DummyPipeline()
    minimal_gui_app.pipeline = pipeline

    preset_calls: list[tuple[str, str]] = []

    def fake_ensure(pack_name, preset_name):
        preset_calls.append((pack_name, preset_name))
        return {"txt2img": {"steps": 30}, "pipeline": {}, "api": {}}

    minimal_gui_app.config_manager.ensure_pack_config = fake_ensure  # type: ignore[attr-defined]

    minimal_gui_app._get_config_from_forms = lambda: {"pipeline": {"img2img_enabled": True}}  # type: ignore
    minimal_gui_app.images_per_prompt_var.set("1")

    def fake_start(pipeline_func, on_complete=None, on_error=None):
        try:
            result = pipeline_func()
            if on_complete:
                on_complete(result)
        except Exception as exc:
            if on_error:
                on_error(exc)
            else:
                raise
        return True

    minimal_gui_app.controller.start_pipeline = fake_start  # type: ignore[assignment]

    minimal_gui_app.preset_var.set("preset_A")
    minimal_gui_app._run_full_pipeline()

    minimal_gui_app.preset_var.set("preset_B")
    minimal_gui_app._run_full_pipeline()

    assert len(pipeline.calls) == 4  # two packs × two runs
    assert preset_calls == [
        ("heroes.txt", "preset_A"),
        ("villains.txt", "preset_A"),
        ("heroes.txt", "preset_B"),
        ("villains.txt", "preset_B"),
    ]


def test_variant_plan_runs_each_combo(tmp_path, monkeypatch, minimal_gui_app):
    """Pipeline should fan-out variant combinations across prompts."""

    pack = tmp_path / "packs" / "combo.txt"
    pack.parent.mkdir(parents=True, exist_ok=True)
    pack.write_text("prompt block", encoding="utf-8")

    monkeypatch.setattr(minimal_gui_app, "_get_selected_packs", lambda: [pack])
    monkeypatch.setattr(
        "src.gui.main_window.read_prompt_pack",
        lambda _path: [{"positive": "variant prompt"}],
    )

    pipeline = DummyPipeline()
    minimal_gui_app.pipeline = pipeline

    minimal_gui_app._get_config_from_forms = lambda: {
        "txt2img": {"model": "base_model"},
        "img2img": {"model": "base_model"},
        "pipeline": {
            "model_matrix": ["modelA", "modelB"],
            "hypernetworks": [{"name": "HN1", "strength": 0.5}],
            "variant_mode": "fanout",
            "img2img_enabled": True,
            "upscale_enabled": True,
        },
    }  # type: ignore
    minimal_gui_app.images_per_prompt_var.set("1")

    def fake_start(pipeline_func, on_complete=None, on_error=None):
        try:
            result = pipeline_func()
            if on_complete:
                on_complete(result)
        except Exception as exc:  # pragma: no cover - mirrors controller contract
            if on_error:
                on_error(exc)
            else:
                raise
        return True

    minimal_gui_app.controller.start_pipeline = fake_start  # type: ignore[assignment]

    minimal_gui_app._run_full_pipeline()

    assert len(pipeline.calls) == 2
    variant_indices = [call["variant_index"] for call in pipeline.calls]
    assert variant_indices == [0, 1]
