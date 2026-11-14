"""AI-202b (owner decision D20): the in-app model selector, one activation authority and per-identity Preview enablement.

Hermetic: temporary roots, fake runtime builds and fake model files, a fake child through the real ``run_bounded`` for the
in-flight case. No llama.cpp binary, archive or model is touched or run, and the selector never starts a process or thread.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from src.ai_assist import activation as activation_module
from src.ai_assist import selector as selector_module
from src.ai_assist.activation import ActivationRefused, activate
from src.ai_assist.attestation import record_attestation
from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.manifests import (
    ModelEntry,
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    import_model,
    import_runtime,
    load_model_registry,
    load_runtime_manifest,
    read_pointer,
    record_active,
)
from src.ai_assist.paths import active_pointer_path, attestation_path, preview_enablement_path
from src.ai_assist.preview import (
    enable_preview,
    preview_enabled_for,
    read_preview_identities,
    revoke_preview,
)
from src.ai_assist.selector import (
    SelectionRefused,
    list_model_choices,
    select_model,
)
from src.ai_assist.service import ServicePolicy
from src.ai_assist.status import (
    MODEL_REGISTRY_PATH,
    RUNTIME_MANIFEST_PATH,
    STATE_PREVIEW,
    STATE_PREVIEW_AVAILABLE,
    read_status,
)
from src.controller.app_controller_services.ai_assist_integration import (
    AiAssistIntegration,
    egress_refusal_text,
)

from .conftest import FAKE_CHILD, Install, build_archive, make_provenance, request_for, sha
from .test_service_runtime import make_service

REPO = Path(__file__).resolve().parents[2]
PREVIEW_POLICY = ServicePolicy(allow_preview=True, strict_offline=True, watch_interval_seconds=0.05)

FILES_A = {"llama-completion.exe": b"fake binary A", "ggml.dll": b"fake ggml A"}
FILES_B = {"llama-completion.exe": b"fake binary B", "ggml.dll": b"fake ggml B"}
QWEN_BYTES = b"GGUF-qwen" + b"\x00" * 64
LFM_BYTES = b"GGUF-lfm3" + b"\x00" * 80
STRAY_BYTES = b"GGUF-stray" + b"\x00" * 96


def _build(build_id: str, files: dict[str, bytes], archive: bytes) -> RuntimeBuild:
    return RuntimeBuild(
        build_id=build_id,
        upstream_repository="https://example.invalid/llama.cpp",
        upstream_tag=build_id.split("-")[0],
        asset_name=f"{build_id}.zip",
        asset_sha256=sha(archive),
        asset_bytes=len(archive),
        license_spdx="MIT",
        executable="llama-completion.exe",
        files={name: sha(data) for name, data in files.items()},
    )


def _entry(model_id: str, name: str, arch: str, data: bytes, builds: tuple[str, ...]) -> ModelEntry:
    return ModelEntry(
        model_id=model_id,
        display_name=name,
        license_spdx="Apache-2.0",
        architecture=arch,
        quantization="Q4_K_M",
        filename=f"{model_id}.gguf",
        bytes=len(data),
        sha256=sha(data),
        provenance=make_provenance(),
        compatible_builds=builds,
    )


@dataclass
class Pair:
    """Two runtime builds and four registered models; three of them are imported."""

    root: Path
    manifest: RuntimeManifest
    registry: ModelRegistry
    build_a: RuntimeBuild
    build_b: RuntimeBuild
    qwen: ModelEntry
    lfm: ModelEntry
    not_imported: ModelEntry
    stray: ModelEntry
    child: Path

    def as_install(self, build: RuntimeBuild, entry: ModelEntry) -> Install:
        return Install(
            self.root,
            self.manifest,
            self.registry,
            build,
            entry,
            self.child,
        )

    def attest(self, *builds: RuntimeBuild) -> Path:
        return record_attestation(
            self.root, "outbound block rule", [(b.build_id, b.executable) for b in builds]
        )


@pytest.fixture
def pair(tmp_path: Path) -> Pair:
    archive_a = build_archive(FILES_A)
    archive_b = build_archive(FILES_B)
    build_a = _build("b0000-cpu", FILES_A, archive_a)
    build_b = _build("b0001-cpu", FILES_B, archive_b)
    qwen = _entry("fake-qwen", "Fake Qwen 4B Q4", "qwen3_5", QWEN_BYTES, ("b0000-cpu", "b0001-cpu"))
    lfm = _entry("fake-lfm", "Fake LFM3 1.7B Q4", "lfm3", LFM_BYTES, ("b0001-cpu",))
    not_imported = _entry(
        "fake-absent", "Fake Absent", "qwen3_5", b"GGUF-absent" + b"\x00" * 40, ("b0000-cpu",)
    )
    stray = _entry("fake-stray", "Fake Stray", "qwen3_5", STRAY_BYTES, ("b9999-cpu",))
    root = tmp_path / "ai"
    for build, archive in ((build_a, archive_a), (build_b, archive_b)):
        path = tmp_path / f"{build.build_id}.zip"
        path.write_bytes(archive)
        import_runtime(path, build, root)
    for entry, data in ((qwen, QWEN_BYTES), (lfm, LFM_BYTES), (stray, STRAY_BYTES)):
        path = tmp_path / f"{entry.model_id}.src"
        path.write_bytes(data)
        import_model(path, entry, root)
    record_active(root, build_a, qwen)
    child = tmp_path / "fake_child.py"
    child.write_text(FAKE_CHILD, encoding="utf-8")
    return Pair(
        root=root,
        manifest=RuntimeManifest((build_a, build_b)),
        registry=ModelRegistry((qwen, lfm, not_imported, stray)),
        build_a=build_a,
        build_b=build_b,
        qwen=qwen,
        lfm=lfm,
        not_imported=not_imported,
        stray=stray,
        child=child,
    )


def owner(pair: Pair) -> AiAssistIntegration:
    return AiAssistIntegration(
        lambda: None,
        lambda callback: None,
        root=pair.root,
        runtime_manifest=pair.manifest,
        registry=pair.registry,
    )


# -- listing: only models that are imported and verified -----------------------------------------------------------------


def test_the_list_holds_only_imported_verified_models_by_display_name(pair: Pair) -> None:
    choices = list_model_choices(pair.root, pair.manifest, pair.registry)
    # not_imported has no file; stray is imported but its only compatible build is not pinned or imported.
    assert [c.display_name for c in choices] == ["Fake Qwen 4B Q4", "Fake LFM3 1.7B Q4"]
    assert [c.active for c in choices] == [True, False]
    assert all(c.trust == "candidate" for c in choices)


def test_a_damaged_build_or_model_leaves_the_list(pair: Pair) -> None:
    runtime_file = pair.root / "runtimes" / "b0001-cpu" / "ggml.dll"
    runtime_file.write_bytes(b"tampered")
    choices = list_model_choices(pair.root, pair.manifest, pair.registry)
    # LFM3 is only compatible with the damaged build; Qwen still has the intact one.
    assert [c.model_id for c in choices] == ["fake-qwen"]
    assert choices[0].build_id == "b0000-cpu"
    model_file = pair.root / "models" / pair.qwen.sha256 / pair.qwen.filename
    model_file.write_bytes(model_file.read_bytes() + b"x")  # wrong size
    assert list_model_choices(pair.root, pair.manifest, pair.registry) == ()


def test_listing_reads_only_and_writes_nothing(pair: Pair) -> None:
    before = active_pointer_path(pair.root).read_bytes()
    list_model_choices(pair.root, pair.manifest, pair.registry)
    assert active_pointer_path(pair.root).read_bytes() == before
    assert (
        not attestation_path(pair.root).exists() and not preview_enablement_path(pair.root).exists()
    )


# -- build compatibility -------------------------------------------------------------------------------------------------


def test_a_model_runs_only_on_a_listed_build_preferring_the_active_one(pair: Pair) -> None:
    pair.attest(pair.build_a, pair.build_b)
    # LFM3 lists b0001 only, whatever is active.
    lfm = select_model(pair.root, pair.manifest, pair.registry, "fake-lfm", request_in_flight=False)
    assert lfm.changed and lfm.choice.build_id == "b0001-cpu"
    assert read_pointer(pair.root)["runtime_build_id"] == "b0001-cpu"
    # Qwen lists both; the active build b0001 is compatible, so it is kept rather than the first listed (b0000).
    qwen = select_model(
        pair.root, pair.manifest, pair.registry, "fake-qwen", request_in_flight=False
    )
    assert qwen.changed and qwen.choice.build_id == "b0001-cpu"
    # From a model on b0000, Qwen is already active on its first listed build: nothing is written.
    record_active(pair.root, pair.build_a, pair.qwen)
    before = active_pointer_path(pair.root).read_bytes()
    same = select_model(
        pair.root, pair.manifest, pair.registry, "fake-qwen", request_in_flight=False
    )
    assert not same.changed and active_pointer_path(pair.root).read_bytes() == before


def test_activation_refuses_an_unlisted_unpinned_or_missing_build(pair: Pair) -> None:
    with pytest.raises(ActivationRefused) as incompatible:
        activate(pair.root, pair.manifest, pair.registry, build_id="b0000-cpu", model_id="fake-lfm")
    assert incompatible.value.code == "build_incompatible"
    for build_id, model_id, code in (
        ("b7777-cpu", "fake-qwen", "unknown_build_or_model"),
        ("b0000-cpu", "nope", "unknown_build_or_model"),
        ("b0000-cpu", "fake-absent", "model_not_imported"),
    ):
        before = active_pointer_path(pair.root).read_bytes()
        with pytest.raises(ActivationRefused) as refused:
            activate(pair.root, pair.manifest, pair.registry, build_id=build_id, model_id=model_id)
        assert refused.value.code == code
        assert active_pointer_path(pair.root).read_bytes() == before


def test_an_empty_compatible_list_allows_nothing(pair: Pair) -> None:
    registry = ModelRegistry((replace(pair.qwen, compatible_builds=()),))
    assert list_model_choices(pair.root, pair.manifest, registry) == ()
    with pytest.raises(ActivationRefused) as refused:
        activate(pair.root, pair.manifest, registry, build_id="b0000-cpu", model_id="fake-qwen")
    assert refused.value.code == "build_incompatible"


def test_the_pinned_registry_lists_the_decided_builds_and_stays_unqualified() -> None:
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    runtime = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    assert not registry.problems and not runtime.problems
    pinned = {b.build_id for b in runtime.builds}
    for entry in registry.entries:
        assert entry.qualified is False
        assert entry.compatible_builds and set(entry.compatible_builds) <= pinned
        expected = ("b11960-cpu",) if entry.architecture == "lfm3" else ("b11840-cpu", "b11960-cpu")
        assert entry.compatible_builds == expected, entry.model_id
    assert all(build.qualified is False for build in runtime.builds)


@pytest.mark.parametrize(
    "value",
    ["b0000-cpu", ["b0000-cpu", "b0000-cpu"], [3], ["../x"], [""], None],
)
def test_a_malformed_compatible_builds_field_drops_the_entry(value: object) -> None:
    document = json.loads(MODEL_REGISTRY_PATH.read_text(encoding="utf-8"))
    entry = document["models"][0]
    entry["compatible_builds"] = value
    parsed = load_model_registry(json.dumps({"schema_version": 1, "models": [entry]}))
    assert parsed.entries == () and "compatible_builds" in parsed.problems[0]


def test_a_registry_entry_without_the_field_still_parses_as_not_selectable() -> None:
    document = json.loads(MODEL_REGISTRY_PATH.read_text(encoding="utf-8"))
    entry = document["models"][0]
    del entry["compatible_builds"]
    parsed = load_model_registry(json.dumps({"schema_version": 1, "models": [entry]}))
    assert parsed.entries[0].compatible_builds == ()


# -- Preview enablement is per model identity ----------------------------------------------------------------------------


def test_enabling_one_model_does_not_enable_another_and_the_record_holds_several(
    pair: Pair,
) -> None:
    pair.attest(pair.build_a, pair.build_b)
    enable_preview(pair.root, pair.manifest, pair.registry)  # Qwen on b0000
    assert preview_enabled_for(pair.root, pair.qwen, pair.build_a)
    assert not preview_enabled_for(pair.root, pair.lfm, pair.build_b)
    assert not preview_enabled_for(
        pair.root, pair.qwen, pair.build_b
    )  # per (model, build) identity
    select_model(pair.root, pair.manifest, pair.registry, "fake-lfm", request_in_flight=False)
    status = read_status(pair.root, pair.manifest, pair.registry)
    assert (
        status.state == STATE_PREVIEW_AVAILABLE
    )  # switching needs the same explicit confirmation as before
    enable_preview(pair.root, pair.manifest, pair.registry)  # LFM3 on b0001
    assert len(read_preview_identities(pair.root)) == 2
    assert preview_enabled_for(pair.root, pair.qwen, pair.build_a)
    assert preview_enabled_for(pair.root, pair.lfm, pair.build_b)


def test_switching_back_to_an_enabled_model_needs_no_new_confirmation(pair: Pair) -> None:
    pair.attest(pair.build_a, pair.build_b)
    enable_preview(pair.root, pair.manifest, pair.registry)
    select_model(pair.root, pair.manifest, pair.registry, "fake-lfm", request_in_flight=False)
    enable_preview(pair.root, pair.manifest, pair.registry)
    select_model(pair.root, pair.manifest, pair.registry, "fake-qwen", request_in_flight=False)
    # Qwen is now on b0001 (the active build was compatible), which is a different identity than the one enabled (b0000).
    assert read_status(pair.root, pair.manifest, pair.registry).state == STATE_PREVIEW_AVAILABLE
    record_active(pair.root, pair.build_a, pair.qwen)
    assert read_status(pair.root, pair.manifest, pair.registry).state == STATE_PREVIEW


def test_revoking_one_identity_leaves_the_others_enabled(pair: Pair) -> None:
    enable_preview(pair.root, pair.manifest, pair.registry)
    record_active(pair.root, pair.build_b, pair.lfm)
    enable_preview(pair.root, pair.manifest, pair.registry)
    assert revoke_preview(pair.root, pair.lfm, pair.build_b)
    assert preview_enabled_for(pair.root, pair.qwen, pair.build_a)
    assert not preview_enabled_for(pair.root, pair.lfm, pair.build_b)
    assert revoke_preview(pair.root, pair.qwen, pair.build_a)
    assert not preview_enablement_path(pair.root).exists()


def test_integration_revoke_acts_on_the_active_identity_only(pair: Pair) -> None:
    ai = owner(pair)
    try:
        enable_preview(pair.root, pair.manifest, pair.registry)
        record_active(pair.root, pair.build_b, pair.lfm)
        assert ai.enable_preview()[0]
        assert ai.revoke_preview()[0]
        assert preview_enabled_for(pair.root, pair.qwen, pair.build_a)
        assert not preview_enabled_for(pair.root, pair.lfm, pair.build_b)
    finally:
        ai.shutdown()


def test_a_request_runs_only_for_the_enabled_identity(pair: Pair) -> None:
    """The request gate matches the verified active identity against the list, so a stale entry admits nothing else."""

    pair.attest(pair.build_a, pair.build_b)
    enable_preview(pair.root, pair.manifest, pair.registry)  # Qwen on b0000
    select_model(pair.root, pair.manifest, pair.registry, "fake-lfm", request_in_flight=False)
    install = pair.as_install(pair.build_b, pair.lfm)
    service = make_service(install, policy=PREVIEW_POLICY)
    refused = service.run(request_for())
    assert refused.reason == "preview_not_enabled"


# -- refusal while a request is in flight, and when unattested ------------------------------------------------------------


def test_selection_is_refused_while_a_request_is_in_flight(pair: Pair) -> None:
    pair.attest(pair.build_a, pair.build_b)
    before = active_pointer_path(pair.root).read_bytes()
    with pytest.raises(SelectionRefused) as refused:
        select_model(pair.root, pair.manifest, pair.registry, "fake-lfm", request_in_flight=True)
    assert refused.value.code == "request_in_flight"
    assert active_pointer_path(pair.root).read_bytes() == before


def test_the_integration_refuses_to_switch_during_a_running_request(pair: Pair) -> None:
    pair.attest(pair.build_a, pair.build_b)
    enable_preview(pair.root, pair.manifest, pair.registry)
    ai = owner(pair)
    ai.service = make_service(pair.as_install(pair.build_a, pair.qwen), policy=PREVIEW_POLICY)
    done = threading.Event()
    request = request_for("sleep", request_id="inflight", extra="TEST_SLEEP:0")
    try:
        assert ai.submit(request, lambda _outcome: done.set()).accepted
        before = active_pointer_path(pair.root).read_bytes()
        ok, message = ai.select_model("fake-lfm")
        assert not ok and "Another AI request is running" in message
        assert active_pointer_path(pair.root).read_bytes() == before
        assert ai.cancel("inflight")
        deadline = time.monotonic() + 20
        while not ai.service.shutdown(0.1) and time.monotonic() < deadline:
            pass
    finally:
        ai.shutdown()


def test_the_service_reports_busy_while_its_worker_runs(pair: Pair) -> None:
    pair.attest(pair.build_a)
    enable_preview(pair.root, pair.manifest, pair.registry)
    service = make_service(pair.as_install(pair.build_a, pair.qwen), policy=PREVIEW_POLICY)
    assert service.busy is False
    submission = service.submit(request_for("sleep", request_id="busy1"), lambda _o: None)
    assert submission.accepted and service.busy is True
    service.cancel("busy1")
    assert service.shutdown(20.0)


def test_selection_refuses_without_an_attestation_and_never_records_one(pair: Pair) -> None:
    before = active_pointer_path(pair.root).read_bytes()
    ai = owner(pair)
    try:
        ok, message = ai.select_model("fake-lfm")
        assert not ok and message == "Operator-managed outbound restriction must be attested."
        assert not attestation_path(pair.root).exists()
        assert active_pointer_path(pair.root).read_bytes() == before
    finally:
        ai.shutdown()


def test_selection_refuses_when_the_attestation_does_not_cover_the_selected_build(
    pair: Pair,
) -> None:
    pair.attest(pair.build_a)  # covers b0000 only; LFM3 needs b0001
    before = active_pointer_path(pair.root).read_bytes()
    attestation_before = attestation_path(pair.root).read_bytes()
    ai = owner(pair)
    try:
        ok, message = ai.select_model("fake-lfm")
        assert not ok
        assert message == (
            "The recorded outbound restriction does not cover runtime b0001-cpu. "
            "Record an attestation for this build and its executable."
        )
        assert active_pointer_path(pair.root).read_bytes() == before
        assert attestation_path(pair.root).read_bytes() == attestation_before
    finally:
        ai.shutdown()


def test_the_selector_reuses_the_availability_wording_for_attestation(pair: Pair) -> None:
    pair.attest(pair.build_a)
    ai = owner(pair)
    try:
        enable_preview(pair.root, pair.manifest, pair.registry)
        shared = egress_refusal_text("not_covered", "b0001-cpu")
        assert ai.select_model("fake-lfm") == (False, shared)
        record_active(pair.root, pair.build_b, pair.lfm)
        enable_preview(pair.root, pair.manifest, pair.registry)
        assert ai.availability() == (OutcomeCode.EGRESS_NOT_ATTESTED, shared)
    finally:
        ai.shutdown()


def test_selecting_works_end_to_end_through_the_integration(pair: Pair) -> None:
    pair.attest(pair.build_a, pair.build_b)
    ai = owner(pair)
    try:
        assert [c.display_name for c in ai.model_choices()] == [
            "Fake Qwen 4B Q4",
            "Fake LFM3 1.7B Q4",
        ]
        ok, message = ai.select_model("fake-lfm")
        assert ok and "Switched to Fake LFM3 1.7B Q4 on runtime b0001-cpu" in message
        assert "not enabled" in message  # it never enables Preview itself
        assert not preview_enablement_path(pair.root).exists()
        assert [c.active for c in ai.model_choices()] == [False, True]
        again_ok, again = ai.select_model("fake-lfm")
        assert again_ok and "already active" in again
        bad_ok, bad = ai.select_model("fake-absent")
        assert not bad_ok and "not imported and verified" in bad
    finally:
        ai.shutdown()


# -- one activation authority, no background work ------------------------------------------------------------------------


def test_the_selector_and_the_admin_tool_use_the_same_activation_function() -> None:
    import tools.ai_assist_admin as admin

    assert selector_module.activate is activation_module.activate is activate
    assert admin.activate is activate


def test_activation_goes_through_the_shared_function(pair: Pair, monkeypatch) -> None:
    pair.attest(pair.build_a, pair.build_b)
    calls: list[tuple[str, str]] = []
    real = selector_module.activate

    def spy(root, runtime, registry, *, build_id, model_id):
        calls.append((build_id, model_id))
        return real(root, runtime, registry, build_id=build_id, model_id=model_id)

    monkeypatch.setattr(selector_module, "activate", spy)
    ai = owner(pair)
    try:
        assert ai.select_model("fake-lfm")[0]
    finally:
        ai.shutdown()
    assert calls == [("b0001-cpu", "fake-lfm")]


def test_active_json_has_one_writer_for_operator_activation() -> None:
    """``record_active`` is called by the shared activation function only (the qualification harness keeps its own call)."""

    callers = []
    for base in (REPO / "src", REPO / "tools"):
        for path in base.rglob("*.py"):
            if path.parts[-3:-1] == ("tools", "qualification") or "qualification" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"\brecord_active\(", text) and "def record_active" not in text:
                callers.append(path.relative_to(REPO).as_posix())
    assert callers == ["src/ai_assist/activation.py"]


def test_admin_activate_refuses_an_incompatible_pair_before_writing(tmp_path, capsys) -> None:
    import tools.ai_assist_admin as admin

    code = admin.main(
        [
            "--root",
            str(tmp_path / "ai"),
            "activate",
            "--build-id",
            "b11840-cpu",
            "--model-id",
            "lfm3-1.7b-q4_k_m-liquidai",
        ]
    )
    assert code == 2 and "refused: build_incompatible" in capsys.readouterr().out
    assert not (tmp_path / "ai").exists()


def test_the_selector_starts_no_process_and_no_thread(pair: Pair, monkeypatch) -> None:
    pair.attest(pair.build_a, pair.build_b)

    def forbidden(*args, **kwargs):
        raise AssertionError("the selector must not launch a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    ai = owner(pair)
    try:
        threads = threading.active_count()
        assert ai.select_model("fake-lfm")[0]
        assert ai.model_choices()
        assert threading.active_count() == threads
    finally:
        ai.shutdown()


def test_every_model_and_build_stays_unqualified_after_a_switch(pair: Pair) -> None:
    pair.attest(pair.build_a, pair.build_b)
    select_model(pair.root, pair.manifest, pair.registry, "fake-lfm", request_in_flight=False)
    assert all(not e.qualified for e in pair.registry.entries)
    assert all(not b.qualified for b in pair.manifest.builds)
    status = read_status(pair.root, pair.manifest, pair.registry)
    assert status.state in (STATE_PREVIEW, STATE_PREVIEW_AVAILABLE) and status.trust != "qualified"
