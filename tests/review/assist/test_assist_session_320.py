"""Smart Review session, source identity, adapters and worker contract with fakes: no model, network or Tk."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.conditioning.reference_map import auxiliary
from src.conditioning.reference_map.contracts import (
    AuxiliaryFileIdentity,
    ProviderUnavailable,
)
from src.review.assist import providers, worker
from src.review.assist.captions import sanitize_text
from src.review.assist.contracts import (
    CAPABILITY_CAPTION,
    CAPABILITY_SEGMENT,
    CODE_BUSY,
    CODE_CANCELLED,
    CODE_DISABLED,
    CODE_OUTPUT,
    CODE_PROMPT,
    CODE_SOURCE_CHANGED,
    CODE_STALE,
    CODE_TIMEOUT,
    AssistError,
    AssistUnavailable,
    BoxPrompt,
    CaptionOutput,
    ModelIdentity,
    PointPrompt,
    RawObject,
    SegmentOutput,
)
from src.review.assist.identity import load_source
from src.review.assist.providers import (
    ChildCaptionAdapter,
    ChildSegmentAdapter,
    ModelAvailability,
    availability_from,
)
from src.review.assist.session import AssistEnablement, AssistSession
from src.utils.managed_process import ProcessOutcome

REPO = Path(__file__).resolve().parents[3]
MODEL = ModelIdentity(
    CAPABILITY_SEGMENT, "sam-2-1-small", providers.ADAPTER_LABEL, runtime={"torch": "2.x"}
)


def write_png(path: Path, color="blue", size=(96, 64)) -> Path:
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def blob_logits(shape=(16, 24)) -> np.ndarray:
    logits = np.full(shape, -4.0, dtype=np.float32)
    logits[4:10, 6:16] = 4.0
    return logits


class FakeSegmenter:
    def __init__(self, logits=None):
        self.logits = blob_logits() if logits is None else logits
        self.calls = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def segment(self, source, points, boxes, cancel):
        self.calls.append((source.identity, tuple(points), tuple(boxes)))
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5)
        return SegmentOutput(self.logits, 0.91, MODEL)


class FakeCaptioner:
    def __init__(self, text="A blue rectangle."):
        self.text = text
        self.calls = 0

    def caption(self, source, cancel):
        self.calls += 1
        return CaptionOutput(self.text, (RawObject("rectangle", (1, 1, 60, 40)),), MODEL)


class FakeProbe:
    def __init__(self):
        self.checked = []

    def check(self, capability, cancel):
        self.checked.append(capability)
        return availability_from(capability, ())


@pytest.fixture
def source(tmp_path):
    return write_png(tmp_path / "a.png")


def make_session(
    path, *, enabled=(CAPABILITY_SEGMENT, CAPABILITY_CAPTION), segmenter=None, captioner=None
):
    enablement = AssistEnablement()
    for capability in enabled:
        enablement.set(capability, True)
    session = AssistSession(
        path,
        segmenter=segmenter or FakeSegmenter(),
        captioner=captioner or FakeCaptioner(),
        probe=FakeProbe(),
        enablement=enablement,
    )
    session.bind(load_source(path), path)
    return session


# -- source identity --------------------------------------------------------------------------------------------------
def test_identity_is_bound_to_bytes_not_names(tmp_path):
    first = write_png(tmp_path / "x.png", "red")
    identity_a = load_source(first).identity
    write_png(first, "green")  # same name, different bytes
    identity_b = load_source(first).identity
    assert identity_a != identity_b and identity_a.file_sha256 != identity_b.file_sha256
    assert load_source(first).identity == identity_b


def test_exif_rotated_rectangular_image_uses_stored_pixels_and_records_orientation(tmp_path):
    path = tmp_path / "rot.jpg"
    image = Image.new("RGB", (128, 64), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW when displayed
    image.save(path, format="JPEG", exif=exif)
    loaded = load_source(path)
    assert loaded.identity.size == (128, 64)  # same frame as the mask editor
    assert loaded.identity.exif_orientation == 6
    assert loaded.rgb.shape == (64, 128, 3)
    session = make_session(path, segmenter=FakeSegmenter(blob_logits((32, 64))))
    ticket = session.begin_segment([PointPrompt(30, 20, True)], [])
    proposal = session.run_segment(ticket, [PointPrompt(30, 20, True)], [])
    assert Image.open(io.BytesIO(proposal.mask_png)).size == (128, 64)


@pytest.mark.parametrize("name", ["missing.png", "x.gif", "x.txt"])
def test_unsupported_or_missing_sources_are_refused_path_free(tmp_path, name):
    with pytest.raises(AssistError) as caught:
        load_source(tmp_path / name)
    assert str(tmp_path) not in caught.value.message


# -- session ----------------------------------------------------------------------------------------------------------
def test_everything_starts_disabled_and_nothing_runs_until_requested(source):
    session = make_session(source, enabled=())
    segmenter = session._segmenter
    with pytest.raises(AssistError) as caught:
        session.begin_segment([PointPrompt(5, 5, True)], [])
    assert caught.value.code == CODE_DISABLED
    with pytest.raises(AssistError) as caught:
        session.begin_caption()
    assert caught.value.code == CODE_DISABLED
    assert session.availability(CAPABILITY_SEGMENT).reasons == ("disabled",)
    assert (
        session._probe.checked == [] and segmenter.calls == []
    )  # a disabled model is never probed or touched
    assert not session.busy and session.segment is None and session.caption is None


def test_click_to_overlay_to_accept_returns_validated_bytes_and_clears_the_proposal(source):
    session = make_session(source)
    points = [PointPrompt(30, 20, True)]
    ticket = session.begin_segment(points, [])
    assert session.busy
    proposal = session.run_segment(ticket, points, [])
    assert not session.busy
    assert session.adopt_segment(ticket, proposal) and session.segment is proposal
    data = session.accept_mask()
    assert data == proposal.mask_png and session.segment is None
    mask = Image.open(io.BytesIO(data))
    assert (
        mask.mode == "L" and mask.size == (96, 64) and set(np.unique(np.asarray(mask))) == {0, 255}
    )
    with pytest.raises(AssistError):
        session.accept_mask()  # nothing left to accept


def test_invalid_prompts_never_reach_the_model(source):
    session = make_session(source)
    for points, boxes in [
        ([], []),
        ([PointPrompt(500, 5, True)], []),
        ([PointPrompt(5, 5, False)], []),
    ]:
        with pytest.raises(AssistError) as caught:
            session.begin_segment(points, boxes)
        assert caught.value.code == CODE_PROMPT
    assert session._segmenter.calls == [] and not session.busy
    session.begin_segment([], [BoxPrompt(2, 2, 40, 40)])  # a lone box is a valid prompt


def test_one_analysis_at_a_time_and_release_frees_the_slot(source):
    session = make_session(source)
    ticket = session.begin_segment([PointPrompt(5, 5, True)], [])
    with pytest.raises(AssistError) as caught:
        session.begin_caption()
    assert caught.value.code == CODE_BUSY
    session.release()
    assert session.begin_caption().kind == "caption"
    del ticket


def test_a_reply_for_another_image_is_dropped_whatever_the_order(tmp_path):
    first, second = write_png(tmp_path / "1.png", "red"), write_png(tmp_path / "2.png", "green")
    segmenter = FakeSegmenter()
    session = make_session(first, segmenter=segmenter)
    points = [PointPrompt(5, 5, True)]
    old = session.begin_segment(points, [])
    session.bind(
        load_source(second), second
    )  # rapid selection switch while the first request is queued
    with pytest.raises(AssistError) as caught:
        session.run_segment(old, points, [])
    assert caught.value.code == CODE_STALE and segmenter.calls == [] and not session.busy
    new = session.begin_segment(points, [])
    proposal = session.run_segment(new, points, [])
    assert not session.adopt_segment(
        old, proposal
    )  # out-of-order: the old ticket can never adopt the new reply
    assert session.adopt_segment(new, proposal)


def test_reply_finishing_after_a_switch_is_not_adoptable(tmp_path):
    first, second = write_png(tmp_path / "1.png", "red"), write_png(tmp_path / "2.png", "green")
    segmenter = FakeSegmenter()
    segmenter.gate = threading.Event()
    session = make_session(first, segmenter=segmenter)
    points = [PointPrompt(5, 5, True)]
    ticket = session.begin_segment(points, [])
    result: list = []
    worker_thread = threading.Thread(
        target=lambda: result.append(_run_quietly(session, ticket, points))
    )
    worker_thread.start()
    assert segmenter.entered.wait(5)
    session.bind(load_source(second), second)
    segmenter.gate.set()
    worker_thread.join(5)
    assert (
        isinstance(result[0], AssistError) and result[0].code == CODE_CANCELLED
    )  # bind cancels the old request
    assert session.segment is None and not session.busy


def _run_quietly(session, ticket, points):
    try:
        return session.run_segment(ticket, points, [])
    except AssistError as exc:
        return exc


def test_cancel_discards_suggestions_and_frees_the_slot(source):
    segmenter = FakeSegmenter()
    segmenter.gate = threading.Event()
    session = make_session(source, segmenter=segmenter)
    points = [PointPrompt(5, 5, True)]
    ticket = session.begin_segment(points, [])
    result: list = []
    thread = threading.Thread(target=lambda: result.append(_run_quietly(session, ticket, points)))
    thread.start()
    assert segmenter.entered.wait(5)
    session.cancel()
    segmenter.gate.set()
    thread.join(5)
    assert result[0].code == CODE_CANCELLED and not session.busy and session.segment is None
    assert session.begin_segment(points, []).kind == "segment"  # usable again after cancel


def test_source_replaced_after_preview_is_refused_at_accept(source):
    session = make_session(source)
    points = [PointPrompt(30, 20, True)]
    ticket = session.begin_segment(points, [])
    session.adopt_segment(ticket, session.run_segment(ticket, points, []))
    write_png(source, "green")  # the file changes under the preview
    with pytest.raises(AssistError) as caught:
        session.accept_mask()
    assert caught.value.code == CODE_SOURCE_CHANGED
    assert str(source) not in caught.value.message


def test_source_replaced_while_running_drops_the_reply(source):
    class Replacing(FakeSegmenter):
        def segment(self, src, points, boxes, cancel):
            output = super().segment(src, points, boxes, cancel)
            write_png(source, "green")
            return output

    session = make_session(source, segmenter=Replacing())
    points = [PointPrompt(30, 20, True)]
    ticket = session.begin_segment(points, [])
    with pytest.raises(AssistError) as caught:
        session.run_segment(ticket, points, [])
    assert caught.value.code == CODE_SOURCE_CHANGED and session.segment is None and not session.busy


def test_model_output_is_validated_before_it_is_ever_shown(source):
    for bad in (
        np.full((16, 24), np.nan, np.float32),
        np.full((16, 24), -2.0, np.float32),
        np.full((16, 24), 2.0, np.float32),
    ):
        session = make_session(source, segmenter=FakeSegmenter(bad))
        points = [PointPrompt(30, 20, True)]
        ticket = session.begin_segment(points, [])
        with pytest.raises(AssistError) as caught:
            session.run_segment(ticket, points, [])
        assert caught.value.code == CODE_OUTPUT and session.segment is None and not session.busy


def test_caption_is_suggestion_only_and_sanitized(source):
    session = make_session(source, captioner=FakeCaptioner("A  cat\x1b[31m‮\n sits."))
    ticket = session.begin_caption()
    proposal = session.run_caption(ticket)
    assert session.caption is None  # not adopted until the UI adopts it
    assert session.adopt_caption(ticket, proposal)
    assert "\x1b" not in proposal.text and proposal.text.startswith("A cat")
    assert "‮" not in proposal.text and "\n" not in proposal.text
    session.reject_caption()
    assert session.caption is None


def test_closed_session_refuses_everything(source):
    session = make_session(source)
    session.close()
    with pytest.raises(AssistError):
        session.begin_caption()
    assert session.identity is None and session.closed


# -- no side effects: network, model imports, prompts, files ----------------------------------------------------------
def test_session_flow_imports_no_model_library_and_opens_no_socket(tmp_path):
    path = write_png(tmp_path / "a.png")
    script = f"""
import socket, sys
def refuse(*a, **k): raise AssertionError("network used")
socket.socket.connect = refuse
socket.create_connection = refuse
import numpy as np
from src.review.assist.contracts import *
from src.review.assist.identity import load_source
from src.review.assist.captions import sanitize_text
from src.review.assist.session import AssistEnablement, AssistSession
from src.review.assist import providers
from src.review.assist.providers import availability_from
class Seg:
    def segment(self, s, p, b, c):
        l = np.full((16, 24), -4.0, np.float32); l[4:10, 6:16] = 4.0
        return SegmentOutput(l, 0.9, ModelIdentity("sam2", "sam-2-1-small", "x"))
class Cap:
    def caption(self, s, c): return CaptionOutput("A box.", (), ModelIdentity("florence2", "f", "x"))
class Probe:
    def check(self, c, cancel): return availability_from(c, ())
en = AssistEnablement(); en.set("sam2", True); en.set("florence2", True)
session = AssistSession({str(path)!r}, segmenter=Seg(), captioner=Cap(), probe=Probe(), enablement=en)
session.bind(load_source({str(path)!r}))
t = session.begin_segment([PointPrompt(5, 5, True)], [])
p = session.run_segment(t, [PointPrompt(5, 5, True)], [])
session.adopt_segment(t, p); session.accept_mask()
t = session.begin_caption(); session.adopt_caption(t, session.run_caption(t))
providers.runtime_reasons("sam2")
bad = [m for m in ("torch", "transformers", "torchvision", "safetensors", "requests", "urllib3", "httpx")
       if m in sys.modules]
assert not bad, bad
print("clean")
"""
    done = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(REPO)!r})\n{script}"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(tmp_path),
    )
    assert done.returncode == 0 and "clean" in done.stdout, done.stderr[-2000:]


def _code_only(text: str) -> str:
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return re.sub(r'""".*?"""', "", code, flags=re.S)


def test_assist_package_has_no_runner_queue_or_backend_dependency():
    banned = re.compile(
        r"PipelineRunner|run_njr|JobService|submit_njrs|job_service|\bforge\b|comfy|requests|urllib|httpx|socket",
        re.I,
    )
    for file in (REPO / "src" / "review" / "assist").glob("*.py"):
        text = file.read_text(encoding="utf-8")
        code = _code_only(text)
        assert not banned.search(code), f"{file.name}: {banned.search(code).group(0)}"


def test_worker_never_enables_remote_code_pickles_or_online_loading():
    text = _code_only(
        (REPO / "src" / "review" / "assist" / "worker.py").read_text(encoding="utf-8")
    )
    assert (
        "trust_remote_code=True" not in text and "torch.load" not in text and "pickle" not in text
    )
    assert "weights_only=False" not in text
    for call in re.findall(r"from_pretrained\((?:[^()]|\([^()]*\))*\)", text):
        assert "local_files_only=True" in call and "trust_remote_code=False" in call, call
    assert set(worker.BACKENDS) == {"sam2", "florence2"}


# -- adapters (fake process runner, fake registry) --------------------------------------------------------------------
def verified(resource_id: str) -> auxiliary.VerifiedResource:
    return auxiliary.VerifiedResource(
        resource_id,
        (
            AuxiliaryFileIdentity(
                "weights", f"{resource_id}/model.safetensors", "ab" * 32, 10, True
            ),
        ),
    )


@pytest.fixture
def child(monkeypatch, tmp_path):
    state = {"commands": [], "cleaned": []}
    monkeypatch.setattr(providers, "runtime_reasons", lambda capability: ())
    monkeypatch.setattr(
        auxiliary,
        "verify_resource",
        lambda registry, modality, cancelled=None: verified(
            auxiliary.RESOURCE_BY_MODALITY[modality]
        ),
    )
    monkeypatch.setattr(
        auxiliary,
        "stage_resource",
        lambda resource, root, dest, cancelled=None: dest.mkdir(parents=True)
        or {"weights": dest / "model.safetensors"},
    )
    registry = type("R", (), {"webui_root": tmp_path})()
    return state, registry


def fake_runner(state, *, result=None, logits=None, outcome=None):
    def run(command, *, timeout_seconds, max_stdout_bytes, cancel, env):
        job = Path(command[-1])
        state["commands"].append((list(command), timeout_seconds, dict(env), job))
        if result is not None:
            (job / "result.json").write_text(json.dumps(result), encoding="utf-8")
        if logits is not None:
            (job / "logits.f32").write_bytes(logits)
        return outcome or ProcessOutcome(0)

    return run


def test_segment_adapter_contract_runs_one_contained_cpu_child_and_cleans_up(child, source):
    state, registry = child
    logits = blob_logits()
    runner = fake_runner(
        state,
        result={
            "ok": True,
            "shape": [16, 24],
            "score": 0.8,
            "runtime": {"torch": "2.9", "transformers": "5.17.0"},
        },
        logits=logits.astype("<f4").tobytes(),
    )
    adapter = ChildSegmentAdapter(lambda: registry, runner=runner)
    loaded = load_source(source)
    output = adapter.segment(
        loaded, [PointPrompt(5, 5, True), PointPrompt(9, 9, False)], [], lambda: False
    )
    command, timeout, env, job = state["commands"][0]
    assert (
        command[1] == "-I"
        and Path(command[2]).name == "worker.py"
        and Path(command[2]).parent.name == "assist"
    )
    assert timeout == providers.DEFAULT_TIMEOUT_SECONDS[CAPABILITY_SEGMENT]
    assert env.get("CUDA_VISIBLE_DEVICES") == "-1" and env.get("HF_HUB_OFFLINE") == "1"
    assert (
        not job.exists()
    )  # the private job directory (hash-verified staged copy included) is gone
    assert np.array_equal(output.logits, logits) and output.score == pytest.approx(0.8)
    assert (
        output.model.runtime["transformers"] == "5.17.0"
        and output.model.resource_id == "sam-2-1-small"
    )


def test_request_carries_prompts_labels_and_staged_paths_only(child, source):
    state, registry = child
    captured = {}

    def runner(command, **kwargs):
        job = Path(command[-1])
        captured.update(json.loads((job / "request.json").read_text(encoding="utf-8")))
        (job / "result.json").write_text(
            json.dumps({"ok": True, "shape": [4, 4]}), encoding="utf-8"
        )
        (job / "logits.f32").write_bytes(np.zeros((4, 4), "<f4").tobytes())
        return ProcessOutcome(0)

    adapter = ChildSegmentAdapter(lambda: registry, runner=runner)
    adapter.segment(
        load_source(source),
        [PointPrompt(5, 6, True), PointPrompt(9, 8, False)],
        [BoxPrompt(1, 2, 30, 40)],
        lambda: False,
    )
    assert captured["points"] == [[5, 6], [9, 8]] and captured["labels"] == [1, 0]
    assert captured["box"] == [1, 2, 30, 40] and captured["kind"] == "sam2"
    assert (captured["width"], captured["height"]) == (96, 64)


@pytest.mark.parametrize(
    ("logit_bytes", "result"),
    [
        (np.zeros((4, 4), "<f4").tobytes()[:-4], {"ok": True, "shape": [4, 4]}),  # truncated
        (np.zeros((4, 4), "<f4").tobytes(), {"ok": True, "shape": [4, 99999]}),  # hostile shape
        (np.zeros((4, 4), "<f4").tobytes(), {"ok": True, "shape": "4x4"}),
        (np.zeros((4, 4), "<f4").tobytes(), {"ok": True}),
    ],
)
def test_malformed_child_output_is_refused(child, source, logit_bytes, result):
    state, registry = child
    adapter = ChildSegmentAdapter(
        lambda: registry, runner=fake_runner(state, result=result, logits=logit_bytes)
    )
    with pytest.raises(AssistError) as caught:
        adapter.segment(load_source(source), [PointPrompt(5, 5, True)], [], lambda: False)
    assert caught.value.code == CODE_OUTPUT
    assert not state["commands"][0][3].exists()


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (ProcessOutcome(None, timed_out=True), CODE_TIMEOUT),
        (ProcessOutcome(None, cancelled=True), CODE_CANCELLED),
    ],
)
def test_timeout_and_cancel_surface_stable_codes_and_leave_no_job_directory(
    child, source, outcome, code
):
    state, registry = child
    adapter = ChildCaptionAdapter(lambda: registry, runner=fake_runner(state, outcome=outcome))
    with pytest.raises(AssistError) as caught:
        adapter.caption(load_source(source), lambda: False)
    assert caught.value.code == code
    assert not state["commands"][0][3].exists()


def test_child_failure_message_is_content_free(child, source):
    state, registry = child
    secret = str(source)
    runner = fake_runner(
        state,
        result={"ok": False, "code": "inference_failed", "reasons": ["RuntimeError"]},
        outcome=ProcessOutcome(1, stderr=secret.encode()),
    )
    adapter = ChildCaptionAdapter(lambda: registry, runner=runner)
    with pytest.raises(AssistError) as caught:
        adapter.caption(load_source(source), lambda: False)
    assert secret not in caught.value.message and secret not in repr(caught.value.reasons)


def test_caption_adapter_bounds_the_result(child, source):
    state, registry = child
    objects = [{"label": f"o{i}", "box": [1, 1, 9, 9]} for i in range(100)] + [
        {"label": 5, "box": [1]},
        "x",
    ]
    result = {"ok": True, "caption": "A box.", "objects": objects, "runtime": {"torch": "2"}}
    output = ChildCaptionAdapter(
        lambda: registry, runner=fake_runner(state, result=result)
    ).caption(load_source(source), lambda: False)
    assert len(output.objects) <= 16 and output.text == "A box."
    huge = {"ok": True, "caption": "x" * 40000, "objects": []}
    with pytest.raises(AssistError) as caught:
        ChildCaptionAdapter(lambda: registry, runner=fake_runner(state, result=huge)).caption(
            load_source(source), lambda: False
        )
    assert caught.value.code == CODE_OUTPUT


def test_unavailable_runtime_or_files_never_start_a_child(monkeypatch, source, tmp_path):
    started = []
    registry = type("R", (), {"webui_root": tmp_path})()
    adapter = ChildCaptionAdapter(lambda: registry, runner=lambda *a, **k: started.append(1))
    monkeypatch.setattr(providers, "runtime_reasons", lambda capability: ("runtime_missing:torch",))
    with pytest.raises(AssistUnavailable) as caught:
        adapter.caption(load_source(source), lambda: False)
    assert caught.value.reasons == ("runtime_missing:torch",)
    monkeypatch.setattr(providers, "runtime_reasons", lambda capability: ())

    def missing(registry, modality, cancelled=None):
        raise ProviderUnavailable("not ready", reasons=("resource_missing:weights",))

    monkeypatch.setattr(auxiliary, "verify_resource", missing)
    with pytest.raises(AssistUnavailable) as caught:
        adapter.caption(load_source(source), lambda: False)
    assert caught.value.reasons == ("resource_missing:weights",)
    assert started == []


# -- availability -----------------------------------------------------------------------------------------------------
def test_availability_reports_precise_reasons_and_keeps_manual_editing_message(
    monkeypatch, tmp_path
):
    registry = type("R", (), {"webui_root": tmp_path})()
    probe = ModelAvailability(lambda: registry)
    monkeypatch.setattr(providers, "runtime_reasons", lambda capability: ())

    def mismatch(registry, modality, cancelled=None):
        raise ProviderUnavailable("bad", reasons=("hash_mismatch:weights",))

    monkeypatch.setattr(auxiliary, "verify_resource", mismatch)
    result = probe.check(CAPABILITY_SEGMENT, lambda: False)
    assert not result.available and result.reasons == ("hash_mismatch:weights",)
    assert "Manual mask editing is unaffected" in result.message

    def boom(registry, modality, cancelled=None):
        raise OSError(str(tmp_path / "secret"))

    monkeypatch.setattr(auxiliary, "verify_resource", boom)
    result = probe.check(CAPABILITY_CAPTION, lambda: False)
    assert result.reasons == ("probe_failed",) and str(tmp_path) not in result.message

    monkeypatch.setattr(auxiliary, "verify_resource", lambda *a, **k: verified("x"))
    assert probe.check(CAPABILITY_CAPTION, lambda: False).available


@pytest.mark.parametrize(
    ("version", "reason"), [("5.16.0", "transformers_too_old"), ("6.1.0", "transformers_too_new")]
)
def test_incompatible_transformers_is_reported_without_importing_it(monkeypatch, version, reason):
    monkeypatch.setattr(providers.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(providers.importlib.metadata, "version", lambda name: version)
    assert reason in providers.runtime_reasons(CAPABILITY_SEGMENT)
    monkeypatch.setattr(
        providers.importlib.util, "find_spec", lambda name: None if name == "torch" else object()
    )
    assert "runtime_missing:torch" in providers.runtime_reasons(CAPABILITY_CAPTION)


# -- worker protocol --------------------------------------------------------------------------------------------------
def test_worker_reports_a_missing_runtime_as_provider_unavailable(tmp_path, monkeypatch):
    rgb = np.zeros((8, 8, 3), np.uint8)
    (tmp_path / "source.rgb").write_bytes(rgb.tobytes())
    (tmp_path / "request.json").write_text(
        json.dumps({"kind": "sam2", "width": 8, "height": 8, "staged_dir": str(tmp_path)})
    )
    monkeypatch.setattr(
        worker, "_missing", lambda *modules: [f"runtime_missing:{m}" for m in modules]
    )
    assert worker.main(["worker.py", str(tmp_path)]) == 3
    document = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert document["ok"] is False and document["code"] == "provider_unavailable"
    assert "runtime_missing:torch" in document["reasons"]
    assert worker.main(["worker.py"]) == 64


# -- review-driven hardening ------------------------------------------------------------------------------------------
def test_the_single_analysis_slot_is_shared_by_every_session_of_one_enablement(tmp_path):
    first, second = write_png(tmp_path / "1.png", "red"), write_png(tmp_path / "2.png", "green")
    enablement = AssistEnablement()
    enablement.set(CAPABILITY_SEGMENT, True)

    def make(path):
        session = AssistSession(
            path,
            segmenter=FakeSegmenter(),
            captioner=FakeCaptioner(),
            probe=FakeProbe(),
            enablement=enablement,
        )
        session.bind(load_source(path), path)
        return session

    one, two = make(first), make(second)
    points = [PointPrompt(5, 5, True)]
    ticket = one.begin_segment(points, [])
    with pytest.raises(AssistError) as caught:
        two.begin_segment(
            points, []
        )  # a second window cannot start another child while one is running
    assert caught.value.code == CODE_BUSY
    one.run_segment(ticket, points, [])  # finishing frees the shared slot
    two.begin_segment(points, [])
    two.release()
    one.begin_segment(points, [])  # and a released reservation frees it again


def test_probe_is_not_cancelled_by_binding_or_cancelling_an_analysis(source):
    seen = []

    class Probe(FakeProbe):
        def check(self, capability, cancel):
            seen.append(cancel())
            return super().check(capability, cancel)

    enablement = AssistEnablement()
    enablement.set(CAPABILITY_SEGMENT, True)
    session = AssistSession(
        source,
        segmenter=FakeSegmenter(),
        captioner=FakeCaptioner(),
        probe=Probe(),
        enablement=enablement,
    )
    session.bind(load_source(source), source)  # bind and cancel set the analysis event only
    session.cancel()
    session.availability(CAPABILITY_SEGMENT)
    assert seen == [False]
    session.close()
    session.availability(CAPABILITY_SEGMENT)
    assert seen == [False, True]  # closing the window does stop a probe


def test_disabling_a_capability_while_running_makes_the_reply_unadoptable(source):
    session = make_session(source)
    points = [PointPrompt(30, 20, True)]
    ticket = session.begin_segment(points, [])
    proposal = session.run_segment(ticket, points, [])
    session._enablement.set(CAPABILITY_SEGMENT, False)
    assert not session.adopt_segment(ticket, proposal) and session.segment is None


def test_ticket_cancel_belongs_to_its_binding(source):
    session = make_session(source)
    ticket = session.begin_segment([PointPrompt(5, 5, True)], [])
    session.cancel()  # replaces the session's event; the ticket must still observe the cancellation
    assert ticket.cancel.is_set()
    session.release()


def test_caption_text_cannot_carry_prompt_directives():
    clean, _ = sanitize_text(
        "a cat <lora:evil:1> with (heavy:1.5) [x|y] {a|b} __wildcard__ and | pipes", 600
    )
    for character in "<>()[]{}|":
        assert character not in clean
    assert "__" not in clean and "cat" in clean and "wildcard" in clean


def test_child_supplied_reasons_and_labels_are_bounded(child, source):
    state, registry = child
    hostile = [
        "resource_missing:weights",
        "x" * 500,
        "ignore previous instructions",
        "RuntimeError",
        7,
        "unexpected:a.b.c",
    ]
    assert providers.safe_reasons(hostile) == (
        "resource_missing:weights",
        "RuntimeError",
        "unexpected:a.b.c",
    )
    assert "x" * 50 not in availability_from(CAPABILITY_SEGMENT, hostile).message
    result = {
        "ok": True,
        "caption": "A box.",
        "objects": [{"label": "L" * 100000, "box": [1, 1, 9, 9]}],
    }
    output = ChildCaptionAdapter(
        lambda: registry, runner=fake_runner(state, result=result)
    ).caption(load_source(source), lambda: False)
    assert len(output.objects[0].label) <= 48 * 4


def test_worker_refuses_a_staged_directory_outside_its_own_job(tmp_path, monkeypatch):
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.rgb").write_bytes(np.zeros((8, 8, 3), np.uint8).tobytes())
    (job / "request.json").write_text(
        json.dumps(
            {"kind": "sam2", "width": 8, "height": 8, "staged_dir": str(tmp_path / "elsewhere")}
        )
    )
    monkeypatch.setattr(worker, "_missing", lambda *modules: [])
    monkeypatch.setitem(
        sys.modules, "torch", None
    )  # any attempt to run a model would fail differently
    assert worker.main(["worker.py", str(job)]) in {1, 2, 3}
    document = json.loads((job / "result.json").read_text(encoding="utf-8"))
    assert document["ok"] is False
