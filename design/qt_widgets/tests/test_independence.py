"""The prototype's pure layer runs with every production runtime made unavailable.

A child interpreter (isolated mode) blocks imports of production/backend packages and makes
sockets, subprocesses and SQLite raise, then runs the whole Create + theme flow. Success proves
the design workspace needs no real backend, queue, runner, database or network.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GUARDED_FLOW = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, sys.argv[1])
    BLOCKED = {"src", "controller", "pipeline", "queue", "history", "sqlite3", "requests", "httpx", "urllib3", "torch",
               "diffusers", "tkinter", "comfy", "webbrowser", "ctypes", "psutil", "numpy", "PIL"}

    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ImportError(f"blocked production runtime: {name}")
            return None

    sys.meta_path.insert(0, Blocker())
    import os, socket, subprocess, tempfile
    from pathlib import Path

    def refuse(*args, **kwargs):
        raise RuntimeError("production runtime access attempted")

    socket.socket.connect = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    subprocess.Popen = refuse
    os.system = refuse
    if hasattr(os, "startfile"):
        os.startfile = refuse

    from stablenew_qt_proto.domain import CreateSession, PACKS
    from stablenew_qt_proto.theme import ThemeEditor, failing_checks
    from stablenew_qt_proto.theme_store import ThemeLibrary
    from stablenew_qt_proto.tokens import reference_themes

    session = CreateSession()
    session.select_source(PACKS[0].key)
    session.set_setting("batch", 2)
    session.build_preview()
    receipt = session.simulate_admission()
    assert len(receipt.tiles) == 2, receipt

    with tempfile.TemporaryDirectory() as tmp:
        library = ThemeLibrary(Path(tmp) / "themes")
        editor = ThemeEditor(reference_themes()["concept-a"])
        assert editor.set("colors", "accent", "#FFC806") and not failing_checks(editor.draft)
        saved = library.save_as(editor.draft, "Guarded")
        library.set_active(saved)
        assert ThemeLibrary(Path(tmp) / "themes").load_active() == saved

    leaked = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
    assert not leaked, leaked
    print("INDEPENDENT-OK")
    """
)


class ProductionRuntimeIndependenceTests(unittest.TestCase):
    def test_full_pure_flow_with_production_runtimes_unavailable(self):
        result = subprocess.run(
            [sys.executable, "-I", "-c", GUARDED_FLOW, str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INDEPENDENT-OK", result.stdout)

    def test_guard_really_blocks(self):
        probe = textwrap.dedent(
            """
            import sys
            class B:
                def find_spec(self, name, path=None, target=None):
                    if name == "sqlite3":
                        raise ImportError("blocked")
            sys.meta_path.insert(0, B())
            try:
                import sqlite3
            except ImportError:
                print("BLOCKED")
            """
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", probe],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertIn("BLOCKED", result.stdout)

    def test_package_sources_import_only_allowed_modules(self):
        import ast

        allowed_third_party = {"PySide6"}
        stdlib = set(sys.stdlib_module_names)
        for path in (ROOT / "stablenew_qt_proto").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else (
                        [node.module or ""]
                        if isinstance(node, ast.ImportFrom) and node.level == 0
                        else []
                    )
                )
                for name in names:
                    root = name.split(".")[0]
                    self.assertTrue(
                        root in stdlib or root in allowed_third_party, f"{path.name}: {name}"
                    )


if __name__ == "__main__":
    unittest.main()
