"""PR-AI-VL-220: the owner-approved image invocation contract, implemented (build entry, visual argv, driver, CLI gate).

Hermetic. The child is a Python script standing in for ``llama-mtmd-cli.exe`` and is launched through the real
``run_bounded`` (own OS container, timeout, output cap, cooperative cancellation); no llama.cpp binary and no model is ever
run, no GPU is touched, nothing is written under the real AI Assist root, and no network is used. The runtime, attestation and
weights here are tiny files made in a temporary directory.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import re
import socket
import struct
import sys
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from src.ai_assist import activation, manifests, preview
from src.ai_assist.activation import ActivationRefused, activate, is_compatible
from src.ai_assist.argv import (
    ALLOWED_FLAGS,
    FORBIDDEN_FLAGS,
    PRODUCTION_ALLOWED_FLAGS,
    build_argv,
    build_production_argv,
)
from src.ai_assist.attestation import record_attestation
from src.ai_assist.host import GenerationActivity, HostMemory
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    load_model_registry,
    load_runtime_manifest,
)
from src.ai_assist.selector import list_model_choices
from src.ai_assist.status import MODEL_REGISTRY_PATH, RUNTIME_MANIFEST_PATH
from src.utils.managed_process import run_bounded
from tests.tools.test_ai_vl220_candidate import acknowledgement, build_fixture
from tools import ai_assist_admin
from tools.qualification.vl220 import __main__ as cli
from tools.qualification.vl220 import candidates as cand
from tools.qualification.vl220 import contract, driver, plan, synthetic, visual_argv
from tools.qualification.vl220.contract import Case
from tools.qualification.vl220.prompts import render_visual_prompt
from tools.qualification.vl220.visual_argv import (
    VISION_BUILD_ID,
    VISION_TOOL,
    VisualArgvRefused,
    VisualLimits,
    VisualSampling,
    argv_shape_digest,
    build_visual_argv,
    check_visual_argv,
    inspect_image,
)

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "tools" / "qualification" / "vl220"
OLD_PLAN_DIGEST = "23df6fa436f4e4292b4421e5155ee232729ea1b4942ff8b6807b50dbc755880e"
#: The plan the first supervised run (2026-11-14) was approved and executed against.
RUN1_PLAN_DIGEST = "fa63304dc98e6aeb0eeb8e7d922cc61d23507ef58fb4994232bd723e9e66339a"
#: The plan the second supervised run (2026-11-14, PR-AI-VL-222) was approved and executed against: RUN1 plus the
#: ``diagnostic`` section (per-case schemas and prompts, controls, the second set).
RUN2_PLAN_DIGEST = "ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7"
#: The plan after PR-AI-VL-223: RUN2 plus the ``template_ab`` section (the turn-format A/B on the varied 512-pixel set).
NEW_PLAN_DIGEST = "15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536"
MARKER = "zebra-marker-xyz"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ============================================================================================ build entry and isolation


def test_the_vision_build_is_a_pinned_unqualified_twin_of_the_required_build() -> None:
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    assert manifest.problems == ()
    twin, vision = manifest.find("b11960-cpu"), manifest.find(VISION_BUILD_ID)
    assert twin is not None and vision is not None
    assert (vision.asset_name, vision.asset_sha256, vision.asset_bytes) == (
        twin.asset_name,
        twin.asset_sha256,
        twin.asset_bytes,
    )
    assert dict(vision.files) == dict(twin.files) and vision.upstream_tag == twin.upstream_tag
    assert vision.executable == VISION_TOOL == "llama-mtmd-cli.exe" and VISION_TOOL in vision.files
    assert twin.executable == "llama-completion.exe"
    assert vision.qualified is False and twin.qualified is False
    candidate = cand.find_candidate(cand.LFM_CANDIDATE_ID)
    assert (
        candidate.runtime.required_build_id == "b11960-cpu"
        and candidate.runtime.tool == VISION_TOOL
    )
    assert (
        driver.vision_build_reasons(manifest, load_model_registry(MODEL_REGISTRY_PATH), candidate)
        == []
    )


def test_no_model_lists_the_vision_build_and_the_registry_text_is_untouched() -> None:
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    vision = manifest.find(VISION_BUILD_ID)
    assert vision is not None and registry.entries
    for entry in registry.entries:
        assert VISION_BUILD_ID not in entry.compatible_builds
        assert not is_compatible(entry, vision)
    text = MODEL_REGISTRY_PATH.read_text(encoding="utf-8")
    assert VISION_BUILD_ID not in text and VISION_TOOL not in text


def _installed_world(
    tmp_path: Path,
) -> tuple[Path, RuntimeManifest, ModelRegistry, manifests.ModelEntry]:
    """An AI root holding one registered text model and both b11960 builds, all tiny and hash-correct."""

    files = {"llama-completion.exe": b"completion", "llama-mtmd-cli.exe": b"mtmd"}
    twin = RuntimeBuild(
        "b11960-cpu", "https://github.com/ggml-org/llama.cpp", "b11960", "x.zip", "a" * 64, 10,
        "MIT", "llama-completion.exe", {name: sha(data) for name, data in files.items()}, False,
    )  # fmt: skip
    vision = replace(twin, build_id=VISION_BUILD_ID, executable=VISION_TOOL)
    model_bytes = b"gguf-model"
    entry = manifests.ModelEntry(
        model_id="text-model", display_name="Text", license_spdx="Apache-2.0", architecture="qwen35",
        quantization="Q4", filename="text.gguf", bytes=len(model_bytes), sha256=sha(model_bytes),
        provenance=manifests.Provenance("a/b", "1" * 40, "c/d", "2" * 40, "conv", "https://huggingface.co/x"),
        compatible_builds=("b11960-cpu",),
    )  # fmt: skip
    root = tmp_path / "aiworld"
    for build in (twin, vision):
        for name, data in files.items():
            target = root / "runtimes" / build.build_id / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    target = root / "models" / entry.sha256 / entry.filename
    target.parent.mkdir(parents=True)
    target.write_bytes(model_bytes)
    return root, RuntimeManifest((twin, vision)), ModelRegistry((entry,)), entry


def test_selector_activation_preview_and_import_model_cannot_reach_the_vision_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, manifest, registry, entry = _installed_world(tmp_path)
    # Selector: the model is offered on the text build it lists, never on the vision build.
    choices = list_model_choices(root, manifest, registry)
    assert [(c.model_id, c.build_id) for c in choices] == [("text-model", "b11960-cpu")]
    # Activation: the explicit compatibility list refuses it before anything is written.
    with pytest.raises(ActivationRefused) as refused:
        activate(root, manifest, registry, build_id=VISION_BUILD_ID, model_id="text-model")
    assert refused.value.code == "build_incompatible"
    assert not (root / "active.json").exists()
    # Preview: enablement needs an active, verified installation, and activation never produced one on the vision build.
    with pytest.raises(preview.PreviewRefused):
        preview.enable_preview(root, manifest, registry)
    assert preview.read_preview_identities(root) == ()
    # The admin entry points with the real configs: every registered model refuses the vision build.
    real = load_model_registry(MODEL_REGISTRY_PATH)
    for item in real.entries:
        assert (
            ai_assist_admin.main(
                [
                    "--root",
                    str(tmp_path / "ai"),
                    "activate",
                    "--build-id",
                    VISION_BUILD_ID,
                    "--model-id",
                    item.model_id,
                ]
            )  # fmt: skip
            == 2
        )
        assert "build_incompatible" in capsys.readouterr().out
    # import-model has no notion of a build at all.
    assert list(inspect.signature(manifests.import_model).parameters) == ["source", "entry", "root"]
    assert activation.is_compatible(entry, manifest.builds[0]) and not activation.is_compatible(
        entry, manifest.builds[1]
    )


def test_the_frozen_ai111_ai115_identities_did_not_move() -> None:
    from tools.qualification.ai111.corpus import corpus_digest
    from tools.qualification.ai111.final_plan import final_corpus, final_plan
    from tools.qualification.ai111.lfm3_contract import FROZEN_CONTRACT_SHA256
    from tools.qualification.ai111.plan import digest, frozen_plan

    assert digest(frozen_plan()).startswith("17814e40")
    assert digest(final_plan()).startswith("3017c427")
    assert corpus_digest(final_corpus()).startswith("a89297be")
    assert FROZEN_CONTRACT_SHA256.startswith("41e65d67")


def test_production_vocabulary_is_byte_identical_and_still_refuses_projectors() -> None:
    from src.ai_assist import argv as production

    assert {"--mmproj", "--mmproj-url", "-mmu", "--rpc", "-hf", "-mu"} <= FORBIDDEN_FLAGS
    assert sorted(ALLOWED_FLAGS) == sorted(
        {
            "-m", "-f", "--json-schema-file", "-c", "-n", "-t", "-ngl", "--offline", "--temp", "--top-k", "--top-p",
            "--presence-penalty", "--seed", "--no-display-prompt", "--no-conversation", "--reasoning", "--prio",
            "--log-disable",
        }
    )  # fmt: skip
    assert PRODUCTION_ALLOWED_FLAGS == ALLOWED_FLAGS - {"--log-disable"}
    assert not {"--mmproj", "--image", "-mmdev", "--no-mmproj-offload"} & ALLOWED_FLAGS
    for builder in (build_argv, build_production_argv):
        tokens = builder(Path("m"), Path("p"), Path("s"), production.RunLimits())
        assert not {"--mmproj", "--image", "-mmdev", "--no-mmproj-offload", "-p"} & set(tokens)
    assert "--mmproj" not in inspect.getsource(production.build_production_argv)


def test_only_the_visual_builder_in_the_harness_spells_the_projector_flag() -> None:
    holders = []
    for folder in ("src", "tools"):
        for path in (REPO / folder).rglob("*.py"):
            if '"--mmproj"' in path.read_text(encoding="utf-8"):
                holders.append(path.relative_to(REPO).as_posix())
    assert sorted(holders) == [
        "src/ai_assist/argv.py",  # the forbidden list only
        "tools/qualification/vl220/visual_argv.py",
    ]
    source = (REPO / "src" / "ai_assist" / "argv.py").read_text(encoding="utf-8")
    assert source.count('"--mmproj"') == 1


# ======================================================================================================== argv vocabulary

ROW_FLAGS = {
    "--offline", "-ngl", "-f", "--json-schema-file", "-c", "-n", "-t", "--temp", "--top-p", "--top-k", "--min-p",
    "--presence-penalty", "--repeat-penalty", "--seed", "--prio", "-m", "--mmproj", "--image",
    "--no-mmproj-offload", "-mmdev", "--image-min-tokens", "--image-max-tokens",
}  # fmt: skip


def test_the_vocabulary_is_exactly_the_yes_rows_of_the_contract_table() -> None:
    assert visual_argv.VISUAL_ALLOWED_FLAGS == ROW_FLAGS
    assert visual_argv.VISUAL_SWITCHES == {"--offline", "--no-mmproj-offload"}
    document = (
        REPO / "docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md"
    ).read_text(encoding="utf-8")
    for flag in ROW_FLAGS:
        pattern = rf"`[^`]*(?<![\w-]){re.escape(flag)}(?![\w-])[^`]*`"
        assert re.search(pattern, document), flag
    # The explicit "no" rows and every production-forbidden flag are refused by name.
    for flag in ("-p", "--prompt", "--log-disable", "--jinja", "-hf", "-mu", "--mmproj-url", "-mmu", "--rpc",
                 "--host", "--port", "--lora", "--control-vector", "--media-path"):  # fmt: skip
        assert (
            flag in visual_argv.VISUAL_REFUSED_FLAGS
            and flag not in visual_argv.VISUAL_ALLOWED_FLAGS
        )
    assert "--mmproj" not in visual_argv.VISUAL_REFUSED_FLAGS


@dataclass
class Files:
    root: Path
    work: Path
    model: Path
    projector: Path
    prompt: Path
    schema: Path
    images: list[Path]


def make_files(tmp_path: Path, images: int = 1) -> Files:
    root, work = tmp_path / "evalroot", tmp_path / "evalroot" / "_work" / "w1"
    work.mkdir(parents=True, exist_ok=True)
    model, projector = root / "model.gguf", root / "mmproj.gguf"
    model.write_bytes(b"m")
    projector.write_bytes(b"p")
    prompt, schema = work / "prompt.txt", work / "schema.json"
    prompt.write_text("Describe the image.\n", encoding="utf-8")
    schema.write_text("{}", encoding="utf-8")
    png = next(iter(synthetic.build_synthetic_set()[0].values()))
    paths = []
    for index in range(images):
        path = work / f"image_{index}.png"
        path.write_bytes(png)
        paths.append(path)
    return Files(root, work, model, projector, prompt, schema, paths)


def build_from(files: Files, **changes: Any) -> list[str]:
    arguments: dict[str, Any] = {
        "model_path": files.model, "projector_path": files.projector, "prompt_file": files.prompt,
        "schema_file": files.schema, "image_paths": files.images, "evaluation_root": files.root, "work_dir": files.work,
    }  # fmt: skip
    arguments.update(changes)
    return build_visual_argv(**arguments)


def test_the_builder_emits_only_the_closed_vocabulary_with_exactly_one_projector(
    tmp_path: Path,
) -> None:
    files = make_files(tmp_path, images=2)
    argv = build_from(files)
    flags = [token for token in argv if token.startswith("-") and token not in ("-1",)]
    assert set(flags) <= ROW_FLAGS
    assert argv.count("--mmproj") == 1 and argv.count("--image") == 2 and argv.count("-m") == 1
    assert argv[argv.index("--mmproj") + 1] == str(files.projector.resolve())
    assert argv[argv.index("-m") + 1] == str(files.model.resolve())
    for required in ("--offline", "--no-mmproj-offload"):
        assert required in argv
    assert argv[argv.index("-ngl") + 1] == "0" and argv[argv.index("-mmdev") + 1] == "none"
    for forbidden in (
        "-p",
        "--log-disable",
        "--jinja",
        "-hf",
        "-mu",
        "--mmproj-url",
        "-mmu",
        "--rpc",
        "--host",
    ):
        assert forbidden not in argv
    # GPU: nothing but CPU settings.
    assert not {
        "--n-gpu-layers",
        "-dev",
        "--device",
        "-sm",
        "--split-mode",
        "-mg",
        "--main-gpu",
    } & set(argv)
    check_visual_argv(argv)
    # The prompt is only ever a file path, never its text.
    assert "Describe the image." not in " ".join(argv)


def test_the_builder_is_deterministic_and_the_shape_hash_carries_no_path(tmp_path: Path) -> None:
    first = build_from(make_files(tmp_path / "a"))
    second = build_from(make_files(tmp_path / "b"))
    assert first != second and argv_shape_digest(first) == argv_shape_digest(second)
    assert str(tmp_path) not in " ".join(visual_argv.argv_shape(first))
    changed = build_from(make_files(tmp_path / "c"), limits=VisualLimits(image_max_tokens=300))
    assert argv_shape_digest(changed) != argv_shape_digest(first)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda f: f.prompt.write_text("  \n", encoding="utf-8"), "prompt_file_empty"),
        (lambda f: f.prompt.write_bytes(b""), "prompt_file_empty"),
        (lambda f: f.images[0].unlink(), "image_outside_work_dir"),
        (lambda f: f.model.unlink(), "model_outside_evaluation_root"),
        (lambda f: f.projector.unlink(), "projector_outside_evaluation_root"),
        (lambda f: f.schema.unlink(), "schema_file_outside_work_dir"),
    ],
)
def test_the_builder_refuses_an_empty_prompt_or_a_missing_file(
    tmp_path: Path, mutate: Callable[[Files], Any], code: str
) -> None:
    files = make_files(tmp_path)
    mutate(files)
    with pytest.raises(VisualArgvRefused) as refused:
        build_from(files)
    assert refused.value.code == code


def test_the_builder_refuses_wrong_image_counts_and_paths_outside_their_directories(
    tmp_path: Path,
) -> None:
    files = make_files(tmp_path)
    for images in ([], [files.images[0]] * 3):
        with pytest.raises(VisualArgvRefused) as refused:
            build_from(files, image_paths=images)
        assert refused.value.code == "one_or_two_images_required"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    for field, name, code in (
        ("model_path", "m.gguf", "model_outside_evaluation_root"),
        ("projector_path", "p.gguf", "projector_outside_evaluation_root"),
        ("prompt_file", "p.txt", "prompt_file_outside_work_dir"),
        ("schema_file", "s.json", "schema_file_outside_work_dir"),
    ):
        stray = outside / name
        stray.write_bytes(b"x")
        with pytest.raises(VisualArgvRefused) as refused:
            build_from(files, **{field: stray})
        assert refused.value.code == code
    stray_image = outside / "i.png"
    stray_image.write_bytes(files.images[0].read_bytes())
    with pytest.raises(VisualArgvRefused) as refused:
        build_from(files, image_paths=[stray_image])
    assert refused.value.code == "image_outside_work_dir"
    with pytest.raises(
        VisualArgvRefused
    ) as refused:  # a `..` hop out of the root is resolved, not trusted
        build_from(files, model_path=files.root / "_work" / ".." / ".." / "elsewhere" / "m.gguf")
    assert refused.value.code == "model_outside_evaluation_root"
    with pytest.raises(VisualArgvRefused) as refused:
        build_from(files, projector_path=files.model)
    assert refused.value.code == "projector_is_the_model"


def good_argv(tmp_path: Path) -> list[str]:
    return build_from(make_files(tmp_path))


def drop(argv: list[str], flag: str) -> list[str]:
    out, index = [], 0
    while index < len(argv):
        if argv[index] == flag:
            index += 1 if flag in visual_argv.VISUAL_SWITCHES else 2
        else:
            out.append(argv[index])
            index += 1
    return out


@pytest.mark.parametrize(
    "extra",
    [
        ["-p", "hello"], ["--prompt", "hello"], ["--log-disable"], ["--jinja"], ["-hf", "a/b"], ["--hf-repo", "a/b"],
        ["-mu", "https://x"], ["--model-url", "https://x"], ["--mmproj-url", "https://x"], ["-mmu", "https://x"],
        ["--rpc", "127.0.0.1:1"], ["--host", "0.0.0.0"], ["--port", "8080"], ["--api-key", "k"], ["--lora", "x"],
        ["--control-vector", "x"], ["--media-path", "/"], ["-dr", "x"], ["--connect", "x"], ["--webui"],
        ["--no-conversation"], ["--no-display-prompt"], ["--reasoning", "off"], ["--video", "x"], ["--audio", "x"],
        ["--n-gpu-layers", "99"], ["-dev", "cuda0"], ["--unknown-flag", "1"], ["--mmproj", "second.gguf"],
        ["-ngl", "1"], ["--temp", "0.1"],
    ],
)  # fmt: skip
def test_the_checker_refuses_every_forbidden_unknown_or_repeated_flag(
    tmp_path: Path, extra: list[str]
) -> None:
    argv = good_argv(tmp_path)
    check_visual_argv(argv)
    with pytest.raises(VisualArgvRefused):
        check_visual_argv([*argv, *extra])


@pytest.mark.parametrize(
    ("flag", "code"),
    [
        ("--mmproj", "exactly_one_mmproj_required"),
        ("--image", "one_or_two_images_required"),
        ("-f", "model_prompt_and_schema_required"),
        ("-m", "model_prompt_and_schema_required"),
        ("--json-schema-file", "model_prompt_and_schema_required"),
        ("--no-mmproj-offload", "cpu_only_offline_settings_required"),
        ("--offline", "cpu_only_offline_settings_required"),
        ("-ngl", "cpu_only_offline_settings_required"),
        ("-mmdev", "cpu_only_offline_settings_required"),
    ],
)
def test_the_checker_refuses_a_command_line_missing_a_required_piece(
    tmp_path: Path, flag: str, code: str
) -> None:
    with pytest.raises(VisualArgvRefused) as refused:
        check_visual_argv(drop(good_argv(tmp_path), flag))
    assert refused.value.code == code


def test_the_checker_refuses_stray_values_missing_values_and_non_numbers(tmp_path: Path) -> None:
    argv = good_argv(tmp_path)
    for broken in (["stray", *argv], [*argv, "--seed"], [*argv[:-2], "--seed", "-hf"], argv[:-1]):
        with pytest.raises(VisualArgvRefused):
            check_visual_argv(broken)
    index = argv.index("--seed")
    changed = [*argv[: index + 1], "abc", *argv[index + 2 :]]
    with pytest.raises(VisualArgvRefused) as refused:
        check_visual_argv(changed)
    assert refused.value.code == "value_not_a_number"


def test_limits_and_sampling_are_bounded() -> None:
    for bad in (
        {"context_tokens": 100}, {"threads": 0}, {"timeout_seconds": 0.1}, {"max_stdout_bytes": 10},
        {"image_min_tokens": 0}, {"image_min_tokens": 300, "image_max_tokens": 200}, {"image_max_tokens": 5000},
    ):  # fmt: skip
        with pytest.raises(ValueError):
            VisualLimits(**bad)
    for bad_sampling in ({"temperature": -1}, {"top_p": 0}, {"top_k": 0}, {"seed": -1}, {"repeat_penalty": 0.5},
                         {"temperature": float("nan")}):  # fmt: skip
        with pytest.raises(ValueError):
            VisualSampling(**bad_sampling)
    assert VisualSampling().temperature == 0.0 and VisualLimits().timeout_seconds == 180.0


# ============================================================================================================ image checks


def png_header(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
    )


def jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def test_image_pre_checks_read_only_the_header(tmp_path: Path) -> None:
    good = tmp_path / "a.png"
    good.write_bytes(png_header(640, 480))
    assert inspect_image(good) == ("image/png", 640, 480)
    photo = tmp_path / "a.jpg"
    photo.write_bytes(jpeg(800, 600))
    assert inspect_image(photo) == ("image/jpeg", 800, 600)
    edge = tmp_path / "edge.png"
    edge.write_bytes(png_header(4096, 4096))
    assert inspect_image(edge)[1:] == (4096, 4096)


REFUSED_IMAGES: list[tuple[bytes, str]] = [
    (png_header(4097, 10), "image_dimensions_out_of_range"),
    (png_header(10, 4097), "image_dimensions_out_of_range"),
    (png_header(0, 10), "image_dimensions_out_of_range"),
    (jpeg(5000, 100), "image_dimensions_out_of_range"),
    (b"GIF89a" + b"\x00" * 40, "image_not_png_or_jpeg"),
    (b"%PDF-1.7 " + b"\x00" * 40, "image_not_png_or_jpeg"),
    (b"\x89PNG\r\n\x1a\n" + b"junk" * 3, "image_header_invalid"),
    (b"\xff\xd8\xff\xe0\x00\x02", "image_header_invalid"),
    (b"", "image_size_out_of_range"),
    (png_header(10, 10) + b"\x00" * (visual_argv.MAX_IMAGE_BYTES), "image_size_out_of_range"),
]


@pytest.mark.parametrize(
    ("data", "code"),
    REFUSED_IMAGES,
    ids=[f"{index}-{code}" for index, (_, code) in enumerate(REFUSED_IMAGES)],
)
def test_image_pre_checks_refuse_anything_else(tmp_path: Path, data: bytes, code: str) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(data)
    with pytest.raises(VisualArgvRefused) as refused:
        inspect_image(path)
    assert refused.value.code == code
    with pytest.raises(VisualArgvRefused) as missing:
        inspect_image(tmp_path / "nothing.png")
    assert missing.value.code == "image_missing"


# =================================================================================================== driver test fixtures

CHILD = textwrap.dedent(
    r"""
    import json, os, re, sys, time
    record, response = sys.argv[1], sys.argv[2]
    argv = sys.argv[3:]
    raw = open(response, "rb").read() if os.path.isfile(response) else b"auto"
    mode = raw.decode() if raw.startswith(b"@") or raw == b"auto" else "file"
    prompt = open(argv[argv.index("-f") + 1], encoding="utf-8").read()
    images = [argv[i + 1] for i, token in enumerate(argv) if token == "--image"]
    work = os.path.dirname(argv[argv.index("-f") + 1])
    with open(record + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd(), "work": work,
                   "images_exist": [os.path.isfile(p) for p in images], "work_files": sorted(os.listdir(work)),
                   "prompt": prompt}, handle)
    os.replace(record + ".tmp", record)
    if mode == "@sleep":
        time.sleep(120)
    if mode.startswith("@exit:"):
        sys.exit(int(mode.split(":")[1]))
    if mode == "@big":
        sys.stdout.write("x" * (300 * 1024))
        sys.exit(0)
    time.sleep(0.4)
    if mode == "auto":
        kind = re.search(r'"kind":"([a-z_]+)"', prompt).group(1)
        ids = re.findall(r"^- ([a-z0-9_.-]+): ", prompt, re.M)
        payload = {"adherence": {"answers": [{"id": i, "value": True} for i in ids]},
                   "consistency": {"answers": [{"id": i, "value": True} for i in ids]},
                   "defect_triage": {"findings": []},
                   "before_after": {"preferred": "tie", "reason": "no_difference"},
                   "describe": {"objects": ["__MARKER__"]}}[kind]
        document = {"schema": "stablenew.vl220.response/1", "status": "ok", "kind": kind, **payload}
        sys.stdout.write(json.dumps(document))
    else:
        sys.stdout.buffer.write(raw)
    sys.stdout.flush()
    """
).replace("__MARKER__", MARKER)


@dataclass
class World:
    tmp: Path
    candidate: cand.VisualCandidate
    case_set: contract.CaseSet
    labels: contract.LabelSet
    kwargs: dict[str, Any]
    launches: list[tuple[Path, list[str]]]
    record: Path
    response: Path

    def driver(self, **overrides: Any) -> driver.VisualDriver:
        return driver.VisualDriver(self.candidate, **{**self.kwargs, **overrides})

    def respond(self, text: str | bytes) -> None:
        self.response.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))

    def case(self, kind: str) -> Case:
        return next(case for case in self.case_set.cases if case.kind == kind)

    @property
    def staged(self) -> Path:
        return (
            self.kwargs["evaluation_root"]
            / self.candidate.candidate_id
            / self.candidate.model.sha256[:16]
        )

    @property
    def ai_root(self) -> Path:
        return self.kwargs["ai_root"]

    def recorded(self) -> dict[str, Any]:
        return json.loads(self.record.read_text(encoding="utf-8"))


def idle() -> GenerationActivity:
    return GenerationActivity()


def roomy() -> HostMemory:
    return HostMemory(available_gib=64.0, commit_headroom_gib=64.0)


@pytest.fixture
def world(tmp_path: Path) -> World:
    candidate, staging_dir = build_fixture(tmp_path)
    evaluation_root = tmp_path / "evalroot"
    staged = evaluation_root / candidate.candidate_id / candidate.model.sha256[:16]
    staged.mkdir(parents=True)
    for item in (candidate.model, candidate.projector):
        (staged / item.filename).write_bytes((staging_dir / item.filename).read_bytes())
    images, case_doc, label_doc = synthetic.build_synthetic_set()
    case_set = contract.validate_case_set(case_doc)
    labels = contract.validate_label_set(label_doc, case_set)
    assets = tmp_path / "assets"
    assets.mkdir()
    for asset_id, data in images.items():
        (assets / f"{asset_id}.png").write_bytes(data)
    runtime_files = {"llama-completion.exe": b"completion", "llama-mtmd-cli.exe": b"mtmd"}
    twin = RuntimeBuild(
        "b11960-cpu", "https://github.com/ggml-org/llama.cpp", "b11960", "x.zip", "a" * 64, 10, "MIT",
        "llama-completion.exe", {name: sha(data) for name, data in runtime_files.items()}, False,
    )  # fmt: skip
    vision = replace(twin, build_id=VISION_BUILD_ID, executable=VISION_TOOL)
    ai_root = tmp_path / "ai"
    for name, data in runtime_files.items():
        target = ai_root / "runtimes" / VISION_BUILD_ID / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    record_attestation(ai_root, "operator block rule", [(VISION_BUILD_ID, VISION_TOOL)])
    records = tmp_path / "records"
    records.mkdir()
    record, response = records / "record.json", records / "response.txt"
    child = records / "child.py"
    child.write_text(CHILD, encoding="utf-8")
    launches: list[tuple[Path, list[str]]] = []

    def factory(executable: Path, argv: list[str]) -> list[str]:
        launches.append((executable, list(argv)))
        return [sys.executable, str(child), str(record), str(response), *argv]

    kwargs: dict[str, Any] = {
        "evaluation_root": evaluation_root, "ai_root": ai_root, "assets_dir": assets,
        "acknowledgement": acknowledgement(candidate), "activity": idle,
        "runtime_manifest": RuntimeManifest((twin, vision)), "registry": load_model_registry(MODEL_REGISTRY_PATH),
        "memory_probe": roomy, "command_factory": factory,
        "environ": {"SystemRoot": "C:/Windows", "SECRET_TOKEN": "must-not-leak", "HTTP_PROXY": "http://x"},
        "limits": VisualLimits(timeout_seconds=60.0),
    }  # fmt: skip
    return World(tmp_path, candidate, case_set, labels, kwargs, launches, record, response)


def answer(world: World, kind: str, **fields: Any) -> str:
    return json.dumps({"schema": contract.RESPONSE_SCHEMA, "status": "ok", "kind": kind, **fields})


# ===================================================================================================== driver: happy path


def test_a_case_runs_through_the_real_launcher_with_a_scrubbed_cpu_only_command(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the driver must not use the network")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    case = world.case(contract.KIND_ADHERENCE)
    run = world.driver().run_case(world.case_set, case)
    assert run.refusal is None and run.evidence.status == driver.STATUS_VALID, run.evidence
    assert run.evidence.exit_code == 0 and run.evidence.cpu_only is True
    assert run.evidence.wall_seconds >= 0.3 and run.evidence.peak_working_set_bytes > 0
    assert len(run.evidence.argv_shape_sha256) == 64 and run.evidence.context_tokens == 4096
    (executable, argv) = world.launches[0]
    assert executable == world.ai_root / "runtimes" / VISION_BUILD_ID / VISION_TOOL
    seen = world.recorded()
    assert seen["argv"] == argv and argv.count("--mmproj") == 1
    assert (
        argv[argv.index("-ngl") + 1] == "0" and "--no-mmproj-offload" in argv and "-p" not in argv
    )
    env = seen["env"]
    assert (
        env["CUDA_VISIBLE_DEVICES"] == "-1"
        and env["NO_PROXY"] == "*"
        and env["HF_HUB_OFFLINE"] == "1"
    )
    assert env["PATH"] == str(world.ai_root / "runtimes" / VISION_BUILD_ID)
    assert "SECRET_TOKEN" not in env and "HTTP_PROXY" not in env
    scratch = Path(seen["work"])
    assert Path(seen["cwd"]).resolve() == scratch.resolve()
    assert scratch.parent == world.kwargs["evaluation_root"] / driver.WORK_NAME
    assert env["TEMP"] == env["TMP"] == str(scratch)
    assert seen["images_exist"] == [True] and "Request:" in seen["prompt"]
    assert (
        not scratch.exists() and not (world.kwargs["evaluation_root"] / driver.LOCK_NAME).exists()
    )


def test_the_prompt_lists_the_elements_and_the_answer_shape(world: World) -> None:
    case = world.case(contract.KIND_ADHERENCE)
    text = render_visual_prompt(case)
    assert case.prompt in text and text == render_visual_prompt(case)
    assert all(f"- {key}: {value}" in text for key, value in case.elements)
    assert contract.RESPONSE_SCHEMA in text and f'"kind":"{case.kind}"' in text
    for kind in contract.KINDS:
        sample = render_visual_prompt(world.case(kind))
        assert "Answer shape:" in sample and "status" in sample


def test_a_before_after_case_passes_both_images(world: World) -> None:
    run = world.driver().run_case(world.case_set, world.case(contract.KIND_BEFORE_AFTER))
    assert run.evidence.status == driver.STATUS_VALID, run.evidence
    assert world.launches[0][1].count("--image") == 2 and world.recorded()["images_exist"] == [
        True,
        True,
    ]


def test_the_whole_synthetic_set_runs_and_is_scored_with_measurements(world: World) -> None:
    run = world.driver().run_cases(world.case_set, world.labels)
    assert run.complete and run.refusal is None and run.report is not None
    assert len(run.evidence) == len(world.case_set.cases) == len(world.launches) == 13
    assert all(row.status == driver.STATUS_VALID for row in run.evidence)
    assert run.report[contract.DIM_STRUCTURED]["valid_rate"] == 1.0
    assert run.report[contract.DIM_RESOURCES]["measured_cases"] == 13
    assert run.report[contract.DIM_BEFORE_AFTER] is not None


# ============================================================================================= driver: nothing persisted


def test_no_image_prompt_or_answer_text_is_persisted(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    describe = world.case(contract.KIND_DESCRIBE)
    run = world.driver().run_case(world.case_set, describe)
    assert run.text and MARKER in run.text  # the answer exists in memory for scoring
    full = world.driver().run_cases(world.case_set, world.labels)
    document = driver.evidence_document(
        full,
        plan_sha256=NEW_PLAN_DIGEST,
        case_set_sha256=contract.digest({}),
        candidate=world.candidate,
    )
    evidence_file = world.tmp / "evidence.json"
    evidence_file.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    secrets: list[bytes] = [MARKER.encode(), b"\x89PNG"]
    for case in world.case_set.cases:
        secrets.append(case.prompt.encode())
        secrets.extend(text.encode() for _, text in case.elements)
    scanned = 0
    for root in (world.kwargs["evaluation_root"], world.ai_root, evidence_file):
        for path in [root] if root.is_file() else sorted(root.rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                scanned += 1
                if path.parent == world.staged:
                    continue  # the tiny stand-in weights, not run output
                for secret in secrets:
                    assert secret not in data, f"{path} holds run text"
    assert scanned > 3
    assert not any(MARKER in record.getMessage() for record in caplog.records)
    assert not any(
        case.prompt in record.getMessage()
        for case in world.case_set.cases
        for record in caplog.records
    )
    assert set(document["cases"][0]) == {
        "case_id", "status", "reason", "wall_seconds", "peak_working_set_bytes", "peak_private_bytes", "exit_code",
        "argv_shape_sha256", "context_tokens", "cpu_only",
    }  # fmt: skip
    assert MARKER not in json.dumps(document)
    leftovers = list((world.kwargs["evaluation_root"] / driver.WORK_NAME).iterdir())
    assert leftovers == []


# ============================================================================================== driver: admission refusals


def refused(
    world: World, code: str, *reasons: str, kind: str = contract.KIND_ADHERENCE, **overrides: Any
) -> None:
    run = world.driver(**overrides).run_case(world.case_set, world.case(kind))
    assert run.refusal is not None, run.evidence
    assert run.refusal.code == code, run.refusal
    for reason in reasons:
        assert reason in run.refusal.reasons, run.refusal
    assert run.evidence.status == driver.STATUS_NOT_RUN and run.evidence.argv_shape_sha256 == ""
    assert world.launches == [], "a refused case must launch nothing"
    root = world.kwargs["evaluation_root"]
    assert not (root / driver.LOCK_NAME).exists()
    assert not (root / driver.WORK_NAME).exists() or list((root / driver.WORK_NAME).iterdir()) == []


def test_refuses_while_the_invocation_is_not_approved(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract, "INVOCATION_APPROVED", False)
    refused(world, driver.REFUSED_NOT_APPROVED)


def test_refuses_an_evaluation_root_that_is_the_ai_root_or_a_git_tree(world: World) -> None:
    managed = world.tmp / "ManagedAi"
    managed.mkdir()
    refused(
        world, driver.REFUSED_ROOT, "evaluation_root_is_the_ai_assist_root", evaluation_root=managed
    )
    refused(
        world,
        driver.REFUSED_ROOT,
        "evaluation_root_inside_a_git_working_tree",
        evaluation_root=REPO,
    )
    refused(
        world, driver.REFUSED_ROOT, "evaluation_root_missing", evaluation_root=world.tmp / "nowhere"
    )


def test_single_flight_refuses_a_second_launch_while_one_is_held(world: World) -> None:
    lock = world.kwargs["evaluation_root"] / driver.LOCK_NAME
    lock.write_text("held", encoding="utf-8")
    run = world.driver().run_case(world.case_set, world.case(contract.KIND_ADHERENCE))
    assert (
        run.refusal is not None and run.refusal.code == driver.REFUSED_BUSY and world.launches == []
    )
    assert lock.exists(), "a lock this call did not take is never removed"


def test_single_flight_holds_during_a_run_and_is_released_after(world: World) -> None:
    other = world.driver()
    nested: list[driver.CaseRun] = []
    inner_factory = world.kwargs["command_factory"]

    def factory(executable: Path, argv: list[str]) -> list[str]:
        nested.append(other.run_case(world.case_set, world.case(contract.KIND_DEFECT)))
        return inner_factory(executable, argv)

    run = world.driver(command_factory=factory).run_case(
        world.case_set, world.case(contract.KIND_ADHERENCE)
    )
    assert run.evidence.status == driver.STATUS_VALID
    assert nested[0].refusal is not None and nested[0].refusal.code == driver.REFUSED_BUSY
    assert not (world.kwargs["evaluation_root"] / driver.LOCK_NAME).exists()
    assert world.driver().run_case(world.case_set, world.case(contract.KIND_DEFECT)).refusal is None


def test_refuses_without_a_trustworthy_generation_reading(world: World) -> None:
    refused(world, driver.REFUSED_ACTIVITY, activity=None)

    def broken() -> GenerationActivity:
        raise RuntimeError("queue unreadable")

    refused(world, driver.REFUSED_ACTIVITY, activity=broken)
    refused(world, driver.REFUSED_ACTIVITY, activity=lambda: "idle")
    refused(world, driver.REFUSED_GENERATION, activity=lambda: GenerationActivity(running_jobs=1))
    refused(
        world, driver.REFUSED_QUARANTINE, activity=lambda: GenerationActivity(gpu_quarantined=True)
    )


def with_builds(world: World, **vision_changes: Any) -> RuntimeManifest:
    manifest: RuntimeManifest = world.kwargs["runtime_manifest"]
    twin, vision = manifest.builds
    return RuntimeManifest((twin, replace(vision, **vision_changes)))


def test_refuses_a_vision_build_that_is_missing_changed_qualified_or_reachable(
    world: World,
) -> None:
    manifest: RuntimeManifest = world.kwargs["runtime_manifest"]
    refused(
        world,
        driver.REFUSED_VISION_BUILD,
        "vision_build_not_pinned",
        runtime_manifest=RuntimeManifest((manifest.builds[0],)),
    )
    refused(world, driver.REFUSED_VISION_BUILD, "vision_build_differs_from_required_build",
            runtime_manifest=with_builds(world, asset_sha256="b" * 64))  # fmt: skip
    refused(world, driver.REFUSED_VISION_BUILD, "vision_build_differs_from_required_build",
            runtime_manifest=with_builds(world, files={VISION_TOOL: "c" * 64}))  # fmt: skip
    refused(world, driver.REFUSED_VISION_BUILD, "vision_build_wrong_executable",
            runtime_manifest=with_builds(world, executable="llama-completion.exe"))  # fmt: skip
    refused(world, driver.REFUSED_VISION_BUILD, "vision_build_qualified",
            runtime_manifest=with_builds(world, qualified=True))  # fmt: skip
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    listing = replace(
        registry.entries[0],
        compatible_builds=(*registry.entries[0].compatible_builds, VISION_BUILD_ID),
    )
    refused(world, driver.REFUSED_VISION_BUILD, "vision_build_listed_by_a_model",
            registry=ModelRegistry((listing, *registry.entries[1:])))  # fmt: skip
    refused(world, driver.REFUSED_VISION_BUILD, "manifest_or_registry_invalid",
            registry=ModelRegistry(registry.entries, ("entry dropped",)))  # fmt: skip


def test_refuses_a_runtime_that_is_not_imported_or_was_tampered_with(world: World) -> None:
    executable = world.ai_root / "runtimes" / VISION_BUILD_ID / VISION_TOOL
    executable.write_bytes(b"tampered")
    refused(world, driver.REFUSED_RUNTIME, f"runtime_file_hash:{VISION_TOOL}")
    executable.unlink()
    refused(world, driver.REFUSED_RUNTIME, "runtime_not_imported")


def test_refuses_without_an_attestation_for_this_build_and_executable(world: World) -> None:
    root = world.ai_root
    (root / "egress_attestation.json").unlink()
    refused(world, driver.REFUSED_ATTESTATION)
    record_attestation(root, "legacy free text only")  # a version-1 record covers nothing
    refused(world, driver.REFUSED_ATTESTATION)
    record_attestation(root, "text build only", [("b11960-cpu", "llama-completion.exe")])
    refused(world, driver.REFUSED_ATTESTATION)
    record_attestation(root, "right build, wrong exe", [(VISION_BUILD_ID, "llama-completion.exe")])
    refused(world, driver.REFUSED_ATTESTATION)
    record_attestation(root, "right exe, wrong build", [("b11960-cpu", VISION_TOOL)])
    refused(world, driver.REFUSED_ATTESTATION)


def test_refuses_without_memory_headroom(world: World) -> None:
    refused(world, driver.REFUSED_MEMORY_UNREADABLE, memory_probe=lambda: None)

    def broken() -> HostMemory:
        raise OSError("no")

    refused(world, driver.REFUSED_MEMORY_UNREADABLE, memory_probe=broken)
    refused(world, driver.REFUSED_MEMORY, memory_probe=lambda: HostMemory(1.0, 64.0))
    refused(world, driver.REFUSED_COMMIT, memory_probe=lambda: HostMemory(64.0, 1.0))
    refused(
        world, driver.REFUSED_MEMORY_UNREADABLE, memory_probe=lambda: HostMemory(float("nan"), 64.0)
    )


def test_refuses_images_that_are_missing_unpinned_or_unsafe(world: World) -> None:
    case = world.case(contract.KIND_ADHERENCE)
    asset = next(item for item in world.case_set.assets if item.asset_id == case.asset_ids[0])
    path = world.kwargs["assets_dir"] / f"{asset.asset_id}.png"
    original = path.read_bytes()
    path.write_bytes(original + b"x")
    refused(world, driver.REFUSED_IMAGE, "image_does_not_match_its_pin")
    path.write_bytes(original)
    path.unlink()
    refused(world, driver.REFUSED_IMAGE, "image_missing")
    # A pinned file that is not a PNG at all (the pin matches the junk) is still refused by the header check.
    junk = b"GIF89a" + b"\x00" * 64
    path.write_bytes(junk)
    pinned = replace(asset, sha256=sha(junk), bytes=len(junk))
    edited = replace(
        world.case_set, assets=tuple(pinned if a is asset else a for a in world.case_set.assets)
    )
    run = world.driver().run_case(edited, case)
    assert (
        run.refusal is not None
        and run.refusal.reasons == ("image_not_png_or_jpeg",)
        and world.launches == []
    )
    # Pinned and well-formed but larger than the dimension ceiling.
    huge = png_header(5000, 10) + b"\x00" * 32
    path.write_bytes(huge)
    pinned = replace(asset, sha256=sha(huge), bytes=len(huge))
    edited = replace(
        world.case_set, assets=tuple(pinned if a is asset else a for a in world.case_set.assets)
    )
    run = world.driver().run_case(edited, case)
    assert run.refusal is not None and run.refusal.reasons == ("image_dimensions_out_of_range",)
    path.write_bytes(original)
    # An asset id the case set does not know.
    foreign = replace(case, asset_ids=("ghost",))
    run = world.driver().run_case(world.case_set, foreign)
    assert (
        run.refusal is not None
        and run.refusal.reasons == ("unknown_asset",)
        and world.launches == []
    )


def test_refuses_a_candidate_that_admission_refuses(world: World) -> None:
    refused(world, driver.REFUSED_CANDIDATE, cand.REASON_LICENSE_MISSING, acknowledgement=None)
    refused(world, driver.REFUSED_CANDIDATE, cand.REASON_LICENSE_MISMATCH,
            acknowledgement=acknowledgement(world.candidate, license_text_sha256="0" * 64))  # fmt: skip
    refused(world, driver.REFUSED_CANDIDATE, cand.REASON_LICENSE_MISSING,
            acknowledgement=acknowledgement(world.candidate, owner_acknowledged=False))  # fmt: skip
    model = world.staged / world.candidate.model.filename
    original = model.read_bytes()
    model.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    refused(world, driver.REFUSED_CANDIDATE, cand.REASON_MODEL_HASH)
    model.write_bytes(original)
    (world.staged / world.candidate.projector.filename).unlink()
    refused(world, driver.REFUSED_CANDIDATE, cand.REASON_PROJECTOR_MISSING)


def test_a_cancel_before_launch_runs_nothing(world: World) -> None:
    refused(world, driver.REFUSED_CANCELLED, cancel=lambda: True)


# ===================================================================== driver: cancellation, limits and output handling


def test_cancellation_mid_run_stops_the_child_and_cleans_up(world: World) -> None:
    world.respond("@sleep")
    started = time.monotonic()
    run = world.driver(cancel=world.record.exists).run_case(
        world.case_set, world.case(contract.KIND_ADHERENCE)
    )
    assert time.monotonic() - started < 30
    assert run.refusal is None and run.evidence.status == driver.STATUS_CANCELLED
    assert run.evidence.reason == "request_cancelled" and run.text == ""
    assert not Path(world.recorded()["work"]).exists()
    assert not (world.kwargs["evaluation_root"] / driver.LOCK_NAME).exists()


def test_a_cancelled_set_stops_without_a_score(world: World) -> None:
    world.respond("@sleep")
    run = world.driver(cancel=world.record.exists).run_cases(world.case_set, world.labels)
    assert run.complete is False and run.report is None and len(run.evidence) == 1
    assert run.refusal is not None and run.refusal.code == driver.REFUSED_CANCELLED


def test_generation_that_starts_mid_run_stops_the_child(world: World) -> None:
    readings = iter([idle()])

    def activity() -> GenerationActivity:
        return next(readings, GenerationActivity(running_jobs=1))

    world.respond("@sleep")
    run = world.driver(activity=activity, watch_interval=0.0).run_case(
        world.case_set, world.case(contract.KIND_ADHERENCE)
    )
    assert (
        run.evidence.status == driver.STATUS_CANCELLED
        and run.evidence.reason == driver.REFUSED_GENERATION
    )


def test_the_wall_clock_limit_kills_a_stuck_child(world: World) -> None:
    world.respond("@sleep")
    run = world.driver(limits=VisualLimits(timeout_seconds=1.0)).run_case(
        world.case_set, world.case(contract.KIND_ADHERENCE)
    )
    assert (
        run.evidence.status == driver.STATUS_TIMEOUT and run.evidence.reason == "wall_clock_limit"
    )
    assert run.evidence.wall_seconds < 20


def test_exit_codes_and_oversized_output_are_reported_not_scored_as_answers(world: World) -> None:
    case = world.case(contract.KIND_ADHERENCE)
    world.respond("@exit:3")
    failed = world.driver().run_case(world.case_set, case)
    assert (failed.evidence.status, failed.evidence.exit_code) == (driver.STATUS_CHILD_FAILED, 3)
    world.respond("@big")
    big = world.driver().run_case(world.case_set, case)
    assert big.evidence.status == driver.STATUS_TOO_LARGE and big.text == ""


def adherence_payload(world: World) -> dict[str, Any]:
    case = world.case(contract.KIND_ADHERENCE)
    return {"answers": [{"id": key, "value": True} for key, _ in case.elements]}


def test_output_goes_through_strict_json_then_the_contract_validator(world: World) -> None:
    case = world.case(contract.KIND_ADHERENCE)
    good = answer(world, case.kind, **adherence_payload(world))
    duplicate = good[:-1] + ',"status":"ok"}'
    cases: list[tuple[str | bytes, str, str]] = [
        (good, driver.STATUS_VALID, ""),
        (good + "\n[end of text]\n", driver.STATUS_VALID, ""),
        (good + "\r\n [end of text]\r\n", driver.STATUS_VALID, ""),
        ("Sure! " + good, driver.STATUS_INVALID, "not_json"),
        ("{not json", driver.STATUS_INVALID, "not_json"),
        (duplicate, driver.STATUS_INVALID, "not_json"),
        (good.replace("true", "NaN", 1), driver.STATUS_INVALID, "not_json"),
        (b"\xff\xfe" + good.encode(), driver.STATUS_INVALID, "not_utf8"),
        ("[]", driver.STATUS_INVALID, "not_an_object"),
        (json.dumps({"schema": "wrong/1", "status": "ok"}), driver.STATUS_INVALID, "bad_schema"),
        (answer(world, contract.KIND_DEFECT, findings=[]), driver.STATUS_INVALID, "kind_mismatch"),
        (answer(world, case.kind, answers=[]), driver.STATUS_INVALID, "bad_list"),
        (
            answer(world, case.kind, answers=[{"id": "nope", "value": True}]),
            driver.STATUS_INVALID,
            "answers_do_not_match_elements",
        ),  # fmt: skip
        (
            answer(world, case.kind, **adherence_payload(world), extra=1),
            driver.STATUS_INVALID,
            "unknown_keys",
        ),
        (
            json.dumps(
                {
                    "schema": contract.RESPONSE_SCHEMA,
                    "status": "refused",
                    "refusal_reason": "cannot tell",
                }
            ),
            driver.STATUS_MODEL_REFUSED,
            "",
        ),  # fmt: skip
        ("", driver.STATUS_INVALID, "not_json"),
    ]
    for text, status, reason in cases:
        world.respond(text)
        run = world.driver().run_case(world.case_set, case)
        assert (run.evidence.status, run.evidence.reason) == (status, reason), (text, run.evidence)
    assert driver.strict_json('{"a": 1}') and not driver.strict_json('{"a":1,"a":2}')
    assert not driver.strict_json("Infinity") and not driver.strict_json("")


def test_a_failed_case_in_a_set_is_scored_as_wrong_never_skipped(world: World) -> None:
    world.respond("{not json")
    run = world.driver().run_cases(world.case_set, world.labels)
    assert run.complete and run.report is not None
    assert run.report[contract.DIM_STRUCTURED]["invalid_rate"] == 1.0
    assert all(row.status == driver.STATUS_INVALID for row in run.evidence)


def test_the_first_admission_refusal_stops_a_set(world: World) -> None:
    run = world.driver(activity=None).run_cases(world.case_set, world.labels)
    assert run.refusal is not None and run.refusal.code == driver.REFUSED_ACTIVITY
    assert (
        len(run.evidence) == 1 and run.report is None and not run.complete and world.launches == []
    )


# ======================================================================================== no own process, thread or socket


def test_the_driver_has_no_process_thread_or_socket_code_of_its_own() -> None:
    forbidden = {
        "subprocess", "threading", "_thread", "multiprocessing", "concurrent", "socket", "ssl", "http", "urllib",
        "asyncio", "ctypes", "requests", "httpx", "huggingface_hub", "llama_cpp", "torch", "psutil",
    }  # fmt: skip
    for name in ("driver.py", "visual_argv.py", "prompts.py"):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"{name} imports {module}"
        for needle in (
            "Popen",
            "os.system",
            "os.startfile",
            "os.spawn",
            "os.kill",
            "terminate(",
            ".kill(",
        ):
            assert needle not in source, f"{name} contains {needle}"
    driver_source = (PACKAGE / "driver.py").read_text(encoding="utf-8")
    assert "from src.utils.managed_process import run_bounded" in driver_source
    default = inspect.signature(driver.VisualDriver.__init__).parameters["runner"].default
    assert default is run_bounded


def test_the_driver_writes_nothing_under_the_ai_root(world: World) -> None:
    before = sorted(path.relative_to(world.ai_root).as_posix() for path in world.ai_root.rglob("*"))
    stamps = {path: path.stat().st_mtime_ns for path in world.ai_root.rglob("*") if path.is_file()}
    run = world.driver().run_case(world.case_set, world.case(contract.KIND_ADHERENCE))
    assert run.evidence.status == driver.STATUS_VALID
    assert (
        sorted(path.relative_to(world.ai_root).as_posix() for path in world.ai_root.rglob("*"))
        == before
    )
    assert {
        path: path.stat().st_mtime_ns for path in world.ai_root.rglob("*") if path.is_file()
    } == stamps


# ================================================================================================================ the CLI


def cli_args(world: World, digest: str, *extra: str) -> list[str]:
    return [
        "evaluate", "--evaluation-root", str(world.kwargs["evaluation_root"]), "--assets", str(world.kwargs["assets_dir"]),
        "--acknowledgement", str(world.tmp / "ack.json"), "--evidence-out", str(world.tmp / "evidence.json"),
        "--i-have-the-plan-digest", digest, "--ai-root", str(world.ai_root), *extra,
    ]  # fmt: skip


def test_the_cli_refuses_a_missing_or_wrong_plan_digest_before_touching_anything(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the driver must not be built")

    monkeypatch.setattr(driver, "VisualDriver", boom)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "evaluate",
                "--evaluation-root",
                "x",
                "--assets",
                "y",
                "--acknowledgement",
                "z",
                "--evidence-out",
                "e",
            ]
        )
    for wrong in (
        OLD_PLAN_DIGEST,
        RUN1_PLAN_DIGEST,
        RUN2_PLAN_DIGEST,
        "0" * 64,
        "",
        NEW_PLAN_DIGEST[:-1],
        NEW_PLAN_DIGEST + "0",
    ):
        assert cli.main(cli_args(world, wrong)) == 2
        assert driver.REFUSED_PLAN_DIGEST in capsys.readouterr().err
    assert not (world.tmp / "evidence.json").exists()


def test_the_cli_refuses_while_the_invocation_is_not_approved(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(contract, "INVOCATION_APPROVED", False)
    assert cli.main(cli_args(world, plan.build_plan()["plan_sha256"])) == 2
    assert driver.REFUSED_NOT_APPROVED in capsys.readouterr().err


def test_the_cli_with_the_right_digest_still_needs_every_gate(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = plan.build_plan()["plan_sha256"]
    assert digest == NEW_PLAN_DIGEST
    (world.tmp / "ack.json").write_text(
        json.dumps(acknowledgement(world.candidate)), encoding="utf-8"
    )
    # No --generation-idle: the activity reading is absent, so the very first gate refuses and nothing launches.
    assert cli.main(cli_args(world, digest.upper())) == 1
    assert driver.REFUSED_ACTIVITY in capsys.readouterr().err
    document = json.loads((world.tmp / "evidence.json").read_text(encoding="utf-8"))
    assert document["refusal"]["code"] == driver.REFUSED_ACTIVITY and document["complete"] is False
    assert document["plan_sha256"] == digest and document["report"] is None
    assert world.launches == []
    # An existing evidence file is never overwritten.
    assert cli.main(cli_args(world, digest)) == 2
    # With the host asserted idle, the real (unattested, un-imported) AI root and runtime still refuse.
    (world.tmp / "evidence.json").unlink()
    assert cli.main(cli_args(world, digest, "--generation-idle")) == 1
    assert "refused:" in capsys.readouterr().err
    refusal = json.loads((world.tmp / "evidence.json").read_text(encoding="utf-8"))["refusal"]
    assert refusal["code"] in (driver.REFUSED_VISION_BUILD, driver.REFUSED_RUNTIME)


def test_the_cli_cases_and_labels_go_together(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = plan.build_plan()["plan_sha256"]
    assert cli.main(cli_args(world, digest, "--cases", str(world.tmp / "cases.json"))) == 2
    assert "go together" in capsys.readouterr().err


def test_the_only_cli_command_that_can_launch_is_evaluate() -> None:
    source = (PACKAGE / "__main__.py").read_text(encoding="utf-8")
    assert source.count("driver.VisualDriver(") == 1 and "run_bounded" not in source
    with pytest.raises(SystemExit):
        cli.main(["run"])


# ===================================================== the flipped flag and the new plan digest (owner decision 2026-11-14)


def test_the_flag_flips_only_because_every_contract_gate_is_implemented() -> None:
    assert contract.INVOCATION_APPROVED is True
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    assert manifest.find(VISION_BUILD_ID) is not None  # gate 1: the separate pinned build entry
    assert callable(build_visual_argv) and callable(
        check_visual_argv
    )  # gate 2: the closed vocabulary and builder
    assert (
        inspect.signature(driver.VisualDriver.__init__).parameters["runner"].default is run_bounded
    )  # gate 3
    for refusal in (  # gate 4: fail-closed admission, each a stable code
        driver.REFUSED_NOT_APPROVED, driver.REFUSED_BUSY, driver.REFUSED_ACTIVITY, driver.REFUSED_GENERATION,
        driver.REFUSED_VISION_BUILD, driver.REFUSED_RUNTIME, driver.REFUSED_ATTESTATION, driver.REFUSED_MEMORY,
        driver.REFUSED_IMAGE, driver.REFUSED_CANDIDATE,
    ):  # fmt: skip
        assert isinstance(refusal, str) and refusal
    assert callable(driver.check_output) and callable(driver.strict_json)  # gate 5: output handling
    assert callable(driver.evidence_document)  # gate 6: evidence
    assert (
        "-ngl" in visual_argv.VISUAL_VALUE_FLAGS
        and "--no-mmproj-offload" in visual_argv.VISUAL_SWITCHES
    )  # gate 7


def test_the_plan_digest_chain_differs_step_by_step_only_by_what_each_package_changed() -> None:
    current = plan.build_plan()
    assert len({current["plan_sha256"], RUN2_PLAN_DIGEST, RUN1_PLAN_DIGEST, OLD_PLAN_DIGEST}) == 4
    assert current["plan_sha256"] == NEW_PLAN_DIGEST
    body = copy.deepcopy({key: value for key, value in current.items() if key != "plan_sha256"})
    # PR-AI-VL-223 added exactly one section to the plan the second run executed; removing it gives that plan back.
    run2 = copy.deepcopy(body)
    del run2["template_ab"]
    assert contract.digest(run2) == RUN2_PLAN_DIGEST
    assert {key for key in body if key not in run2} == {"template_ab"}
    # PR-AI-VL-222 added exactly one section to the plan the first run executed; removing it gives that plan back.
    run1 = copy.deepcopy(run2)
    del run1["diagnostic"]
    assert contract.digest(run1) == RUN1_PLAN_DIGEST
    assert {key for key in run2 if key not in run1} == {"diagnostic"}
    # And the first run's plan differs from the owner-approved one only by the flag and the reason text.
    reverted = copy.deepcopy(run1)
    reverted["image_invocation"]["approved"] = False
    candidate_row = next(
        row
        for row in reverted["comparators"]
        if row["comparator_id"] == "lfm3-vl-2b-q4_k_m-liquidai"
    )
    candidate_row["reasons"] = ["image_invocation_not_approved", *candidate_row["reasons"]]
    assert contract.digest(reverted) == OLD_PLAN_DIGEST
    # And nothing else differs: every other field of the plan is the one the owner authorized.
    changed = {key for key in run1 if run1[key] != reverted[key]}
    assert changed == {"image_invocation", "comparators"}
    assert {
        k
        for k in run1["image_invocation"]
        if run1["image_invocation"][k] != reverted["image_invocation"][k]
    } == {"approved"}
    assert body["executes_models"] is False


def test_the_documents_name_the_new_plan_digest_and_the_prior_one() -> None:
    for relative in (plan.EVALUATION_DOCUMENT, plan.INVOCATION_DOCUMENT):
        text = (REPO / relative).read_text(encoding="utf-8")
        assert NEW_PLAN_DIGEST in text, relative
        assert RUN2_PLAN_DIGEST in text, relative
        assert RUN1_PLAN_DIGEST in text, relative
        assert OLD_PLAN_DIGEST in text, relative
