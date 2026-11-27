"""DESK-QUICK: one list of every model with missing files, from file presence only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.assets.component_evidence import ComponentEvidence
from src.assets.picker_compatibility import PickerEvidence
from src.services.model_file_health import LOADER_FOLDERS, find_missing_model_files
from src.video.workflow_contracts import WorkflowDependencySpec


def _entry(name: str, refusal: str = "", warning: bool = False) -> Any:
    picker = PickerEvidence(ComponentEvidence(), refusal=refusal, warning=warning)
    return SimpleNamespace(name=name, display_name=name, picker=picker)


def _spec(*files: tuple[str, str]) -> Any:
    return SimpleNamespace(
        display_name="Wan clip",
        workflow_version="1.0.0",
        dependency_specs=tuple(
            WorkflowDependencySpec(
                dependency_id=name, dependency_kind="model_file", locator=name, version_hint=hint
            )
            for name, hint in files
        ),
    )


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def test_an_exact_profile_checkpoint_lists_each_missing_module_and_its_folder(tmp_path) -> None:
    _touch(tmp_path / "models" / "VAE" / "flux2-vae.safetensors")

    report = find_missing_model_files(
        image_models=[_entry("flux-2-klein-4b-fp8.safetensors")], webui_root=tmp_path
    )

    (entry,) = report.entries
    assert entry.model == "flux-2-klein-4b-fp8.safetensors"
    assert len(entry.problems) == 1
    assert "qwen_3_4b.safetensors" in entry.problems[0] and "text_encoder" in entry.problems[0]


def test_a_picker_block_is_listed_and_a_policy_warning_is_not(tmp_path) -> None:
    report = find_missing_model_files(
        image_models=[
            _entry("qwen.safetensors", refusal="Needs the text encoder."),
            _entry("flux-dev.safetensors", refusal="Not qualified.", warning=True),
            _entry("juggernaut.safetensors"),
        ],
        webui_root=tmp_path,
    )

    assert [entry.model for entry in report.entries] == ["qwen.safetensors"]
    assert report.missing_for("qwen.safetensors") == ("Needs the text encoder.",)
    assert report.missing_for("juggernaut.safetensors") == ()


def test_video_workflow_files_are_resolved_by_their_loader_folder(tmp_path) -> None:
    unet, loras = tmp_path / "diffusion_models", tmp_path / "loras"
    _touch(unet / "wan.safetensors")
    spec = _spec(
        ("wan.safetensors", "UNETLoader.unet_name"),
        ("speed.safetensors", "LoraLoaderModelOnly.lora_name"),
        ("odd.bin", "SomeOtherNode.name"),
    )

    report = find_missing_model_files(
        video_specs=[spec], comfy_folders={"diffusion_models": [unet], "loras": [loras]}
    )

    (entry,) = report.entries
    assert entry.kind == "video" and entry.model == "Wan clip 1.0.0"
    assert len(entry.problems) == 1 and "speed.safetensors" in entry.problems[0]
    assert any("odd.bin" in note for note in report.unchecked)


def test_unknown_folders_are_reported_as_unchecked_never_as_missing_or_fine() -> None:
    report = find_missing_model_files(
        image_models=[_entry("flux-2-klein-4b-fp8.safetensors")],
        webui_root=None,
        video_specs=[_spec(("wan.safetensors", "UNETLoader.unet_name"))],
        comfy_folders=None,
    )

    assert report.entries == ()
    text = "\n".join(report.lines())
    assert "not checked" in text.lower() and "ComfyUI" in text


def test_lines_name_every_model_and_say_when_nothing_is_missing(tmp_path) -> None:
    empty = find_missing_model_files(image_models=[], webui_root=tmp_path)
    assert "No missing model files" in "\n".join(empty.lines())

    report = find_missing_model_files(
        image_models=[_entry("a.safetensors", refusal="Needs b.")], webui_root=tmp_path
    )
    text = "\n".join(report.lines())
    assert "a.safetensors" in text and "Needs b." in text


def test_every_offered_video_workflow_file_has_a_known_model_folder() -> None:
    """A new loader node in the catalog must be mapped, or its files would silently go unchecked."""

    from src.video.workflow_registry import build_default_workflow_registry, latest_spec_per_workflow

    specs = latest_spec_per_workflow(
        list(build_default_workflow_registry().list_offerable_specs("comfy"))
    )
    assert specs
    unmapped = {
        dependency.version_hint
        for spec in specs
        for dependency in spec.dependency_specs
        if dependency.dependency_kind == "model_file"
        and dependency.version_hint.partition(".")[0] not in LOADER_FOLDERS
    }
    assert unmapped == set()
