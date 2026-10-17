"""Thread and layering rules as ratchets (audit P1-5b): existing violations may shrink, never grow."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import run_architecture_ratchets as arch  # noqa: E402


def test_a_daemon_thread_is_counted_whether_it_is_a_raw_thread_or_a_registry_spawn() -> None:
    source = (
        "import threading\n"
        "from src.utils.thread_registry import get_thread_registry\n"
        "t = threading.Thread(target=f, daemon=True)\n"
        "get_thread_registry().spawn(target=f, name='x', daemon=True)\n"
        "ok = threading.Thread(target=f)\n"
    )
    counts = arch.scan_source("src/services/x.py", source)
    assert counts == {"daemon_threads": 2, "raw_threads": 2}


def test_the_thread_registry_itself_may_create_threads() -> None:
    assert (
        arch.scan_source(
            arch.THREAD_REGISTRY_FILE, "import threading\nthreading.Thread(target=f)\n"
        )
        == {}
    )


def test_a_bare_thread_name_imported_from_threading_is_also_a_raw_thread() -> None:
    assert arch.scan_source(
        "src/services/x.py", "from threading import Thread\nThread(target=f)\n"
    ) == {"raw_threads": 1}


def test_utils_importing_a_higher_layer_is_counted_in_every_import_form() -> None:
    source = (
        "from src.controller.job_service import JobService\n"
        "import src.pipeline.executor\n"
        "from src import queue\n"
        "from src.utils.logger import get_logger\n"  # same layer: fine
        "def late():\n"
        "    from src.api.client import SDWebUIClient\n"  # a function-level import is still a dependency
    )
    assert arch.scan_source("src/utils/x.py", source) == {"utils_upward_imports": 4}


def test_other_packages_are_not_subject_to_the_utils_rule() -> None:
    assert (
        arch.scan_source("src/pipeline/x.py", "from src.controller.job_service import JobService\n")
        == {}
    )


def test_a_controller_importing_the_gui_package_is_counted() -> None:
    source = "from src.gui.klein_lora_selection_dialog import open_dialog\nfrom src import gui\nfrom src.pipeline import x\n"
    assert arch.scan_source("src/controller/x.py", source) == {"controller_gui_imports": 2}


def test_an_unparseable_file_is_skipped_not_fatal() -> None:
    assert arch.scan_source("src/x.py", "def (:\n") == {}


def test_more_than_the_baseline_is_a_regression_and_an_improvement_must_be_locked_in() -> None:
    problems = arch.compare(
        {"src/a.py": {"daemon_threads": 2}, "src/b.py": {"raw_threads": 1}},
        {"src/a.py": {"daemon_threads": 1}, "src/b.py": {"raw_threads": 3}},
    )
    assert any(p.startswith("daemon_threads REGRESSION: src/a.py") for p in problems)
    assert any(p.startswith("raw_threads IMPROVED: src/b.py") and "--update" in p for p in problems)


def test_a_new_violation_in_a_clean_file_is_a_regression() -> None:
    assert arch.compare({"src/new.py": {"controller_gui_imports": 1}}, {})[0].startswith(
        "controller_gui_imports REGRESSION"
    )


def test_the_checked_in_baseline_is_current_well_formed_and_refers_to_real_files() -> None:
    baseline = arch.load_baseline()
    assert baseline and all((ROOT / path).is_file() for path in baseline)
    assert all(n > 0 for per in baseline.values() for n in per.values())
    assert arch.compare(arch.collect(), baseline) == []  # the repository satisfies its own ratchet


def test_end_to_end_a_new_daemon_thread_in_a_clean_module_fails_the_real_check() -> None:
    probe = ROOT / "src" / "_p1_5b_probe_thread.py"
    probe.write_text(
        "import threading\nthreading.Thread(target=print, daemon=True).start()\n", encoding="utf-8"
    )
    try:
        problems = arch.compare(arch.collect(), arch.load_baseline())
        joined = "\n".join(problems)
        assert "daemon_threads REGRESSION: src/_p1_5b_probe_thread.py" in joined
        assert "raw_threads REGRESSION: src/_p1_5b_probe_thread.py" in joined
    finally:
        probe.unlink()


def test_the_ratchet_is_wired_into_the_local_gate_and_the_required_ci_job() -> None:
    assert "run_architecture_ratchets.py" in (ROOT / "tools" / "ci" / "run_pr_gate.py").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    required = workflow[workflow.index("  required:") : workflow.index("  full-suite-shard:")]
    assert (
        "python tools/ci/run_architecture_ratchets.py" in required
        and "cheap_path != 'true'" in required
    )


def test_the_broken_precommit_scripts_and_the_second_formatter_are_gone() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "check_daemon_threads" not in config and "check_thread_registry_usage" not in config
    assert "psf/black" not in config  # ruff-format is the one formatter
    assert not (ROOT / "scripts" / "check_daemon_threads.py").exists()
    assert not (ROOT / "scripts" / "check_thread_registry_usage.py").exists()
