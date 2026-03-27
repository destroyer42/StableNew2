from __future__ import annotations

from pathlib import Path


CORE_FILES = [
    Path("src/controller/core_pipeline_controller.py"),
    Path("src/controller/pipeline_controller.py"),
    Path("src/controller/job_service.py"),
    Path("src/pipeline/executor.py"),
    Path("src/pipeline/pipeline_runner.py"),
]

FORBIDDEN_TOKENS = (
    "from src.gui.controller",
    "import src.gui.controller",
    "from src.gui.state",
    "import src.gui.state",
    "from src.gui.pipeline_panel_v2 import format_queue_job_summary",
)


def test_controller_core_path_avoids_gui_owned_imports() -> None:
    for file_path in CORE_FILES:
        assert file_path.exists(), f"Core file missing: {file_path}"
        content = file_path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            assert token not in content, f"{file_path} unexpectedly references {token}"
