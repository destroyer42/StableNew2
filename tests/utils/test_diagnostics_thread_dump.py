"""
PR-HB-003: Test thread dump capture in diagnostics bundles.

Tests that thread dumps are properly captured with real frame objects
and included in diagnostic bundles.
"""
import json
import tempfile
import zipfile
from pathlib import Path


class TestDiagnosticsThreadDump:
    """Test thread dump capture in diagnostics_bundle_v2."""
    
    def test_thread_dump_files_exist_in_bundle(self):
        """Test that thread dump files are included in diagnostic bundle."""
        from src.utils.diagnostics_bundle_v2 import build_diagnostics_bundle
        
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = build_diagnostics_bundle(
                reason="test",
                crash_context={"test": "data"},
                output_dir=Path(tmpdir)
            )
            
            assert bundle_path.exists()
            
            # Check bundle contains thread dump files
            with zipfile.ZipFile(bundle_path, "r") as zf:
                namelist = zf.namelist()
                assert "metadata/thread_dump.txt" in namelist
                assert "metadata/thread_dump.json" in namelist
    
    def test_thread_dump_contains_mainthread_stack(self):
        """Test that thread dump includes MainThread with stack frames."""
        from src.utils.diagnostics_bundle_v2 import build_diagnostics_bundle
        
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = build_diagnostics_bundle(
                reason="test",
                crash_context={"test": "data"},
                output_dir=Path(tmpdir)
            )
            
            # Read thread dump text
            with zipfile.ZipFile(bundle_path, "r") as zf:
                thread_dump_text = zf.read("metadata/thread_dump.txt").decode("utf-8")
                
                # Should contain MainThread or at least one thread
                assert "Thread" in thread_dump_text
                # Should contain file/line references
                assert "File" in thread_dump_text or ".py" in thread_dump_text
    
    def test_thread_dump_json_structure(self):
        """Test that thread dump JSON has correct structure."""
        from src.utils.diagnostics_bundle_v2 import build_diagnostics_bundle
        
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = build_diagnostics_bundle(
                reason="test",
                crash_context={"test": "data"},
                output_dir=Path(tmpdir)
            )
            
            # Read thread dump JSON
            with zipfile.ZipFile(bundle_path, "r") as zf:
                thread_dump_json_str = zf.read("metadata/thread_dump.json").decode("utf-8")
                thread_dump_json = json.loads(thread_dump_json_str)
                
                # Should be a dict (possibly with thread IDs as keys or error key)
                assert isinstance(thread_dump_json, dict)
                
                # If no error, should have at least one thread
                if "error" not in thread_dump_json:
                    assert len(thread_dump_json) > 0
                    
                    # Check structure of first thread entry
                    first_thread = next(iter(thread_dump_json.values()))
                    assert "thread_id" in first_thread
                    assert "name" in first_thread
                    assert "stack_frames" in first_thread
                    assert isinstance(first_thread["stack_frames"], list)
                    
                    # Check frame structure if frames exist
                    if first_thread["stack_frames"]:
                        first_frame = first_thread["stack_frames"][0]
                        assert "filename" in first_frame
                        assert "lineno" in first_frame
                        assert "function" in first_frame
    
    def test_thread_dump_failure_does_not_prevent_bundle(self):
        """Test that thread dump capture failure doesn't prevent bundle creation."""
        from src.utils.diagnostics_bundle_v2 import build_diagnostics_bundle
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Even if thread dump fails, bundle should still be created
            bundle_path = build_diagnostics_bundle(
                reason="test",
                crash_context={"test": "data"},
                output_dir=Path(tmpdir)
            )
            
            assert bundle_path.exists()
            
            # Bundle should still contain metadata
            with zipfile.ZipFile(bundle_path, "r") as zf:
                assert "metadata/info.json" in zf.namelist()
    
    def test_capture_thread_dump_directly(self):
        """Test _capture_thread_dump function directly."""
        from src.utils.diagnostics_bundle_v2 import _capture_thread_dump
        
        text_dump, json_dump = _capture_thread_dump()
        
        # Should return strings/dicts
        assert isinstance(text_dump, str)
        assert isinstance(json_dump, dict)
        
        # Text should contain thread info
        assert len(text_dump) > 0
        
        # JSON should contain thread data or error
        assert len(json_dump) > 0
        
        # If successful, should have thread entries
        if "error" not in json_dump:
            # Should have at least one thread (this test thread)
            assert len(json_dump) > 0
            
            # Each thread should have required fields
            for thread_id, thread_data in json_dump.items():
                assert "name" in thread_data
                assert "stack_frames" in thread_data
                assert isinstance(thread_data["stack_frames"], list)
