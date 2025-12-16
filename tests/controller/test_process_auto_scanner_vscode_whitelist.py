"""Tests for ProcessAutoScannerService VS Code allowlist (PR-CORE1-D11F).

Tests that VS Code / extension worker processes are never terminated by the scanner.
"""

from __future__ import annotations

from unittest.mock import Mock
from pathlib import Path

from src.controller.process_auto_scanner_service import (
    ProcessAutoScannerConfig,
    ProcessAutoScannerService,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestProcessAutoScannerVSCodeAllowlist:
    """VS Code / extension processes should never be terminated."""

    def test_vscode_lsp_server_process_is_protected(self):
        """MyPy LSP lsp_server.py process should be recognized as VS Code-related."""
        config = ProcessAutoScannerConfig(
            idle_threshold_sec=60.0,
            memory_threshold_mb=1000.0,
            enabled=True,
        )

        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create fake VS Code MyPy LSP process
        fake_proc = Mock()
        fake_proc.pid = 99999
        fake_proc.name.return_value = "python.exe"
        fake_proc.parent.return_value = None
        fake_proc.cwd.return_value = str(REPO_ROOT / "tmp")  # repo-local (but still protected by allowlist)
        fake_proc.cmdline.return_value = [
            "C:\\Users\\rob\\.vscode\\extensions\\ms-python.mypy-type-checker-2025.2.0\\bundled\\tool\\lsp_server.py"
        ]
        fake_proc.memory_info.return_value = Mock(rss=2000 * 1024 * 1024)  # 2GB (exceeds threshold)
        fake_proc.create_time.return_value = 1.0  # Very old (exceeds idle threshold)

        # Check that _is_vscode_related returns True
        assert scanner._is_vscode_related(fake_proc) is True

    def test_vscode_debugpy_process_is_protected(self):
        """debugpy process should be recognized as VS Code-related."""
        config = ProcessAutoScannerConfig(
            idle_threshold_sec=60.0,
            memory_threshold_mb=1000.0,
            enabled=True,
        )

        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create fake debugpy process
        fake_proc = Mock()
        fake_proc.pid = 88888
        fake_proc.name.return_value = "python.exe"
        fake_proc.parent.return_value = None
        fake_proc.cwd.return_value = str(REPO_ROOT / "tmp")
        fake_proc.cmdline.return_value = [
            "python.exe",
            "-m",
            "debugpy",
            "--listen",
            "5678",
        ]
        fake_proc.memory_info.return_value = Mock(rss=500 * 1024 * 1024)
        fake_proc.create_time.return_value = 1.0

        assert scanner._is_vscode_related(fake_proc) is True

    def test_vscode_extensions_cwd_is_protected(self):
        """Process running from .vscode\\extensions directory should be protected."""
        config = ProcessAutoScannerConfig(
            idle_threshold_sec=60.0,
            memory_threshold_mb=1000.0,
            enabled=True,
        )

        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create process with .vscode\extensions in cwd
        fake_proc = Mock()
        fake_proc.pid = 77777
        fake_proc.name.return_value = "python.exe"
        fake_proc.parent.return_value = None
        fake_proc.cwd.return_value = "C:\\Users\\rob\\.vscode\\extensions\\ms-python.pylance-1.1.0\\pythonFiles"
        fake_proc.cmdline.return_value = ["python.exe", "some_script.py"]
        fake_proc.memory_info.return_value = Mock(rss=100 * 1024 * 1024)
        fake_proc.create_time.return_value = 1.0

        assert scanner._is_vscode_related(fake_proc) is True

    def test_vscode_code_exe_process_is_protected(self):
        """Code.exe (VS Code editor itself) should be protected."""
        config = ProcessAutoScannerConfig(
            idle_threshold_sec=60.0,
            memory_threshold_mb=1000.0,
            enabled=True,
        )

        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create Code.exe process
        fake_proc = Mock()
        fake_proc.pid = 66666
        fake_proc.name.return_value = "Code.exe"
        fake_proc.parent.return_value = None
        fake_proc.cwd.return_value = "C:\\Program Files\\Microsoft VS Code"
        fake_proc.cmdline.return_value = ["Code.exe"]
        fake_proc.memory_info.return_value = Mock(rss=500 * 1024 * 1024)
        fake_proc.create_time.return_value = 1.0

        assert scanner._is_vscode_related(fake_proc) is True

    def test_child_of_vscode_process_is_protected(self):
        """Child process of Code.exe should be protected."""
        config = ProcessAutoScannerConfig(
            idle_threshold_sec=60.0,
            memory_threshold_mb=1000.0,
            enabled=True,
        )

        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create child process with Code.exe parent
        fake_proc = Mock()
        fake_proc.pid = 55555
        fake_proc.name.return_value = "python.exe"
        parent_mock = Mock()
        parent_mock.name.return_value = "Code.exe"
        fake_proc.parent.return_value = parent_mock
        fake_proc.cwd.return_value = str(REPO_ROOT / "tmp")
        fake_proc.cmdline.return_value = ["python.exe", "extension_script.py"]
        fake_proc.memory_info.return_value = Mock(rss=100 * 1024 * 1024)
        fake_proc.create_time.return_value = 1.0

        assert scanner._is_vscode_related(fake_proc) is True

    def test_non_vscode_process_not_protected(self):
        """Non-VS Code process should not be automatically protected."""
        config = ProcessAutoScannerConfig(
            idle_threshold_sec=60.0,
            memory_threshold_mb=1000.0,
            enabled=True,
        )

        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create generic Python process
        fake_proc = Mock()
        fake_proc.pid = 44444
        fake_proc.name.return_value = "python.exe"
        fake_proc.parent.return_value = None
        fake_proc.cwd.return_value = str(REPO_ROOT / "tmp")
        fake_proc.cmdline.return_value = ["python.exe", "random_script.py"]
        fake_proc.memory_info.return_value = Mock(rss=100 * 1024 * 1024)
        fake_proc.create_time.return_value = 1.0

        # Should NOT be recognized as VS Code-related
        assert scanner._is_vscode_related(fake_proc) is False

    def test_vscode_check_handles_exceptions(self):
        """_is_vscode_related should gracefully handle attribute/method exceptions."""
        config = ProcessAutoScannerConfig(enabled=True)
        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Create process that raises on all method calls
        fake_proc = Mock()
        fake_proc.name.side_effect = Exception("AccessDenied")
        fake_proc.parent.side_effect = Exception("AccessDenied")
        fake_proc.cwd.side_effect = Exception("AccessDenied")
        fake_proc.cmdline.side_effect = Exception("AccessDenied")

        # Should not crash, return False (not recognized as VS Code)
        result = scanner._is_vscode_related(fake_proc)
        assert result is False

    def test_vscode_marker_slash_and_backslash_variants(self):
        """Should recognize VS Code markers with both / and \\ path separators."""
        config = ProcessAutoScannerConfig(enabled=True)
        protected_pids_fn = Mock(return_value=[])

        scanner = ProcessAutoScannerService(
            config=config,
            protected_pids=protected_pids_fn,
            start_thread=False,
        )

        # Test with forward slashes
        fake_proc1 = Mock()
        fake_proc1.name.return_value = "python.exe"
        fake_proc1.parent.return_value = None
        fake_proc1.cwd.return_value = str(REPO_ROOT)
        fake_proc1.cmdline.return_value = ["python", "C:/.vscode/extensions/ms-python.tool/script.py"]
        fake_proc1.memory_info.return_value = Mock(rss=100 * 1024 * 1024)
        fake_proc1.create_time.return_value = 1.0

        assert scanner._is_vscode_related(fake_proc1) is True

        # Test with backslashes (should also work)
        fake_proc2 = Mock()
        fake_proc2.name.return_value = "python.exe"
        fake_proc2.parent.return_value = None
        fake_proc2.cwd.return_value = str(REPO_ROOT)
        fake_proc2.cmdline.return_value = ["python", "C:\\.vscode\\extensions\\ms-python.tool\\script.py"]
        fake_proc2.memory_info.return_value = Mock(rss=100 * 1024 * 1024)
        fake_proc2.create_time.return_value = 1.0

        assert scanner._is_vscode_related(fake_proc2) is True
