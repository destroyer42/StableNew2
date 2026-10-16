from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # anchor to the repository, not the working directory

CORE_FILES = [
    ROOT / "src/controller/core_pipeline_controller.py",
    ROOT / "src/controller/pipeline_controller.py",
    ROOT / "src/controller/job_service.py",
    ROOT / "src/pipeline/executor.py",
    ROOT / "src/pipeline/pipeline_runner.py",
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
