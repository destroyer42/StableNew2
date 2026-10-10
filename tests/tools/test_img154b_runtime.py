"""PR-IMG-MODELS-154B T28-T36: isolated layout, served-file proof, materialization, launch profile and ownership.

Synthetic temporary files and fakes only. No model is read, no process or runtime is started.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from tools.qualification.img154 import isolation as iso
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154b import runtime as rt

CONTENT = {
    "transformer": b"transformer-bytes-" * 40,
    "text_encoder": b"encoder-bytes-" * 55,
    "vae": b"vae-bytes-" * 12,
}


def synthetic_manifest() -> mf.QualificationManifest:
    assets = {}
    for role, spec in mf.FROZEN_ASSETS.items():
        data = CONTENT[role]
        assets[role] = mf.AssetSpec(
            role, spec.filename, len(data), hashlib.sha256(data).hexdigest(), spec.models_subdir
        )
    return mf.QualificationManifest(assets=assets)


@pytest.fixture
def plan():
    return synthetic_manifest()


@pytest.fixture
def library(tmp_path, plan):
    """A source library with the three files (outside the qualification root)."""

    root = tmp_path / "library"
    paths = {}
    for role, spec in plan.assets.items():
        path = root / spec.models_subdir / spec.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(CONTENT[role])
        paths[role] = path
    return paths


@pytest.fixture
def layout(tmp_path, plan):
    return rt.plan_runtime_layout(tmp_path / "qualification", plan)


def materialized(layout, library, plan):
    rt.materialize_served_files(layout, library, plan)
    rt.write_isolated_config(layout)


# --- T28: layout ---------------------------------------------------------------------------------------------------------


def test_t28_layout_names_only_and_matches_the_154a_served_paths(tmp_path):
    plan = mf.build_manifest()
    layout = rt.plan_runtime_layout(tmp_path / "q", plan)
    assert not (tmp_path / "q").exists()  # planning creates nothing
    relative = {
        role: Path(path).relative_to(tmp_path / "q").as_posix()
        for role, path in layout.served_paths.items()
    }
    assert relative == plan.served_relative_paths()
    assert Path(layout.data_dir) == tmp_path / "q" / "forge-data"
    assert set(layout.served_paths) == set(plan.assets)


def test_t28_the_154a_isolation_validators_decide_the_root(tmp_path):
    reserved = {
        "repository": str(tmp_path / "repo"),
        "managed_forge_install": str(tmp_path / "forge"),
        "model_library": str(tmp_path / "library"),
    }
    ok = iso.validate_isolation(str(tmp_path / "qualification"), reserved, iso.RealFs())
    assert not [f for f in ok if f.severity == "refuse"]
    inside = iso.validate_isolation(str(tmp_path / "repo" / "q"), reserved, iso.RealFs())
    assert any(f.code == "ISOLATION_INSIDE_RESERVED" for f in inside)


def test_t28_storage_for_separate_copies_is_assessed_not_assumed():
    cost = rt.storage_cost()
    assert cost["assets_bytes"] == 6_158_115_074 + 8_044_982_048 + 335_304_388
    assert (
        cost["required_bytes"]
        == cost["assets_bytes"] + rt.EVIDENCE_RESERVE_BYTES + rt.OUTPUT_RESERVE_BYTES
    )
    assert rt.assess_storage(cost["required_bytes"]) == []
    assert [f.code for f in rt.assess_storage(cost["required_bytes"] - 1)] == [
        "STORAGE_INSUFFICIENT"
    ]
    for unknown in (None, True, float("nan"), -5):
        assert rt.assess_storage(unknown)[0].severity == "inconclusive"


# --- T29: materialization ------------------------------------------------------------------------------------------------


def test_t29_materialization_copies_verifies_and_never_touches_the_sources(
    tmp_path, plan, library, layout
):
    before = {
        role: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
        for role, p in library.items()
    }
    results = rt.materialize_served_files(layout, library, plan)
    assert {r.role: r.action for r in results} == dict.fromkeys(plan.assets, "copied")
    for role, _spec in plan.assets.items():
        served = Path(layout.served_paths[role])
        assert served.read_bytes() == CONTENT[role]
        assert os.stat(served).st_nlink == 1  # a copy, never a hard link to the source
        assert not os.path.samefile(served, library[role])
        assert not Path(str(served) + ".partial").exists()
    after = {
        role: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
        for role, p in library.items()
    }
    assert before == after
    assert rt.write_isolated_config(layout) is True
    assert rt.write_isolated_config(layout) is False  # never rewritten
    assert json.loads(Path(layout.config_path).read_text()) == {"VERSION_UID": "PY313"}


def test_t29_a_second_run_verifies_and_does_not_overwrite(plan, library, layout):
    rt.materialize_served_files(layout, library, plan)
    mtimes = {r: os.stat(p).st_mtime_ns for r, p in layout.served_paths.items()}
    again = rt.materialize_served_files(layout, library, plan)
    assert {r.action for r in again} == {"already_present_verified"}
    assert mtimes == {r: os.stat(p).st_mtime_ns for r, p in layout.served_paths.items()}


def test_t29_a_wrong_existing_target_is_refused_and_left_alone(plan, library, layout):
    target = Path(layout.served_paths["vae"])
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * len(CONTENT["vae"]))  # same size, other bytes
    with pytest.raises(rt.RuntimePathError):
        rt.materialize_served_files(layout, library, plan)
    assert target.read_bytes() == b"x" * len(CONTENT["vae"])  # not repaired
    assert not Path(
        layout.served_paths["transformer"]
    ).exists()  # nothing was copied before the refusal


@pytest.mark.parametrize(
    "what",
    ["wrong_bytes", "wrong_size", "wrong_name", "missing_role", "inside_root", "partial_present"],
)
def test_t29_unfit_sources_are_refused_before_anything_is_written(
    tmp_path, plan, library, layout, what
):
    sources = dict(library)
    if what == "wrong_bytes":
        Path(library["vae"]).write_bytes(b"y" * len(CONTENT["vae"]))
    elif what == "wrong_size":
        Path(library["text_encoder"]).write_bytes(b"short")
    elif what == "wrong_name":
        renamed = library["vae"].with_name("flux1AE_v10_copy.safetensors")
        renamed.write_bytes(CONTENT["vae"])
        sources["vae"] = renamed
    elif what == "missing_role":
        del sources["vae"]
    elif what == "inside_root":
        inside = Path(layout.root) / "assets" / library["vae"].name
        inside.parent.mkdir(parents=True)
        inside.write_bytes(CONTENT["vae"])
        sources["vae"] = inside
    elif what == "partial_present":
        partial = Path(layout.served_paths["vae"] + ".partial")
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"left over")
    with pytest.raises((rt.RuntimePathError,)):
        rt.materialize_served_files(layout, sources, plan)
    if what == "partial_present":
        assert not Path(layout.served_paths["transformer"]).exists()
        assert (
            Path(layout.served_paths["vae"] + ".partial").read_bytes() == b"left over"
        )  # not cleaned
    elif what == "wrong_bytes":
        # detected during the single copy-and-hash pass: no corrupt target and no partial survives
        assert not Path(layout.served_paths["vae"]).exists()
        assert not list(Path(layout.root).rglob("*.partial"))
    else:
        assert not Path(layout.served_paths["transformer"]).exists()


def test_t29_a_source_that_changes_after_the_size_check_is_caught_by_the_digest_and_leaves_no_partial(
    monkeypatch, plan, library, layout
):
    real_open = open
    state = {"flipped": False}

    def flaky_open(path, mode="r", *args, **kwargs):
        if str(path) == str(library["transformer"]) and "b" in mode and not state["flipped"]:
            state["flipped"] = True
            data = bytes(len(CONTENT["transformer"]))  # same length, different bytes
            import io

            return io.BytesIO(data)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    with pytest.raises(rt.RuntimePathError):
        rt.materialize_served_files(layout, library, plan)
    monkeypatch.undo()
    assert not Path(layout.served_paths["transformer"]).exists()
    assert not Path(layout.served_paths["transformer"] + ".partial").exists()


# --- T30: served-file proof ----------------------------------------------------------------------------------------------


def test_t30_a_complete_isolated_layout_verifies(plan, library, layout):
    materialized(layout, library, plan)
    proof = rt.verify_served_layout(layout, plan)
    assert proof.verified, proof.findings
    assert {r: m.sha256 for r, m in proof.measurements.items()} == {
        r: s.sha256 for r, s in plan.assets.items()
    }
    assert rt.served_unchanged(proof, layout, plan) == []


def test_t30_wrong_bytes_wrong_size_and_missing_files_are_refused(plan, library, layout):
    materialized(layout, library, plan)
    Path(layout.served_paths["vae"]).write_bytes(b"z" * len(CONTENT["vae"]))
    codes = {f.code for f in rt.verify_served_layout(layout, plan).findings}
    assert "ASSET_SHA256_MISMATCH" in codes
    Path(layout.served_paths["vae"]).write_bytes(b"short")
    assert "ASSET_SIZE_MISMATCH" in {f.code for f in rt.verify_served_layout(layout, plan).findings}
    Path(layout.served_paths["vae"]).unlink()
    assert "SERVED_FILE_MISSING" in {f.code for f in rt.verify_served_layout(layout, plan).findings}


def test_t30_a_served_file_that_is_a_hard_link_to_another_file_is_an_alias(plan, library, layout):
    materialized(layout, library, plan)
    served = Path(layout.served_paths["vae"])
    served.unlink()
    try:
        os.link(library["vae"], served)
    except OSError:
        pytest.skip("hard links are not permitted on this host")
    findings = rt.verify_served_layout(layout, plan).findings
    assert "SERVED_FILE_ALIASED" in {f.code for f in findings}


def test_t30_a_symlinked_served_file_is_refused(plan, library, layout, tmp_path):
    materialized(layout, library, plan)
    served = Path(layout.served_paths["vae"])
    served.unlink()
    try:
        os.symlink(library["vae"], served)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this host")
    assert "SERVED_FILE_NOT_PLAIN" in {
        f.code for f in rt.verify_served_layout(layout, plan).findings
    }


def test_t30_a_file_that_changes_during_hashing_is_refused(plan, library, layout):
    materialized(layout, library, plan)
    target = layout.served_paths["transformer"]

    def mutating_hasher(path):
        digest, size = rt.sha256_of(path)
        if str(path) == str(target):
            with open(path, "ab") as stream:  # the file grows while it is being verified
                stream.write(b"!")
        return digest, size

    codes = {f.code for f in rt.verify_served_layout(layout, plan, hasher=mutating_hasher).findings}
    assert "SERVED_FILE_CHANGED_DURING_VERIFICATION" in codes


def test_t30_a_change_after_the_proof_is_detected_cheaply(plan, library, layout):
    materialized(layout, library, plan)
    proof = rt.verify_served_layout(layout, plan)
    with open(layout.served_paths["text_encoder"], "ab") as stream:
        stream.write(b"+")
    assert [f.code for f in rt.served_unchanged(proof, layout, plan)] == [
        "SERVED_FILE_CHANGED_AFTER_PROOF"
    ]


def test_t30_discovery_directories_must_hold_exactly_the_frozen_file(plan, library, layout):
    materialized(layout, library, plan)
    (Path(layout.model_directories["vae"]) / "another_vae.safetensors").write_bytes(b"x")
    findings = rt.verify_served_layout(layout, plan).findings
    assert "LAYOUT_UNEXPECTED_ENTRY" in {f.code for f in findings}


def test_t30_config_must_be_exactly_the_version_marker(plan, library, layout):
    materialized(layout, library, plan)
    Path(layout.config_path).write_text(json.dumps({"VERSION_UID": "PY313", "forge_preset": "all"}))
    assert "CONFIG_UNEXPECTED" in {f.code for f in rt.verify_served_layout(layout, plan).findings}
    Path(layout.config_path).write_text("{not json")
    assert "CONFIG_UNREADABLE" in {f.code for f in rt.verify_served_layout(layout, plan).findings}
    Path(layout.config_path).unlink()
    assert "CONFIG_MISSING" in {f.code for f in rt.verify_served_layout(layout, plan).findings}


def test_t30_the_proof_applies_to_the_served_path_not_to_a_matching_source(plan, library, layout):
    # sources match perfectly, but nothing is served: a source match never satisfies the served-file proof
    proof = rt.verify_served_layout(layout, plan)
    assert not proof.verified
    assert "SERVED_FILE_MISSING" in {f.code for f in proof.findings}


# --- T31: launch profile -------------------------------------------------------------------------------------------------

CONTRACT = {
    "launch_policy": {
        "launch_script": "launch.py",
        "data_dir_flag": "--data-dir",
        "env": {
            "GRADIO_ANALYTICS_ENABLED": "False",
            "HF_HUB_OFFLINE": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        "forbidden_flag_fragments": ["listen", "share", "xformers", "fp8", "autolaunch"],
    }
}


def test_t31_the_launch_profile_is_exactly_the_isolated_allow_listed_command(tmp_path, layout):
    install = str(tmp_path / "forge-install")
    profile = rt.build_isolated_launch_profile(layout, install, contract=CONTRACT)
    assert list(profile.command) == [
        os.path.join(install, "venv", "Scripts", "python.exe"),
        "launch.py",
        "--uv",
        "--api",
        "--port",
        "7886",
        "--data-dir",
        layout.data_dir,
        "--skip-install",
    ]
    assert profile.endpoint == "http://127.0.0.1:7886" and profile.port == 7886
    assert profile.env_overrides["COMMANDLINE_ARGS"] == ""
    assert (
        rt.validate_launch(
            profile,
            layout,
            install,
            forbidden_fragments=CONTRACT["launch_policy"]["forbidden_flag_fragments"],
        )
        == []
    )
    assert not (Path(layout.runtime_dir)).exists()  # building the profile created nothing


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda c: [*c, "--forge-ref-a1111-home", "C:/library"], "LAUNCH_FLAG_SET"),
        (lambda c: [*c, "--ckpt-dir", "C:/library"], "LAUNCH_FLAG_SET"),
        (lambda c: [*c, "--listen"], "LAUNCH_FLAG_SET"),
        (lambda c: [*c, "--xformers"], "LAUNCH_FLAG_SET"),
        (lambda c: [c[0], "webui.py", *c[2:]], "LAUNCH_SCRIPT"),
        (lambda c: ["python", *c[1:]], "LAUNCH_INTERPRETER"),
        (lambda c: [x if x != "7886" else "7871" for x in c], "LAUNCH_PORT"),
        (lambda c: [x if x != "--skip-install" else "--api" for x in c], "LAUNCH_FLAG_SET"),
    ],
)
def test_t31_any_other_launch_command_is_refused(tmp_path, layout, mutation, code):
    install = str(tmp_path / "forge-install")
    good = rt.build_isolated_launch_profile(layout, install, contract=CONTRACT)
    bad = replace(good, command=tuple(mutation(list(good.command))))
    findings = rt.validate_launch(bad, layout, install, forbidden_fragments=("listen", "xformers"))
    assert code in {f.code for f in findings}


def test_t31_data_directory_endpoint_environment_and_caches_are_pinned(tmp_path, layout):
    install = str(tmp_path / "forge-install")
    good = rt.build_isolated_launch_profile(layout, install, contract=CONTRACT)
    other_data = replace(
        good,
        command=tuple(x if x != layout.data_dir else str(tmp_path / "other") for x in good.command),
    )
    assert "LAUNCH_DATA_DIR" in {f.code for f in rt.validate_launch(other_data, layout, install)}
    assert "LAUNCH_ENDPOINT" in {
        f.code
        for f in rt.validate_launch(replace(good, endpoint="http://0.0.0.0:7886"), layout, install)
    }
    inherited = dict(good.env_overrides)
    inherited.pop("COMMANDLINE_ARGS")
    assert "LAUNCH_ENV_COMMANDLINE_ARGS" in {
        f.code for f in rt.validate_launch(replace(good, env_overrides=inherited), layout, install)
    }
    leaking = dict(good.env_overrides, HF_HUB_CACHE=str(tmp_path / "global-cache"))
    assert "LAUNCH_ENV_CACHE" in {
        f.code for f in rt.validate_launch(replace(good, env_overrides=leaking), layout, install)
    }
    assert "LAUNCH_WORKING_DIR" in {
        f.code
        for f in rt.validate_launch(replace(good, working_dir=str(tmp_path / "x")), layout, install)
    }


def test_t31_runtime_directories_are_created_only_by_the_explicit_step(layout):
    rt.prepare_runtime_dirs(layout)
    for name in ("hf", "matplotlib", "yolo", "uv-cache"):
        assert (Path(layout.runtime_dir) / name).is_dir()
    assert Path(layout.evidence_dir).is_dir() and Path(layout.outputs_dir).is_dir()


# --- T32: ownership and shutdown (fakes) ---------------------------------------------------------------------------------


class FakeManager:
    def __init__(self, pid=4242, owns=True):
        self.pid = pid
        self.owns_process = owns
        self.tail = {"stdout_tail": "out", "stderr_tail": "err", "pid": pid, "running": True}

    def get_recent_output_tail(self, max_lines=60):
        return self.tail


class FakeForge:
    def __init__(
        self, profile, *, pid=4242, owns=True, stop_result=None, stop_raises=None, hang=None
    ):
        self.profile = profile
        self.manager = None
        self._pid, self._owns = pid, owns
        self._stop_result, self._stop_raises, self._hang = stop_result, stop_raises, hang
        self.calls = []

    def start(self):
        self.calls.append("start")
        self.manager = FakeManager(self._pid, self._owns)
        return {"started_at": 1.0, "pid": self._pid, "owns_process": self._owns}

    def stop(self):
        self.calls.append("stop")
        if self._hang is not None:
            self._hang.wait(5)
        if self._stop_raises:
            raise self._stop_raises
        return (
            self._stop_result
            if self._stop_result is not None
            else {"owned_pids": [4242, 4243], "survivors": []}
        )


class FakeFacts:
    def __init__(self, *, alive=(4242, 4243), created=100.0, listeners=(4243,), children=(4243,)):
        self.alive = set(alive)
        self.created = created
        self.listeners = list(listeners)
        self.kids = list(children)

    def exists(self, pid):
        return pid in self.alive

    def create_time(self, pid):
        return self.created if pid in self.alive else None

    def children(self, pid):
        return list(self.kids)

    def listening_pids(self, port):
        assert port == 7886
        return list(self.listeners)

    def cmdline(self, pid):
        return ("python", "launch.py")


@pytest.fixture
def profile(tmp_path, layout):
    return rt.build_isolated_launch_profile(layout, str(tmp_path / "install"), contract=CONTRACT)


def started_runtime(profile, facts=None, **forge_kwargs):
    forge = FakeForge(profile.as_runtime_dict(), **forge_kwargs)
    facts = facts or FakeFacts()
    runtime = rt.OwnedRuntime(
        profile, forge_factory=lambda p: forge, process_facts=facts, stop_timeout_s=2.0
    )
    runtime.start()
    return runtime, forge, facts


def test_t32_ownership_is_verified_from_the_manager_the_tree_and_the_listener(profile):
    runtime, forge, _ = started_runtime(profile)
    facts = runtime.verify_ownership()
    assert facts.owned and facts.pid == 4242 and facts.tree == (4242, 4243)
    assert facts.endpoint_in_tree and facts.start_time_unchanged and facts.problems == ()
    assert forge.calls == ["start"]


@pytest.mark.parametrize(
    "setup,problem",
    [
        ({"owns": False}, "launch-session ownership"),
        ({"facts": FakeFacts(alive=())}, "does not exist"),
        ({"facts": FakeFacts(listeners=())}, "nothing listens"),
        ({"facts": FakeFacts(listeners=(9999,))}, "outside the owned tree"),
    ],
)
def test_t32_ownership_fails_closed_on_every_contradiction(profile, setup, problem):
    runtime, _, _ = started_runtime(profile, **setup)
    facts = runtime.verify_ownership()
    assert not facts.owned
    assert any(problem in item for item in facts.problems), facts.problems


def test_t32_pid_reuse_is_detected_by_a_changed_start_time(profile):
    facts = FakeFacts()
    runtime, _, _ = started_runtime(profile, facts=facts)
    facts.created = 999.0
    result = runtime.verify_ownership()
    assert not result.owned and not result.start_time_unchanged


def test_t32_a_runtime_cannot_be_started_twice_and_verification_without_start_is_not_owned(profile):
    runtime, _, _ = started_runtime(profile)
    with pytest.raises(rt.RuntimePathError):
        runtime.start()
    never = rt.OwnedRuntime(
        profile, forge_factory=lambda p: FakeForge(p), process_facts=FakeFacts()
    )
    assert never.verify_ownership().owned is False
    assert never.stop().outcome == "not_attempted"


def test_t32_a_clean_manager_owned_stop_is_verified_only_with_no_survivors(profile):
    facts = FakeFacts()
    runtime, forge, _ = started_runtime(profile, facts=facts)
    facts.alive.clear()  # the manager's stop removed the tree
    result = runtime.stop()
    assert result.outcome == "verified_clean" and result.verified and result.survivors == ()
    assert forge.calls == ["start", "stop"]


def test_t32_a_survivor_after_the_stop_is_reported_and_not_clean(profile):
    facts = FakeFacts()
    runtime, _, _ = started_runtime(
        profile, facts=facts, stop_result={"owned_pids": [4242, 4243], "survivors": [4243]}
    )
    facts.alive = {4243}
    result = runtime.stop()
    assert result.outcome == "requested_unverified" and result.survivors == (4243,)


def test_t32_a_stop_that_raises_or_hangs_is_not_clean_and_triggers_operator_instructions(profile):
    import threading

    runtime, _, _ = started_runtime(profile, stop_raises=RuntimeError("boom"))
    failed = runtime.stop()
    assert failed.outcome == "requested_unverified" and "RuntimeError" in failed.detail

    release = threading.Event()
    runtime, _, _ = started_runtime(profile, hang=release)
    hung = runtime.stop()
    release.set()
    assert hung.outcome == "timed_out" and hung.timed_out
    assert any("no other process authority" in line for line in rt.RECOVERY_INSTRUCTIONS)


def test_t32_the_runtime_module_has_no_signal_or_kill_authority_of_its_own():
    import ast

    source = Path(rt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    assert not called & {"kill", "terminate", "send_signal", "killpg", "TerminateProcess"}
    code = source.replace(
        ast.get_docstring(tree, clean=False) or "", ""
    )  # the docstring may name what is NOT done
    for needle in ("taskkill", "Stop-Process", "os.kill", ".kill(", ".terminate("):
        assert needle not in code


def test_t32_a_stop_that_never_observed_the_tree_or_the_root_gone_is_not_verified(profile):
    forge = FakeForge(profile.as_runtime_dict(), pid=None)
    runtime = rt.OwnedRuntime(
        profile,
        forge_factory=lambda p: forge,
        process_facts=FakeFacts(alive=()),
        stop_timeout_s=2.0,
    )
    runtime.start()
    result = runtime.stop()
    assert (
        result.succeeded and not result.verified
    )  # absence of an observation is not a clean shutdown
    assert result.outcome == "requested_unverified"


# --- T33-T34: boot-window ownership and the tree after the stop (independent-review findings) ----------------------------


def test_t33_the_boot_window_needs_the_process_identity_not_a_listener(profile):
    runtime, _, facts = started_runtime(profile, facts=FakeFacts(listeners=()))
    boot = runtime.verify_ownership(require_listener=False)
    assert boot.owned and boot.listener_pids == () and not boot.endpoint_in_tree
    assert boot.pid == 4242 and boot.start_time_unchanged
    strict = runtime.verify_ownership(require_listener=True)
    assert not strict.owned and any("nothing listens" in p for p in strict.problems)
    facts.listeners = [4243]  # the endpoint bound, inside the owned tree
    bound = runtime.verify_ownership(require_listener=True)
    assert bound.owned and bound.endpoint_in_tree


def test_t33_a_listener_outside_the_owned_tree_refuses_in_every_mode(profile):
    runtime, _, _ = started_runtime(profile, facts=FakeFacts(listeners=(9999,)))
    for mode in (False, True):
        facts = runtime.verify_ownership(require_listener=mode)
        assert not facts.owned and not facts.endpoint_in_tree
        assert any("outside the owned tree" in p for p in facts.problems)


def test_t33_the_boot_window_still_fails_fast_when_the_root_exits_or_the_manager_disowns(profile):
    runtime, _, facts = started_runtime(profile, facts=FakeFacts(listeners=()))
    facts.alive.clear()
    gone = runtime.verify_ownership(require_listener=False)
    assert not gone.owned and any("does not exist" in p for p in gone.problems)
    disowned, _, _ = started_runtime(profile, owns=False, facts=FakeFacts(listeners=()))
    assert not disowned.verify_ownership(require_listener=False).owned


def test_t34_after_the_root_is_gone_the_tree_is_empty_so_process_memory_is_not_applicable(profile):
    from tools.qualification.img154b import sampler as sp

    runtime, _, facts = started_runtime(profile)
    assert runtime.verify_ownership().tree == (4242, 4243)
    facts.alive.clear()  # the owned stop removed the tree
    after = runtime.verify_ownership()
    assert (
        after.tree == ()
    )  # a stale single-pid tree would read as "missing" memory for the whole settle interval
    provider = sp.ProcessTreeProvider(
        lambda: runtime.verify_ownership().tree, reader=lambda pid: None
    )
    assert set(provider.read().status.values()) == {"not_applicable"}
