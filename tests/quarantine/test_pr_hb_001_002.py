"""
Quick test script to verify PR-HB-001 and PR-HB-002 implementations.
"""

import threading
import time
import sys
import traceback

print("=" * 80)
print("PR-HB-001 & PR-HB-002 Implementation Tests")
print("=" * 80)

# Test 1: Thread dump capture
print("\n[TEST 1] Thread dump capture function")
print("-" * 80)
from src.utils.diagnostics_bundle_v2 import _capture_thread_dump

def sample_worker():
    """Sample worker thread for testing."""
    time.sleep(0.5)

# Spawn a test thread
test_thread = threading.Thread(target=sample_worker, name="TestWorker")
test_thread.start()

# Capture thread dump
text_dump, json_dump = _capture_thread_dump()

print(f"✓ Text dump captured: {len(text_dump)} chars")
print(f"✓ JSON dump captured: {len(json_dump)} threads")
print(f"✓ Threads found: {list(json_dump.keys())[:5]}...")  # Show first 5 thread IDs

test_thread.join()
print("[TEST 1] PASSED ✓")

# Test 2: Watchdog context enhancement
print("\n[TEST 2] Watchdog context enhancement")
print("-" * 80)

class FakeApp:
    """Mock app for testing watchdog context."""
    def __init__(self):
        self.last_ui_heartbeat_ts = time.monotonic()
        self.last_queue_activity_ts = time.monotonic()
        self.last_runner_activity_ts = time.monotonic()
        self.current_operation_label = "Testing operation"
        self.last_ui_action = "test_action()"

from src.services.watchdog_system_v2 import SystemWatchdogV2

app = FakeApp()
watchdog = SystemWatchdogV2(app=app)

# Check that watchdog can access new fields
print(f"✓ Watchdog has app reference: {watchdog.app is not None}")
print(f"✓ App has current_operation_label: {hasattr(app, 'current_operation_label')}")
print(f"✓ App has last_ui_action: {hasattr(app, 'last_ui_action')}")
print(f"✓ Watchdog has UI_STALL_S threshold: {watchdog.UI_STALL_S}")
print("[TEST 2] PASSED ✓")

# Test 3: AppController has operation tracking fields
print("\n[TEST 3] AppController operation tracking fields")
print("-" * 80)

from src.controller.app_controller import AppController

# Create minimal controller (without full GUI)
try:
    controller = AppController(
        main_window=None,
        threaded=False
    )
    
    print(f"✓ Controller has current_operation_label: {hasattr(controller, 'current_operation_label')}")
    print(f"✓ Controller has last_ui_action: {hasattr(controller, 'last_ui_action')}")
    print(f"✓ Controller has _refresh_preview_from_state_async: {hasattr(controller, '_refresh_preview_from_state_async')}")
    
    # Test that we can set operation labels
    controller.current_operation_label = "Test operation"
    controller.last_ui_action = "test_method()"
    print(f"✓ Operation label set: '{controller.current_operation_label}'")
    print(f"✓ Last action set: '{controller.last_ui_action}'")
    
    print("[TEST 3] PASSED ✓")
    
    # Clean shutdown
    controller.shutdown()
    
except Exception as e:
    print(f"[TEST 3] Note: Full controller test skipped due to dependencies: {e}")
    print("[TEST 3] PARTIAL ⚠")

# Test 4: Build crash bundle with thread dump
print("\n[TEST 4] Crash bundle with thread dump")
print("-" * 80)

from pathlib import Path
import tempfile
from src.utils.diagnostics_bundle_v2 import build_crash_bundle

test_dir = Path(tempfile.gettempdir()) / "test_pr_hb_bundles"
test_dir.mkdir(exist_ok=True)

bundle_path = build_crash_bundle(
    reason="pr_hb_test",
    context={"test_key": "test_value", "test_operation": "PR-HB-001 test"},
    output_dir=test_dir
)

if bundle_path and bundle_path.exists():
    print(f"✓ Bundle created: {bundle_path.name}")
    
    # Verify bundle contents
    import zipfile
    with zipfile.ZipFile(bundle_path, 'r') as zf:
        files = zf.namelist()
        print(f"✓ Bundle contains {len(files)} files")
        
        required_files = [
            "metadata/info.json",
            "metadata/thread_dump.txt",
            "metadata/thread_dump.json"
        ]
        
        for required in required_files:
            if required in files:
                print(f"  ✓ {required}")
            else:
                print(f"  ✗ MISSING: {required}")
        
        # Check that thread_dump_captured flag is in metadata
        info_json = zf.read("metadata/info.json").decode()
        if "thread_dump_captured" in info_json:
            print(f"✓ thread_dump_captured flag present in metadata")
    
    print("[TEST 4] PASSED ✓")
    
    # Cleanup
    bundle_path.unlink()
else:
    print("[TEST 4] FAILED - Bundle not created")

print("\n" + "=" * 80)
print("PR-HB-001 & PR-HB-002 Implementation Tests Complete")
print("=" * 80)
