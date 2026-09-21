"""Tk-backed coverage for the semantic operator driver and the fake-backend journey.

These tests need a Tk display and follow the repository's Tk skip policy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

from tools.operator_journey.tk_driver import TkDriver, WidgetNotFound

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.journey


@pytest.fixture
def root():
    try:
        instance = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - environment specific
        pytest.skip(f"Tk unavailable: {exc}")
    instance.withdraw()
    yield instance
    instance.destroy()


def test_driver_operates_real_widgets_and_fires_their_own_callbacks(root: tk.Tk) -> None:
    fired: list[str] = []
    notebook = ttk.Notebook(root)
    for title in ("Prompt", "Learning - Adv"):
        notebook.add(ttk.Frame(notebook), text=title)
    notebook.pack()
    notebook.bind("<<NotebookTabChanged>>", lambda _e: fired.append("tab"))
    button = ttk.Button(root, text="Run Experiment", command=lambda: fired.append("run"))
    button.pack()
    combo = ttk.Combobox(root, values=["a", "b"], state="readonly")
    combo.bind("<<ComboboxSelected>>", lambda _e: fired.append("combo"))
    combo.pack()
    text = tk.Text(root)
    text.bind("<<Modified>>", lambda _e: fired.append("typed"))
    text.pack()
    disabled = ttk.Button(root, text="Nope", command=lambda: fired.append("nope"), state="disabled")
    disabled.pack()

    driver = TkDriver(root)
    driver.pump(0.2)  # Tk announces the initially selected tab once mapped
    fired.clear()
    driver.select_tab(notebook, "learning - adv")
    driver.select_combobox(combo, "b", label="combo")
    driver.type_in_text(text, "hello", label="text")
    driver.invoke(driver.find_button(root, "Run Experiment"), label="run")

    assert fired == ["tab", "combo", "typed", "run"]
    assert combo.get() == "b" and text.get("1.0", "end").strip() == "hello"
    with pytest.raises(WidgetNotFound):
        driver.invoke(disabled, label="disabled")
    with pytest.raises(WidgetNotFound):
        driver.select_combobox(combo, "missing", label="combo")
    assert "nope" not in fired
    assert [entry["action"] for entry in driver.trace.entries][:2] == [
        "select_tab",
        "select_combobox",
    ]


def _tracked_state() -> str:
    return subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True)


def _require_display() -> None:
    try:
        tk.Tk().destroy()
    except tk.TclError as exc:  # pragma: no cover - environment specific
        pytest.skip(f"Tk unavailable: {exc}")


def _run_cli(tmp_path: Path, *extra: str, timeout: float = 240) -> tuple[int, dict]:
    """Run the operator command exactly as Codex would, in its own process.

    A subprocess keeps the journey on production configuration; pytest's autouse
    fixtures stub the WebUI client and enable test-mode inside this process.
    """

    _require_display()
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTEST_CURRENT_TEST", "STABLENEW_TEST_MODE", "STABLENEW_NO_WEBUI"}
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.operator_journey",
            "learning-lora-strength",
            "--backend",
            "fake",
            "--hide-window",
            "--discard-workspace",
            "--evidence-dir",
            str(tmp_path),
            *extra,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    bundle = next(tmp_path.iterdir())
    evidence = json.loads((bundle / "evidence.json").read_text(encoding="utf-8"))
    evidence["_bundle"] = str(bundle)
    return result.returncode, evidence


def test_fake_backend_journey_traverses_the_canonical_queue_path(tmp_path: Path) -> None:
    tracked_before = _tracked_state()
    code, evidence = _run_cli(tmp_path, "--stop-after", "verify_execution")
    failures = [c for c in evidence["checks"] if not c["passed"]]
    assert code == 0 and evidence["verdict"] == "PASS", (failures, evidence["failed_assertion"])
    names = {check["name"] for check in evidence["checks"]}
    assert {"single_batch_admission", "three_independent_jobs", "all_jobs_completed"} <= names
    assert evidence["summary"]["requested_seed"] == 12345
    variants = evidence["variants"]
    assert [v["job_status"] for v in variants] == ["completed"] * 3
    assert [v["selected_lora_tokens"] for v in variants] == [[], ["1.0"], ["2.0"]]
    assert all(v["actual_all_seeds"] == [12345] for v in variants)
    assert evidence["isolation_violations"] == [] and _tracked_state() == tracked_before
    assert evidence["captured_errors"] == {"gui": [], "threads": [], "logs": []}
    artifacts = Path(evidence["_bundle"]) / "artifacts"
    assert len(list(artifacts.glob("v*_image.png"))) == 3
    assert len(list(artifacts.glob("v*_manifest.json"))) == 3
    assert (Path(evidence["_bundle"]) / "summary.txt").is_file()


def test_journey_waits_for_a_slow_starting_webui(tmp_path: Path) -> None:
    """StableNew needs ~15 s to connect to WebUI; submission must wait for it."""

    code, evidence = _run_cli(tmp_path, "--stop-after", "preflight", "--fake-startup-delay", "6")
    assert code == 0 and evidence["verdict"] == "PASS", evidence["failed_assertion"]
    # WebUI answered 503 while warming up; the journey waited instead of failing.
    assert evidence["summary"]["backend_requests_rejected_while_starting"] >= 1
    assert any(e.get("label") == "header Refresh" for e in evidence["action_trace"])


def test_real_backend_code_path_against_a_loopback_backend(tmp_path: Path) -> None:
    """Exercise the --real-backend branch (probe, LoRA check, model match, idle wait)
    against a loopback double so no real A1111 is needed.

    The double has two checkpoints and the *second* is loaded; the journey must use
    that one and leave the operator's checkpoint untouched (no switch).
    """

    _require_display()
    from tools.operator_journey.fake_a1111 import FakeA1111

    with FakeA1111(
        model="alpha-model", extra_models=("zeta-model",), active_model="zeta-model"
    ) as backend:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"PYTEST_CURRENT_TEST", "STABLENEW_TEST_MODE", "STABLENEW_NO_WEBUI"}
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.operator_journey",
                "learning-lora-strength",
                "--real-backend",
                "--webui-url",
                backend.base_url,
                "--startup-grace",
                "0",
                "--hide-window",
                "--discard-workspace",
                "--stop-after",
                "verify_execution",
                "--evidence-dir",
                str(tmp_path),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
        payloads = list(backend.txt2img_payloads)
        switches, active = backend.checkpoint_switches, backend.options["sd_model_checkpoint"]
    evidence = json.loads((next(tmp_path.iterdir()) / "evidence.json").read_text("utf-8"))
    assert result.returncode == 0 and evidence["verdict"] == "PASS", evidence["failed_assertion"]
    assert evidence["backend_mode"] == "real"
    assert evidence["summary"]["backend"]["lora_count"] == 1
    assert evidence["summary"]["model"].startswith("zeta-model")  # the loaded model, not the first
    assert switches == 0 and active.startswith("zeta-model")  # operator's checkpoint untouched
    assert (
        evidence["summary"]["active_checkpoint_before"]
        == evidence["summary"]["active_checkpoint_after"]
    )
    assert len(payloads) == 3 and {p["seed"] for p in payloads} == {12345}


def test_journey_reports_fail_when_seed_readback_is_lost(tmp_path: Path) -> None:
    code, evidence = _run_cli(
        tmp_path, "--stop-after", "verify_execution", "--fake-drop-seed-readback"
    )
    assert code == 1 and evidence["verdict"] == "FAIL"
    assert any(
        c["name"].startswith("controlled_evidence") for c in evidence["checks"] if not c["passed"]
    )


def test_full_fake_journey_including_review_and_ratings(tmp_path: Path) -> None:
    code, evidence = _run_cli(tmp_path)
    assert code == 0 and evidence["verdict"] == "PASS", evidence["failed_assertion"]
    names = {check["name"] for check in evidence["checks"]}
    assert {
        "gui_rating_feedback",
        "ratings_persisted_isolated",
        "rating_lineage[0.0]",
        "rating_lineage[1.0]",
        "rating_lineage[2.0]",
        "only_lora_strength_varies",
        "conclusion_scoped_to_lora_strength",
        "gui_recommendations_only_lora_strength",
        "engine_recommends_structured_lora_value_only",
        "analytics_parameter",
        "analytics_counts",
        "analytics_best_value",
    } <= names
    assert all(check["passed"] for check in evidence["checks"])
    assert evidence["isolation_violations"] == []
    assert evidence["captured_errors"] == {"gui": [], "threads": [], "logs": []}
    records = Path(evidence["_bundle"]) / "artifacts" / "learning_records.jsonl"
    ratings = [
        json.loads(line)["metadata"]["user_rating_raw"]
        for line in records.read_text(encoding="utf-8").splitlines()
        if '"learning_experiment_rating"' in line
    ]
    assert ratings == [3, 4, 5]
