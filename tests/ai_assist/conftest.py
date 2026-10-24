"""Shared hermetic fixtures: a fake installation under tmp_path and a fake inference child.

No real model, binary, GPU, network or display is used. The "child" is a tiny Python script launched through the real
``run_bounded``, so containment, timeout, cancellation and output caps are exercised for real.
"""

from __future__ import annotations

import hashlib
import io
import sys
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.ai_assist.contracts import AssistRequest, SuggestionKind
from src.ai_assist.host import GenerationActivity, HostMemory
from src.ai_assist.manifests import (
    ModelEntry,
    ModelRegistry,
    Provenance,
    RuntimeBuild,
    RuntimeManifest,
    import_model,
    import_runtime,
    record_active,
)
from src.ai_assist.runtime import AiRuntime

FAKE_CHILD = textwrap.dedent(
    """
    import json, os, subprocess, sys, time
    sys.stdout.reconfigure(encoding="utf-8")  # the real runtime writes UTF-8; a Windows console codepage would not
    argv = sys.argv[1:]
    prompt = open(argv[argv.index("-f") + 1], encoding="utf-8").read()
    lines = {line.split(":", 1)[0]: line.split(":", 1)[1] for line in prompt.splitlines() if line.startswith("TEST_")}
    mode = lines.get("TEST_MODE", "ok")
    record = lines.get("TEST_RECORD")
    if record:
        with open(record, "w", encoding="utf-8") as handle:
            json.dump({"argv": argv, "cuda": os.environ.get("CUDA_VISIBLE_DEVICES"), "env": sorted(os.environ),
                       "no_proxy": os.environ.get("NO_PROXY"), "cwd": os.getcwd(),
                       "llama": {k: v for k, v in os.environ.items() if k.upper().startswith("LLAMA")}}, handle)
    alloc_mb = int(lines.get("TEST_ALLOC_MB", "0"))
    held = (bytearray(b"x") * (alloc_mb * 1024 * 1024)) if alloc_mb else None
    time.sleep(float(lines.get("TEST_SLEEP", "0")))
    pidfile = lines.get("TEST_PIDFILE")
    selfpid = lines.get("TEST_SELFPID")
    if selfpid:
        with open(selfpid, "w") as handle:
            handle.write(str(os.getpid()))
    positive = prompt.split("POSITIVE_PROMPT:", 1)[1].split("NEGATIVE_PROMPT:", 1)[0].strip("\\n")
    schema = "ai_assist.suggestion/1"
    if mode == "sleep":
        time.sleep(120)
    elif mode == "grandchild":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        with open(pidfile, "w") as handle:
            handle.write(str(child.pid))
        time.sleep(120)
    elif mode == "status_refused":
        print(json.dumps({"schema": schema, "status": "refused", "refusal_reason": "policy"}))
    elif mode == "text_refusal":
        print("I can\\u2019t help with that request.")
    elif mode == "malformed":
        print("{not json")
    elif mode == "extra_text":
        print("Sure! " + json.dumps({"schema": schema, "status": "ok"}))
    elif mode == "big":
        sys.stdout.write("x" * (2 * 1024 * 1024))
    elif mode == "echo_prompt":
        sys.stdout.write(prompt)
        print(json.dumps({"schema": schema, "status": "ok", "kind": "prompt_rewrite", "positive": positive,
                          "negative": "", "changes": []}))
    elif mode == "banner":
        print("llama.cpp build b0000")
        print(json.dumps({"schema": schema, "status": "ok", "kind": "prompt_rewrite", "positive": positive,
                          "negative": "", "changes": []}))
        print("[end of text]")
    elif mode == "timings":
        print(json.dumps({"schema": schema, "status": "ok", "kind": "prompt_rewrite", "positive": positive,
                          "negative": "", "changes": []}))
        print("llama_print_timings: eval time = 1234.5 ms / 87 runs ( 14.19 ms per token, 70.46 tokens per second)")
    elif mode == "exit3":
        sys.exit(3)
    elif mode == "wrong_enum":
        print(json.dumps({"schema": schema, "status": "ok", "kind": "workflow_choice", "workflow": "evil"}))
    elif mode == "add_lora":
        print(json.dumps({"schema": schema, "status": "ok", "kind": "prompt_rewrite",
                          "positive": positive + " <lora:injected:1>", "negative": "", "changes": ["added_detail"]}))
    else:
        print(json.dumps({"schema": schema, "status": "ok", "kind": "prompt_rewrite",
                          "positive": positive.replace("TEST_", "T_"), "negative": "", "changes": ["clarified_wording"]}))
    """
)


@dataclass
class Install:
    root: Path
    manifest: RuntimeManifest
    registry: ModelRegistry
    build: RuntimeBuild
    entry: ModelEntry
    child: Path

    def runtime(self, runner=None, extra_environ=None) -> AiRuntime:
        kwargs = {} if runner is None else {"runner": runner}
        return AiRuntime(
            self.root,
            command_factory=lambda _exe, argv: [sys.executable, str(self.child), *argv],
            environ={
                "SystemRoot": "C:/Windows",
                "SECRET_TOKEN": "must-not-leak",
                "HTTP_PROXY": "http://x",
                **(extra_environ or {}),
            },
            **kwargs,
        )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_provenance() -> Provenance:
    return Provenance(
        publisher_repo="Qwen/Qwen3.5-9B",
        publisher_revision="abc1234",
        packager_repo="example/Qwen3.5-9B-GGUF",
        packager_revision="def5678",
        converter="llama.cpp convert_hf_to_gguf.py b0000",
        source_url="https://example.invalid/model",
    )


FILES = {"llama-cli.exe": b"fake llama binary", "ggml.dll": b"fake ggml library"}
MODEL_BYTES = b"GGUF" + b"\x00" * 252


def build_archive(files: dict[str, bytes], extra: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in {**files, **(extra or {})}.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def make_build(archive: bytes, *, qualified: bool = True) -> RuntimeBuild:
    return RuntimeBuild(
        build_id="b0000-cpu",
        upstream_repository="https://example.invalid/llama.cpp",
        upstream_tag="b0000",
        asset_name="llama-b0000-bin-win-cpu-x64.zip",
        asset_sha256=sha(archive),
        asset_bytes=len(archive),
        license_spdx="MIT",
        executable="llama-cli.exe",
        files={name: sha(data) for name, data in FILES.items()},
        qualified=qualified,
    )


def make_entry(*, qualified: bool = True) -> ModelEntry:
    return ModelEntry(
        model_id="fake-9b-q4",
        display_name="Fake 9B Q4",
        license_spdx="Apache-2.0",
        architecture="qwen3_5",
        quantization="Q4_K_M",
        filename="fake-9b-q4.gguf",
        bytes=len(MODEL_BYTES),
        sha256=sha(MODEL_BYTES),
        provenance=make_provenance(),
        qualified=qualified,
    )


@pytest.fixture
def installation(tmp_path: Path) -> Install:
    archive_bytes = build_archive(FILES, {"README.txt": b"docs"})
    build = make_build(archive_bytes)
    entry = make_entry()
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(archive_bytes)
    model = tmp_path / "model.gguf"
    model.write_bytes(MODEL_BYTES)
    root = tmp_path / "ai"
    import_runtime(archive, build, root)
    import_model(model, entry, root)
    record_active(root, build, entry)
    child = tmp_path / "fake_child.py"
    child.write_text(FAKE_CHILD, encoding="utf-8")
    return Install(
        root=root,
        manifest=RuntimeManifest((build,)),
        registry=ModelRegistry((entry,)),
        build=build,
        entry=entry,
        child=child,
    )


def request_for(
    mode: str = "ok", *, request_id: str = "r1", extra: str = "", **overrides
) -> AssistRequest:
    text = f"a red barn <lora:barn:0.8> [[season]]\nTEST_MODE:{mode}\n{extra}".rstrip("\n")
    values = {
        "request_id": request_id,
        "kind": SuggestionKind.PROMPT_REWRITE,
        "positive_text": text,
        "negative_text": "",
        "target_policy_id": "sdxl",
    }
    values.update(overrides)
    return AssistRequest(**values)


def idle() -> GenerationActivity:
    return GenerationActivity(running_jobs=0, gpu_quarantined=False)


def roomy() -> HostMemory:
    return HostMemory(available_gib=24.0, commit_headroom_gib=30.0)
