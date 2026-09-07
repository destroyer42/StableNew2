from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

from src.pipeline.job_models_v2 import NormalizedJobRecord

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"

ALLOWED_ARCHIVE_IMPORT_PATHS: set[Path] = set()
ALLOWED_CONTROLLER_BACKEND_IMPORT_PATHS: set[Path] = {
    ROOT / "src" / "controller" / "ports" / "default_runtime_ports.py",
}

ARCHIVE_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.controller\.archive\.pipeline_config_types\s+import\b"),
    re.compile(r"\bfrom\s+src\.controller\.archive\.pipeline_config_assembler\s+import\b"),
    re.compile(r"\bimport\s+src\.controller\.archive\.pipeline_config_types\b"),
    re.compile(r"\bimport\s+src\.controller\.archive\.pipeline_config_assembler\b"),
    re.compile(r"\bfrom\s+tools\.archive_reference(?:\.[A-Za-z_][A-Za-z0-9_]*)+\s+import\b"),
    re.compile(r"\bimport\s+tools\.archive_reference(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"),
)

GUI_PIPELINE_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.pipeline\.(pipeline_runner|executor)\s+import\b"),
    re.compile(r"\bimport\s+src\.pipeline\.(pipeline_runner|executor)\b"),
)

GUI_DIRECT_RUN_PATTERNS = (
    re.compile(r"\bpipeline_runner\.run\s*\("),
    re.compile(r"\brun_njr_v2\s*\("),
)

CONTROLLER_TK_IMPORT_PATTERNS = (
    re.compile(r"\bimport\s+tkinter\b"),
    re.compile(r"\bfrom\s+tkinter\s+import\b"),
)

CONTROLLER_DIRECT_WIDGET_MUTATION_PATTERNS = (
    re.compile(r"\blog_text\.(?:insert|delete|see)\s*\("),
    re.compile(r"\bapi_status_label\.configure\s*\("),
    re.compile(r"\bstatus_label\.configure\s*\("),
)

CONTROLLER_CONCRETE_GUI_IMPORT_PATTERNS = (
    re.compile(r"^from\s+src\.gui\.(?:panels_v2|views|main_window_v2)\s+import\b", re.MULTILINE),
    re.compile(r"^import\s+src\.gui\.(?:panels_v2|views|main_window_v2)\b", re.MULTILINE),
)

CONTROLLER_RAW_THREAD_CREATION_PATTERNS = (
    re.compile(r"\bthreading\.Thread\s*\("),
    re.compile(r"\bThread\s*\("),
)

LEGACY_ADAPTER_PATTERNS = (
    re.compile(r"\blegacy_njr_adapter\b"),
    re.compile(r"\bbuild_njr_from_legacy_pipeline_config\s*\("),
)

CONTROLLER_BACKEND_IMPORT_PATTERNS = (
    re.compile(r"\bfrom\s+src\.api\.client\s+import\s+SDWebUIClient\b"),
    re.compile(r"\bfrom\s+src\.pipeline\.pipeline_runner\s+import\s+PipelineRunner\b"),
    re.compile(
        r"\bfrom\s+src\.video\.workflow_registry\s+import\s+(?:WorkflowRegistry,\s*)?build_default_workflow_registry\b"
    ),
    re.compile(r"\bfrom\s+src\.video\.workflow_registry\s+import\s+WorkflowRegistry\b"),
)

NJR_RUNTIME_MUTATION_TARGETS = (
    SRC_ROOT / "pipeline" / "job_builder_v2.py",
    SRC_ROOT / "pipeline" / "prompt_pack_job_builder.py",
    SRC_ROOT / "pipeline" / "reprocess_builder.py",
    SRC_ROOT / "pipeline" / "cli_njr_builder.py",
    SRC_ROOT / "pipeline" / "replay_engine.py",
    SRC_ROOT / "pipeline" / "pipeline_runner.py",
    SRC_ROOT / "controller" / "job_service.py",
    SRC_ROOT / "controller" / "pipeline_controller_services" / "queue_submission_service.py",
    SRC_ROOT / "controller" / "video_workflow_controller.py",
    SRC_ROOT / "gui" / "controllers" / "learning_controller.py",
    SRC_ROOT / "utils" / "snapshot_builder_v2.py",
)

FORBIDDEN_NJR_ASSIGNMENTS = {
    "status",
    "created_at",
    "created_ts",
    "completed_at",
    "error_message",
    "output_paths",
    "thumbnail_path",
    "prompt_pack_id",
    "prompt_pack_name",
    "prompt_source",
    "positive_prompt",
    "negative_prompt",
    "stage_chain",
    "input_image_paths",
    "start_stage",
    "extra_metadata",
    "learning_context",
    "continuity_link",
}


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if "archive" in path.parts or "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def _find_pattern_hits(files: list[Path], patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append(f"{rel}:{line}: {pattern.pattern}")
    return hits


def test_only_allowlisted_source_modules_import_legacy_pipeline_config_archive() -> None:
    source_files = _iter_python_files(SRC_ROOT)
    violations: list[str] = []
    for path in source_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in ARCHIVE_IMPORT_PATTERNS):
            if rel not in ALLOWED_ARCHIVE_IMPORT_PATHS:
                violations.append(str(rel))

    assert violations == [], (
        "Unexpected source imports of archive/reference modules:\n" + "\n".join(sorted(violations))
    )


def test_gui_modules_do_not_import_pipeline_runner_or_executor() -> None:
    gui_files = _iter_python_files(SRC_ROOT / "gui")
    violations = _find_pattern_hits(gui_files, GUI_PIPELINE_IMPORT_PATTERNS)
    assert violations == [], (
        "GUI modules must not import pipeline runner/executor directly:\n"
        + "\n".join(sorted(violations))
    )


def test_gui_modules_do_not_call_runner_entrypoints_directly() -> None:
    gui_files = _iter_python_files(SRC_ROOT / "gui")
    violations = _find_pattern_hits(gui_files, GUI_DIRECT_RUN_PATTERNS)
    assert violations == [], (
        "GUI modules must not invoke runner entrypoints directly:\n" + "\n".join(sorted(violations))
    )


def test_controller_modules_do_not_import_tkinter_directly() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations = _find_pattern_hits(controller_files, CONTROLLER_TK_IMPORT_PATTERNS)
    assert violations == [], "Controller modules must not import tkinter directly:\n" + "\n".join(
        sorted(violations)
    )


def test_controller_modules_do_not_mutate_widgets_directly() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations = _find_pattern_hits(controller_files, CONTROLLER_DIRECT_WIDGET_MUTATION_PATTERNS)
    assert violations == [], (
        "Controller modules must not mutate Tk widgets directly:\n" + "\n".join(sorted(violations))
    )


def test_controller_modules_do_not_import_concrete_gui_views_panels_or_dialogs() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations = _find_pattern_hits(controller_files, CONTROLLER_CONCRETE_GUI_IMPORT_PATTERNS)
    assert violations == [], (
        "Controller modules must not import concrete GUI views/panels/dialogs directly:\n"
        + "\n".join(sorted(violations))
    )


def test_app_and_pipeline_controllers_do_not_spawn_raw_threads_directly() -> None:
    target_files = [
        SRC_ROOT / "controller" / "app_controller.py",
        SRC_ROOT / "controller" / "pipeline_controller.py",
    ]
    violations = _find_pattern_hits(target_files, CONTROLLER_RAW_THREAD_CREATION_PATTERNS)
    assert violations == [], (
        "AppController/PipelineController must route background work through coordinators or tracked-thread helpers:\n"
        + "\n".join(sorted(violations))
    )


def test_controller_modules_only_use_backend_runtime_imports_via_ports_layer() -> None:
    controller_files = _iter_python_files(SRC_ROOT / "controller")
    violations: list[str] = []
    for path in controller_files:
        text = path.read_text(encoding="utf-8")
        if not any(pattern.search(text) for pattern in CONTROLLER_BACKEND_IMPORT_PATTERNS):
            continue
        if path in ALLOWED_CONTROLLER_BACKEND_IMPORT_PATHS:
            continue
        violations.append(str(path.relative_to(ROOT)))

    assert violations == [], (
        "Controller backend/runtime imports must stay behind controller ports:\n"
        + "\n".join(sorted(violations))
    )


def test_source_does_not_reference_legacy_njr_adapter_outside_legacy_module() -> None:
    source_files = _iter_python_files(SRC_ROOT)
    violations: list[str] = []
    for path in source_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for pattern in LEGACY_ADAPTER_PATTERNS:
            if pattern.search(text):
                violations.append(str(rel))
                break

    assert violations == [], (
        "Legacy NJR adapter must remain isolated to its own module:\n"
        + "\n".join(sorted(violations))
    )


def test_legacy_njr_adapter_module_is_deleted() -> None:
    assert not (ROOT / "src" / "pipeline" / "legacy_njr_adapter.py").exists()


def test_njr_contract_has_exactly_eight_authorized_work_fields() -> None:
    assert tuple(field.name for field in fields(NormalizedJobRecord)) == (
        "schema_version",
        "job_id",
        "workload_kind",
        "source",
        "workload",
        "stages",
        "output_plan",
        "provenance",
    )
    assert NormalizedJobRecord.__dataclass_params__.frozen is True


def test_njr_builders_services_and_runner_do_not_mutate_records() -> None:
    violations: list[str] = []
    for path in NJR_RUNTIME_MUTATION_TARGETS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                raw_targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                targets.extend(raw_targets)
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if not isinstance(target.value, ast.Name):
                    continue
                if target.value.id not in {"njr", "record", "normalized_job"}:
                    continue
                if target.attr not in FORBIDDEN_NJR_ASSIGNMENTS:
                    continue
                violations.append(
                    f"{path.relative_to(ROOT)}:{target.lineno}: {target.value.id}.{target.attr}"
                )

    assert violations == [], "NJR mutation is forbidden:\n" + "\n".join(violations)
