# No external imports needed; keep file minimal and headless-friendly


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
        self.calls.append({"pack": pack_name, "prompt": prompt, "config": config})
        return {"summary": [{"pack": pack_name, "prompt": prompt}]}


def test_two_identical_runs_do_not_hang(tmp_path, monkeypatch, minimal_gui_app):
    """Consecutive runs without config changes should both complete (no lifecycle deadlock)."""

    # Create one pack
    pack = tmp_path / "packs" / "heroes.txt"
    pack.parent.mkdir(parents=True, exist_ok=True)
    pack.write_text("prompt block", encoding="utf-8")

    monkeypatch.setattr(minimal_gui_app, "_get_selected_packs", lambda: [pack])
    monkeypatch.setattr(
        "src.gui.main_window.read_prompt_pack", lambda _path: [{"positive": "hero prompt"}]
    )

    pipeline = DummyPipeline()
    minimal_gui_app.pipeline = pipeline

    # Force a stable form config snapshot
    minimal_gui_app._get_config_from_forms = lambda: {
        "txt2img": {"model": "ModelA", "vae": "VAE_A"},
        "pipeline": {},
    }  # type: ignore
    minimal_gui_app.images_per_prompt_var.set("1")

    # Fake controller start_pipeline to run synchronously (like existing tests)
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

    minimal_gui_app.controller.start_pipeline = fake_start  # type: ignore[attr-defined]

    # First run
    minimal_gui_app._run_full_pipeline()
    # Second run (identical)
    minimal_gui_app._run_full_pipeline()

    # Expect two calls (one image generated per run)
    assert len(pipeline.calls) == 2, "Both runs should complete without hang"
    # Model/VAE should appear in config for both runs
    for call in pipeline.calls:
        assert call["config"].get("txt2img", {}).get("model") == "ModelA"
        assert call["config"].get("txt2img", {}).get("vae") == "VAE_A"
