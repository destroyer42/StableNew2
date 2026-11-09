"""Static no-runtime-import and no-side-effect tests for prototype source."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "stablenew_qt_proto"
FORBIDDEN_IMPORT_ROOTS = {
    "src", "controller", "pipeline", "queue", "history", "tkinter", "requests", "httpx", "subprocess",
    "socket", "sqlite3", "torch", "diffusers", "comfy", "webbrowser", "ctypes",
}


class IsolationTests(unittest.TestCase):
    def test_no_forbidden_imports(self):
        for path in ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [x.name for x in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    self.assertNotIn(name.split(".")[0], FORBIDDEN_IMPORT_ROOTS, f"Forbidden import in {path}: {name}")

    def test_only_app_imports_gui_on_launch(self):
        path = ROOT / "domain.py"
        code = path.read_text(encoding="utf-8")
        self.assertNotIn("PySide6", code)
        self.assertNotIn("QApplication", code)

    def test_no_persistence_or_production_service_names(self):
        for path in ROOT.rglob("*.py"):
            if path.name == "domain.py":
                code = path.read_text(encoding="utf-8")
                for forbidden in ("JobService.submit_njrs(", "PipelineRunner.run_njr(", "open(", "connect(", "requests.get("):
                    self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
