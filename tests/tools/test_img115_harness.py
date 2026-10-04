"""PR-IMG-115: the FLUX.2 Klein 4B FP8 qualification harness, proven with fakes only (no GPU, network or download)."""

from __future__ import annotations

import base64
import io
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import tools.qualification.img115.run as run_module
from tools.qualification.img115 import api, spec
from tools.qualification.img115.runtime import OwnedForge, assert_isolated, build_layout

REPO = Path(__file__).resolve().parents[2]
RUNTIME_SRC = (REPO / "tools" / "qualification" / "img115" / "runtime.py").read_text(encoding="utf-8")
ALL_SRC = "".join(p.read_text(encoding="utf-8") for p in (REPO / "tools" / "qualification" / "img115").glob("*.py"))


# --- assets ----------------------------------------------------------------------------------------------


def _small_asset(monkeypatch, tmp_path: Path, role: str, content: bytes = b"weights") -> Path:
    import hashlib

    original = spec.ASSETS[role]
    small = spec.Asset(original.role, original.repo, original.revision, original.remote_path, original.filename, len(content),
                       hashlib.sha256(content).hexdigest(), original.models_subdir)
    monkeypatch.setitem(spec.ASSETS, role, small)
    path = tmp_path / original.filename
    path.write_bytes(content)
    return path


def test_the_frozen_identities_are_the_exact_baseline_stack():
    assert spec.ASSETS["transformer"].sha256 == "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6"
    assert spec.ASSETS["transformer"].size == 4_070_624_520 and spec.ASSETS["transformer"].repo == "black-forest-labs/FLUX.2-klein-4b-fp8"
    assert spec.ASSETS["text_encoder"].filename == "qwen_3_4b.safetensors" and spec.ASSETS["text_encoder"].models_subdir == "text_encoder"
    assert spec.ASSETS["vae"].filename == "flux2-vae.safetensors" and spec.ASSETS["vae"].models_subdir == "VAE"
    assert set(spec.ASSETS) == {"transformer", "text_encoder", "vae"}
    for asset in spec.ASSETS.values():
        assert len(asset.revision) == 40 and len(asset.sha256) == 64  # pinned revisions, never a branch


def test_only_the_exact_transformer_hash_is_accepted(monkeypatch, tmp_path):
    path = _small_asset(monkeypatch, tmp_path, "transformer")
    assert spec.verify_asset("transformer", path)["sha256"] == spec.ASSETS["transformer"].sha256
    path.write_bytes(b"weightz")  # same size, different content
    with pytest.raises(ValueError, match="sha256"):
        spec.verify_asset("transformer", path)
    path.write_bytes(b"short")
    with pytest.raises(ValueError, match="size"):
        spec.verify_asset("transformer", path)
    with pytest.raises(ValueError, match="missing"):
        spec.verify_asset("transformer", tmp_path / "gone" / "flux-2-klein-4b-fp8.safetensors")


@pytest.mark.parametrize(
    "name",
    ["flux-2-klein-4b.safetensors", "flux-2-klein-base-4b-fp8.safetensors", "flux-2-klein-9b-fp8.safetensors",
     "flux-2-klein-4b-Q8_0.gguf", "flux-2-klein-4b-nvfp4.safetensors", "flux-2-klein-4b-bf16.safetensors",
     "community-requant-fp8.safetensors"],
)
def test_substituted_transformers_are_rejected(name):
    stack = {r: a.filename for r, a in spec.ASSETS.items()} | {"transformer": name}
    with pytest.raises(ValueError, match="not the frozen"):
        spec.reject_substitution(stack)
    with pytest.raises(ValueError):  # also when presented as a file on disk
        spec.verify_asset("transformer", Path(name))


@pytest.mark.parametrize(
    ("role", "name"),
    [("text_encoder", "qwen_3_8b.safetensors"), ("text_encoder", "mistral_3_small_flux2_fp8.safetensors"),
     ("vae", "ae.safetensors"), ("vae", "flux1-vae.safetensors")],
)
def test_the_required_qwen3_4b_and_flux2_vae_cannot_be_substituted(role, name):
    stack = {r: a.filename for r, a in spec.ASSETS.items()} | {role: name}
    with pytest.raises(ValueError):
        spec.reject_substitution(stack)
    with pytest.raises(ValueError, match="stack is exactly"):
        spec.reject_substitution({"transformer": "flux-2-klein-4b-fp8.safetensors"})  # an incomplete stack


# --- frozen cases ----------------------------------------------------------------------------------------


def test_exactly_four_cases_with_the_frozen_distilled_inference_and_fixed_seeds():
    assert list(spec.CASES) == ["A", "B", "C", "D"]
    assert [c["seed"] for c in spec.CASES.values()] == [424242, 424243, 424244, 424245]
    assert [(c["width"], c["height"]) for c in spec.CASES.values()] == [(768, 1024), (1024, 1024), (768, 1024), (768, 1024)]
    for case in spec.CASES.values():
        assert (case["steps"], case["cfg_scale"], case["sampler_name"], case["scheduler"]) == (4, 1.0, "Euler", "Beta")
        assert case["negative_prompt"] == ""


def test_edit_cases_chain_to_their_references():
    assert spec.CASES["A"]["references"] == [] and spec.CASES["B"]["references"] == []
    assert spec.CASES["C"]["references"] == ["A"]
    assert spec.CASES["D"]["references"] == ["A", "B"]
    assert spec.CASES["A"]["kind"] == spec.CASES["B"]["kind"] == "txt2img" and spec.CASES["C"]["kind"] == spec.CASES["D"]["kind"] == "edit"


def test_payloads_carry_the_frozen_parameters_and_use_the_builtin_reference_mechanism():
    text = api.build_payload("A", [])
    assert (text["steps"], text["cfg_scale"], text["seed"], text["width"], text["height"]) == (4, 1.0, 424242, 768, 1024)
    assert "alwayson_scripts" not in text and "override_settings" not in text and text["negative_prompt"] == ""
    two = api.build_payload("D", ["r1", "r2"])
    assert two["init_images"] == ["r1"] and two["denoising_strength"] == 1.0 and two["seed"] == 424245  # reference 1 = init image
    assert two["alwayson_scripts"]["ImageStitch Integrated"]["args"] == [True, ["r2"], 1024]  # further references: built-in script
    one = api.build_payload("C", ["r1"])
    assert one["init_images"] == ["r1"] and "alwayson_scripts" not in one and one["seed"] == 424244
    assert [api.endpoint_for(c) for c in "ABCD"] == ["/sdapi/v1/txt2img"] * 2 + ["/sdapi/v1/img2img"] * 2
    with pytest.raises(ValueError):
        api.build_payload("D", ["only-one"])
    with pytest.raises(ValueError):
        api.build_payload("A", ["unexpected"])


def test_the_model_stack_is_selected_through_options_with_exact_names(tmp_path):
    options = api.options_payload(tmp_path / "models")
    assert options["sd_model_checkpoint"] == "flux-2-klein-4b-fp8.safetensors"
    assert [Path(m).name for m in options["forge_additional_modules"]] == ["qwen_3_4b.safetensors", "flux2-vae.safetensors"]
    assert "forge_unet_storage_dtype" not in options  # 'Diffusion in Low Bits' stays Automatic


# --- references -------------------------------------------------------------------------------------------


def test_missing_or_changed_reference_hashes_are_refused(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png-bytes")
    import hashlib

    good = hashlib.sha256(b"png-bytes").hexdigest()
    assert base64.b64decode(api.encode_reference(ref, good)) == b"png-bytes"
    ref.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed since it was frozen"):
        api.encode_reference(ref, good)
    with pytest.raises(FileNotFoundError):
        api.encode_reference(tmp_path / "missing.png", good)


def test_case_d_uses_the_frozen_fallback_only_when_case_b_did_not_pass(tmp_path):
    ledger = api.Ledger(tmp_path / "ledger.json")
    ledger.data["cases"] = {"A": {"state": "passed", "png_path": "a.png", "png_sha256": "a" * 64},
                            "B": {"state": "failed"}}
    frozen = {"fallback_reference_2": {"path": "fallback.png", "sha256": "f" * 64}}
    assert api.resolve_references("D", ledger, frozen) == [(Path("a.png"), "a" * 64), (Path("fallback.png"), "f" * 64)]
    ledger.data["cases"]["B"] = {"state": "passed", "png_path": "b.png", "png_sha256": "b" * 64}
    assert api.resolve_references("D", ledger, frozen)[1] == (Path("b.png"), "b" * 64)
    ledger.data["cases"]["A"] = {"state": "failed"}
    with pytest.raises(RuntimeError, match="did not pass"):
        api.resolve_references("C", ledger, frozen)


# --- ledger: no retry, no replay, hard stop ---------------------------------------------------------------


def test_the_ledger_never_allows_a_retry_a_second_dispatch_or_progress_after_a_hard_stop(tmp_path):
    ledger = api.Ledger(tmp_path / "ledger.json")
    with pytest.raises(RuntimeError, match="Case A must pass"):
        ledger.begin("B")
    ledger.begin("A")
    ledger.mark_dispatched("A")
    with pytest.raises(RuntimeError, match="second dispatch"):
        ledger.mark_dispatched("A")
    with pytest.raises(RuntimeError, match="no retry"):
        ledger.begin("A")  # even after a crash the case stays 'dispatched'
    assert api.Ledger(tmp_path / "ledger.json").state("A") == "dispatched"  # survives a process restart
    ledger.finish("A", "passed", png_path="a.png", png_sha256="a" * 64)
    ledger.set_hard_stop("GPU event")
    with pytest.raises(RuntimeError, match="hard-stopped"):
        ledger.begin("B")


def test_a_frozen_manifest_cannot_change_after_freezing():
    manifest = {"a": 1}
    manifest["manifest_sha256"] = api.frozen_digest(manifest)
    api.check_frozen(manifest)
    manifest["a"] = 2
    with pytest.raises(ValueError, match="changed after it was frozen"):
        api.check_frozen(manifest)


# --- isolation and lifecycle ------------------------------------------------------------------------------


def test_roots_stay_outside_the_repository_the_managed_install_and_application_envs(tmp_path):
    install = tmp_path / "Forge" / "neo-d70373eb"
    install.mkdir(parents=True)
    assert_isolated(tmp_path / "qual", repo_root=REPO, managed_install=install)
    for bad in (REPO / "qual", install / "data" / "qual", REPO):
        with pytest.raises(ValueError, match="outside"):
            assert_isolated(bad, repo_root=REPO, managed_install=install)
    for marker in (".venv", "stable-diffusion-webui", "ComfyRuntime"):
        with pytest.raises(ValueError, match="must not be inside"):
            assert_isolated(tmp_path / marker / "q", repo_root=REPO, managed_install=install)


def test_layout_hard_links_assets_into_forge_data_and_writes_the_version_marker(monkeypatch, tmp_path):
    root = tmp_path / "root"
    (root / "assets").mkdir(parents=True)
    for role in spec.ASSETS:
        (root / "assets" / spec.ASSETS[role].filename).write_bytes(b"x")
    layout = build_layout(root)
    for asset in spec.ASSETS.values():
        linked = root / "forge-data" / "models" / asset.models_subdir / asset.filename
        assert linked.exists() and linked.stat().st_ino == (root / "assets" / asset.filename).stat().st_ino
    assert json.loads((root / "forge-data" / "config.json").read_text()) == {"VERSION_UID": "PY313"}
    assert layout["outputs"].is_dir() and layout["evidence"].is_dir()


class _Manager:
    def __init__(self, profile):
        self.profile, self.pid, self.owns_process, self.started, self.stopped = profile, None, True, 0, 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def get_stdout_tail_text(self):
        return ""


class _Lock:
    def acquire(self):
        return True

    def release(self):
        return None


def test_the_runtime_is_started_and_stopped_only_through_the_injected_process_manager():
    managers: list[_Manager] = []
    forge = OwnedForge({"endpoint": f"http://127.0.0.1:{_free_port()}"}, manager_factory=lambda p: managers.append(_Manager(p)) or managers[-1], lock_factory=_Lock)

    info = forge.start()
    result = forge.stop()

    assert info["owns_process"] and managers[0].started == 1 and managers[0].stopped == 1
    assert result["survivors"] == []
    assert "Popen" not in RUNTIME_SRC and "os.kill" not in RUNTIME_SRC and "taskkill" not in ALL_SRC.lower()
    assert "WebUIProcessManager" in RUNTIME_SRC  # the only lifecycle authority


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_an_occupied_port_is_never_adopted_or_stopped():
    with socket.socket() as occupant:
        occupant.bind(("127.0.0.1", 0))
        occupant.listen(1)
        port = occupant.getsockname()[1]
        made: list[_Manager] = []
        forge = OwnedForge({"endpoint": f"http://127.0.0.1:{port}"}, manager_factory=lambda p: made.append(_Manager(p)) or made[-1], lock_factory=_Lock)

        with pytest.raises(RuntimeError, match="never adopted"):
            forge.start()

        assert made == []  # no manager was even constructed


def test_the_harness_never_touches_production_settings_or_the_backend_configuration():
    assert "settings.json" not in ALL_SRC and "ConfigManager" not in ALL_SRC and "set_webui" not in ALL_SRC
    assert "src.image_backends" not in ALL_SRC and "JobService" not in ALL_SRC  # not another backend, queue or runner
    assert not (REPO / "src").joinpath("image_backends", "img115").exists()


# --- case execution with fakes: classification and no-replay ----------------------------------------------


def _png_b64(width: int, height: int) -> str:
    import numpy as np

    rng = np.random.default_rng(1)
    buffer = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, (height, width, 3), dtype=np.uint8)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class _Http:
    def __init__(self, behaviour="ok", *, wrong_size=False):
        self.behaviour, self.wrong_size, self.posts, self.options = behaviour, wrong_size, [], {}

    def get(self, url, **_k):
        if url.endswith("/progress") or "/progress" in url:
            return SimpleNamespace(status_code=200, json=lambda: {"progress": 0.5, "state": {"sampling_step": 2}})
        return SimpleNamespace(status_code=200, json=lambda: dict(self.options), text="{}")

    def post(self, url, json=None, **_k):  # noqa: A002
        self.posts.append(url)
        if url.endswith("/options"):
            self.options.update(json)
            return SimpleNamespace(status_code=200, text="{}", json=lambda: {})
        if self.behaviour == "timeout":
            raise TimeoutError("read timed out")
        if self.behaviour == "oom":
            return SimpleNamespace(status_code=500, text="CUDA out of memory", json=lambda: {})
        size = (100, 100) if self.wrong_size else (json["width"], json["height"])
        body = {"images": [_png_b64(*size)], "info": __import__("json").dumps({"seed": json["seed"], "all_seeds": [json["seed"]]})}
        return SimpleNamespace(status_code=200, text="", json=lambda: body)


class _FakeForge:
    base_url = "http://127.0.0.1:7885"
    profile = {"startup_timeout_seconds": 5, "endpoint": base_url}
    manager = SimpleNamespace(get_stdout_tail_text=lambda: "")

    def __init__(self):
        self.started = self.stopped = 0

    def start(self):
        self.started += 1
        return {"pid": 1, "owns_process": True}

    def process_tree_pids(self):
        return []

    def stop(self):
        self.stopped += 1
        return {"owned_pids": [], "survivors": []}


@pytest.fixture
def qualification_root(tmp_path, monkeypatch):
    root = tmp_path / "qual"
    layout = build_layout(root)
    manifest = {"qualification_source_sha": run_module._git_head(), "cases": spec.CASES,
                "fallback_reference_2": run_module._fallback_reference(layout["evidence"] / "fallback.png")}
    manifest["manifest_sha256"] = api.frozen_digest(manifest)
    (layout["evidence"] / "frozen-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(run_module, "A1111", tmp_path / "no-a1111")
    return root


def _run(case, root, http, events=lambda _s: []):
    return run_module.run_case(case, root, root.parent / "install", http=http, forge=_FakeForge(), events=events)


def test_a_successful_case_records_one_dispatch_the_model_stack_seed_and_a_valid_image(qualification_root):
    http = _Http()
    record = _run("A", qualification_root, http)

    assert record["state"] == "passed" and record["class"] == "passed"
    assert [u.rsplit("/", 1)[-1] for u in http.posts] == ["options", "txt2img"]  # one options write, ONE generation POST
    assert record["active_checkpoint"] == "flux-2-klein-4b-fp8.safetensors"
    assert sorted(record["active_modules"]) == ["flux2-vae.safetensors", "qwen_3_4b.safetensors"]
    assert record["seed_returned"] == 424242 and record["image"]["valid"] and record["image"]["size"] == [768, 1024]
    assert record["stop"]["survivors"] == []


def test_an_ambiguous_generation_submission_is_never_replayed(qualification_root):
    http = _Http("timeout")
    record = _run("A", qualification_root, http)

    assert record["state"] == "ambiguous" and record["class"] == "ambiguous"
    assert sum(u.endswith("/txt2img") for u in http.posts) == 1
    with pytest.raises(RuntimeError, match="no retry"):
        _run("A", qualification_root, _Http())  # a second attempt is refused before any runtime starts


def test_an_oom_is_a_resource_limit_not_a_technical_failure_and_stops_progression_after_a(qualification_root):
    record = _run("A", qualification_root, _Http("oom"))
    assert record["class"] == "resource_limit" and record["state"] == "failed"
    with pytest.raises(RuntimeError, match="Case A must pass"):
        _run("B", qualification_root, _Http())


def test_a_wrong_sized_image_is_a_technical_failure(qualification_root):
    record = _run("A", qualification_root, _Http(wrong_size=True))
    assert record["class"] == "technical_failure" and record["image"]["dimensions_ok"] is False


def test_a_relevant_gpu_event_is_a_hard_stop_that_blocks_every_later_case(qualification_root):
    calls = {"n": 0}

    def events(_since):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [{"provider": "nvlddmkm", "id": 14, "message": "TDR"}]

    record = _run("A", qualification_root, _Http(), events)

    assert record["class"] == "hard_stop"
    with pytest.raises(RuntimeError, match="hard-stopped"):
        _run("B", qualification_root, _Http())


def test_edit_cases_chain_to_the_recorded_outputs_and_d_survives_a_failed_b(qualification_root):
    http = _Http()
    assert _run("A", qualification_root, http)["state"] == "passed"
    assert _run("B", qualification_root, _Http("oom"))["state"] == "failed"
    c = _run("C", qualification_root, http)
    d = _run("D", qualification_root, http)

    assert c["state"] == "passed" and len(c["references"]) == 1
    a_sha = json.loads((qualification_root / "evidence" / "ledger.json").read_text())["cases"]["A"]["png_sha256"]
    assert c["references"][0]["sha256"] == a_sha
    assert d["state"] == "passed" and [r["sha256"] for r in d["references"]][0] == a_sha
    assert d["references"][1]["path"].endswith("fallback.png")  # frozen fallback: no replacement generation for B


def test_a_changed_reference_stops_the_edit_before_any_runtime_starts(qualification_root):
    assert _run("A", qualification_root, _Http())["state"] == "passed"
    out = qualification_root / "outputs" / "case-A.png"
    out.write_bytes(b"tampered")
    forge = _FakeForge()

    with pytest.raises(ValueError, match="changed since it was frozen"):
        run_module.run_case("C", qualification_root, qualification_root.parent / "install", http=_Http(), forge=forge, events=lambda _s: [])

    assert forge.started == 0


# --- the single infrastructure-repair exception ------------------------------------------------------------


def _rejected_ledger(tmp_path, **entry):
    ledger = api.Ledger(tmp_path / "ledger.json")
    ledger.data["cases"] = {"A": {"state": "passed", "png_path": "a.png", "png_sha256": "a" * 64},
                            "C": {"state": "failed", "dispatches": 1, "http_status": 500, "generation_seconds": 0.2, **entry}}
    return ledger


def test_an_api_rejected_dispatch_can_be_reopened_exactly_once_and_stays_counted(tmp_path):
    ledger = _rejected_ledger(tmp_path)
    ledger.reopen_rejected("C", "payload shape")
    ledger.begin("C")
    ledger.mark_dispatched("C")
    assert ledger.data["cases"]["C"]["dispatches_total"] == 1 and ledger.data["cases"]["C"]["dispatches"] == 1  # 2 POSTs in total
    assert ledger.data["repairs"][0]["case"] == "C"
    ledger.finish("C", "failed", http_status=500, generation_seconds=0.1)
    with pytest.raises(RuntimeError, match="already used"):
        ledger.reopen_rejected("C", "again")


@pytest.mark.parametrize(
    "entry",
    [{"state": "passed"}, {"http_status": 200}, {"generation_seconds": 19.0}, {"png_path": "c.png"}, {"state": "ambiguous"}],
)
def test_only_an_api_layer_rejection_without_generation_work_can_be_reopened(tmp_path, entry):
    ledger = _rejected_ledger(tmp_path, **entry)
    with pytest.raises(RuntimeError, match="only an API-layer rejection"):
        ledger.reopen_rejected("C", "x")
