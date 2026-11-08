"""MEC-900: the Model Evidence Catalog is usable from one window with durable, whole-library status."""

from __future__ import annotations

import os
import threading
import time
from tkinter import ttk
from types import SimpleNamespace

import pytest

from src.assets.registry import AssetKind, AssetRegistry
from src.gui.views import model_evidence_window as module
from src.gui.views.model_evidence_window import (
    ModelEvidenceWindow,
    RowAssessment,
    assess_row,
    compare_with_history,
    open_model_evidence,
)
from src.gui_v2.next_test_view import NextTestRoute
from src.learning.intelligence_contracts import WORKFLOW_IDENTITY_VERIFICATION
from src.learning.model_run_history import ModelRunSummary
from tests.assets.checkpoint_fixtures import checkpoint
from tests.assets.test_registry_linked_library_900 import _moved_library
from tests.learning_v2.test_evidence_autopilot_800 import context as context_fixture


def pump(root, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert condition()


def make_owner(tk_root, **attrs):
    owner = ttk.Frame(tk_root)
    owner._on_open_experiment_library = lambda: None
    for key, value in attrs.items():
        setattr(owner, key, value)
    return owner


def census_row(relative="models/Stable-diffusion/test.safetensors", **extra):
    return {
        "kind": "checkpoint",
        "relative": relative,
        "identity_status": "pending",
        "family": "sdxl",
        "size": 1,
        "header": {},
        **extra,
    }


def test_second_open_brings_the_same_window_forward(tk_root):
    owner = make_owner(tk_root)
    first = open_model_evidence(owner)
    first.census = {"assets": [census_row()]}
    first._render_assets()
    second = open_model_evidence(owner)
    assert second is first and len(second.tree.get_children()) == 1  # state kept, no reset
    first._close()
    third = open_model_evidence(owner)
    assert third is not first
    third._close()


def test_selecting_a_row_never_cancels_a_library_scan(tk_root):
    owner = make_owner(tk_root, learning_controller=object())
    window = ModelEvidenceWindow(owner)
    window.census = {"assets": [census_row(), census_row("models/Stable-diffusion/b.safetensors")]}
    window._render_assets()
    gate, observed = threading.Event(), []
    planned = []
    window._plan = lambda **kw: planned.append(kw)

    def scan(cancelled, _progress):
        gate.wait(3)
        observed.append(cancelled())
        return "scanned"

    finished = []
    window._work(scan, finished.append, scope=module.SCOPE_LIBRARY)
    window.tree.selection_set("0")
    window._selected_model_changed()
    assert planned == []  # deferred, not started over the scan
    gate.set()
    pump(tk_root, lambda: bool(finished))
    assert observed == [False] and finished == ["scanned"]  # the scan was not cancelled
    assert planned == [{"open_dialog": False}]  # the selection is planned once the scan finishes
    window._close()


def test_selection_work_is_still_superseded_by_a_new_selection(tk_root):
    window = ModelEvidenceWindow(make_owner(tk_root))
    gate = threading.Event()
    cancelled_seen = []

    def plan(cancelled, _progress):
        gate.wait(3)
        cancelled_seen.append(cancelled())

    window._work(plan, lambda _value: pytest.fail("a superseded result must not be delivered"))
    window._selected_model_changed()
    gate.set()
    time.sleep(0.2)
    tk_root.update()
    assert cancelled_seen == [True]
    window._close()


def test_cached_rows_show_saved_identity_once_per_real_file(tk_root, tmp_path, monkeypatch):
    webui, cache, model = _moved_library(tmp_path)
    # A second, real entry for the same file under its resolved path (as an earlier verify would add).
    registry = AssetRegistry(webui, cache_path=cache)
    registry.refresh(checkpoint_paths=[model.resolve()])
    monkeypatch.setattr(module, "AssetRegistry", lambda: AssetRegistry(webui, cache_path=cache))
    window = ModelEvidenceWindow(make_owner(tk_root))
    rows = window._checkpoint_rows()
    assert len(rows) == 1
    assert rows[0]["identity_status"] == "verified" and rows[0]["sha256"]
    assert (
        window.tree.item(window.tree.get_children()[0], "text") == "Not Working/probe.safetensors"
    )
    window._close()


def test_verify_selected_hashes_one_file_and_persists_it(tk_root, tmp_path, monkeypatch):
    webui = tmp_path / "webui"
    model = checkpoint(webui / "models" / "Stable-diffusion" / "solo.safetensors", payload=b"solo")
    cache = tmp_path / "cache.json"
    registry = AssetRegistry(webui, cache_path=cache)
    registry.refresh(kinds=[AssetKind.CHECKPOINT])
    stat = model.stat()
    os.utime(
        model, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000)
    )  # saved hash no longer applies
    assert AssetRegistry(webui, cache_path=cache).verified_sha256(model) is None
    monkeypatch.setattr(module, "AssetRegistry", lambda: AssetRegistry(webui, cache_path=cache))
    window = ModelEvidenceWindow(make_owner(tk_root))
    key = window.tree.get_children()[0]
    window.tree.selection_set(key)
    window._selected_model_changed()
    assert str(window.verify_button.cget("state")) == "normal"
    window._verify_selected()
    pump(tk_root, lambda: not window._busy)
    assert "Verified solo.safetensors" in window.status.get()
    assert AssetRegistry(webui, cache_path=cache).verified_sha256(model)
    window._close()


def test_identity_step_runs_verification_for_the_selected_checkpoint(tk_root, tmp_path):
    window = ModelEvidenceWindow(make_owner(tk_root))
    window.census = {"assets": [census_row()]}
    window._render_assets()
    window.tree.selection_set("0")
    window._paths[census_row()["relative"]] = tmp_path / "test.safetensors"
    called = []
    window._verify_selected = lambda: called.append(True)
    window._route_next(NextTestRoute(WORKFLOW_IDENTITY_VERIFICATION, "x", "guidance"), False)
    assert called == [True]
    window._paths.clear()
    window._route_next(
        NextTestRoute(WORKFLOW_IDENTITY_VERIFICATION, "x", "Press Verify Selected"), False
    )
    assert called == [True] and "Verify Selected" in window.status.get()
    window._close()


def test_rows_show_history_and_assessment_without_selection(tk_root):
    window = ModelEvidenceWindow(make_owner(tk_root))
    window.census = {
        "assets": [census_row(), census_row("models/Stable-diffusion/Not Working/bad.safetensors")]
    }
    window._assessments = {
        census_row()["relative"]: RowAssessment(
            "Verified", "sdxl", 2, "2 experiments ready: Proposed Experiments."
        ),
    }
    window._history_state = "ready"
    window._history = {
        "test": ModelRunSummary(completed=10, failed=1, last_run="2026-10-19"),
        "bad": ModelRunSummary(failed=4),
    }
    window._render_assets()
    first, second = (window.tree.item(key, "values") for key in window.tree.get_children())
    assert first[:5] == ("Verified", "sdxl", "10 ok / 1 failed", "2026-10-19", "2")
    assert second[2] == "0 ok / 4 failed" and second[-1].startswith("Never completed in past runs")
    window.tree.selection_set(window.tree.get_children()[1])
    window._paths[window._rows[window.tree.get_children()[1]]["relative"]] = object()
    window._render_details()
    details = window.details.get("1.0", "end")
    assert "PAST RUNS" in details and "Never completed" in details and "Not Working" in details
    window._sort_by("runs")
    assert window.tree.item(window.tree.get_children()[0], "text") == "test.safetensors"
    window._close()


def test_assess_row_reports_ready_experiments_and_identity_steps(tmp_path):
    context = context_fixture.__wrapped__(tmp_path)
    resolver = SimpleNamespace(resolve=lambda _name: context.target)
    verified = assess_row(
        census_row("models/Stable-diffusion/test.safetensors"),
        resolver=resolver,
        catalog=context.catalog,
        planning=(context.baseline, context.resources),
    )
    assert verified.identity == "Verified" and verified.ready and "ready" in verified.next_step
    assert any("[READY]" in line for line in verified.lines)
    unverified_target = SimpleNamespace(
        identity=SimpleNamespace(sha256=None, family="sdxl", display_name="x"),
        policy=SimpleNamespace(qualified=False, policy_id="sdxl"),
        unverified_reason="",
    )

    class Catalog:
        def coverage(self, *_a, **_kw):
            return ()

    blank = SimpleNamespace(resolve=lambda _name: unverified_target)
    pending = assess_row(census_row(), resolver=blank, catalog=Catalog(), planning=None)
    assert pending.identity == "Not verified" and "Verify Selected" in pending.next_step
    ambiguous = assess_row(
        census_row(identity_status="verified", sha256="a" * 64),
        resolver=blank,
        catalog=Catalog(),
        planning=None,
    )
    assert ambiguous.identity == "Ambiguous name" and "share this name" in ambiguous.next_step


def test_catalog_and_history_comparison_is_descriptive():
    history = ModelRunSummary(
        completed=32, settings=(("steps", (("36", 28),)), ("cfg_scale", (("8.1", 28),)))
    )
    lines = compare_with_history(
        {"steps": ("4 (exact_publisher, high)",), "cfg_scale": ("0.0 (exact_publisher, high)",)},
        history,
    )
    assert "not a recommendation" in lines[0]
    assert any("steps: catalog says 4" in line and "mostly used 36" in line for line in lines)
    assert compare_with_history({"steps": ("4",)}, ModelRunSummary(failed=2)) == []


def test_child_dialog_stays_with_the_catalog_and_returns_to_it(tk_root):
    import tkinter as tk

    window = ModelEvidenceWindow(make_owner(tk_root))
    raised = []
    window.bring_to_front = lambda: raised.append(True)
    dialog = tk.Toplevel(window)
    window._keep_in_front(dialog)
    assert str(dialog.transient()) == str(window)
    dialog.destroy()
    pump(tk_root, lambda: bool(raised))
    window._close()
