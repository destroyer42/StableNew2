"""PR-VID-QUALITY-211: the review is a post-execution consumer, not a new execution path.

Static guards over the new modules: they import nothing that executes, queues, compiles or loads a model,
the Tk-free layers stay Tk-free, and none of them calls a submission, queue-write or lifecycle method.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REVIEW_MODULES = (
    "src/video/video_review_group.py",
    "src/video/review_preview.py",
    "src/learning/video_quality_review.py",
    "src/learning/video_review_service.py",
    "src/gui/view_contracts/video_review_contract.py",
    "src/gui/views/video_experiment_review_window.py",
)
TK_FREE = REVIEW_MODULES[:5]
FORBIDDEN_IMPORT_PREFIXES = (
    "src.pipeline.pipeline_runner",
    "src.pipeline.executor",
    "src.pipeline.stage_sequencer",
    "src.pipeline.job_builder_v2",
    "src.pipeline.reprocess_builder",
    "src.pipeline.replay_engine",
    "src.controller.job_service",
    "src.controller.app_controller",
    "src.queue.job_queue",
    "src.queue.single_node_runner",
    "src.api",
    "src.video.comfy_",
    "src.video.svd_",
    "src.video.workflow_compiler",
    "src.video.video_workflow_njr_builder",
    "src.video.video_execution_resolver",
    "src.video.video_backend_registry",
    "src.services.runtime_transition_service",
    "src.image_backends",
    "torch",
    "diffusers",
    "transformers",
    "requests",
    "httpx",
    "urllib3",
    "socket",
)
FORBIDDEN_CALLS = (
    "submit_njrs",
    "submit_job",
    "record_job_submission",
    "transition_job",
    "enqueue",
    "queue_prompt",
    "run_njr",
    "replay",
    "retry_job",
    "cancel_job",
    "unlink",
    "rmtree",
    "write_bytes",
    "write_text",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            called.add(
                target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            )
    return called


def _forbidden(name: str) -> bool:
    return any(
        name == prefix
        or name.startswith(prefix + ".")
        or (prefix.endswith("_") and name.startswith(prefix))
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_the_import_guard_itself_catches_what_it_is_meant_to():
    assert _forbidden("src.pipeline.pipeline_runner") and _forbidden("src.api.client")
    assert _forbidden("src.video.comfy_workflow_backend") and _forbidden("torch.nn")
    assert _forbidden("src.controller.job_service")
    assert not _forbidden("src.video.video_review_group") and not _forbidden(
        "src.learning.learning_record"
    )
    assert not _forbidden("src.utils.managed_process")


@pytest.mark.parametrize("relative", REVIEW_MODULES)
def test_review_modules_import_no_execution_queue_compile_network_or_model_code(relative):
    offenders = sorted(name for name in _imports(ROOT / relative) if _forbidden(name))
    assert offenders == [], f"{relative} must stay a post-execution consumer: {offenders}"


@pytest.mark.parametrize("relative", TK_FREE)
def test_the_non_widget_layers_do_not_import_tk(relative):
    imported = _imports(ROOT / relative)
    assert not {name for name in imported if name.split(".")[0] in {"tkinter", "ttk"}}
    assert "PIL.ImageTk" not in imported


@pytest.mark.parametrize("relative", REVIEW_MODULES)
def test_review_modules_never_submit_queue_replay_or_delete(relative):
    offenders = sorted(_calls(ROOT / relative) & set(FORBIDDEN_CALLS))
    assert offenders == [], f"{relative} calls {offenders}"


def test_the_only_file_the_review_service_writes_is_the_learning_evidence_through_the_writer():
    source = (ROOT / "src/learning/video_quality_review.py").read_text(encoding="utf-8")
    assert "LearningRecordWriter" in source and "append_record" in source
    assert 'open(path, "w' not in source and "atomic_write" not in source


def test_the_repository_query_is_read_only_sql():
    source = (ROOT / "src/queue/job_repository.py").read_text(encoding="utf-8")
    start = source.index("def list_experiment_sibling_entries")
    body = source[start : source.index("def _row_to_batch_candidate", start)]
    sql = " ".join(body.upper().split())
    assert "SELECT" in sql
    for verb in ("INSERT", "UPDATE ", "DELETE", "CREATE ", "DROP ", "ALTER ", "BEGIN"):
        assert verb not in sql
    assert "ROWID BETWEEN" in sql  # bounded window, never a table scan


def test_no_controller_or_ratcheted_surface_gained_review_logic():
    for relative in (
        "src/controller/video_workflow_controller.py",
        "src/controller/app_controller.py",
        "src/gui/controllers/learning_controller.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "video_quality_review" not in text and "video_review_group" not in text
