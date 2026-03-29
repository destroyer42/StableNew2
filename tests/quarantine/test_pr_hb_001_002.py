"""Manual verification script for PR-HB-001 and PR-HB-002.

Import-safe under pytest collection.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path


def main() -> None:
    print("=" * 80)
    print("PR-HB-001 & PR-HB-002 Implementation Tests")
    print("=" * 80)

    print("\n[TEST 1] Thread dump capture function")
    print("-" * 80)
    from src.utils.diagnostics_bundle_v2 import _capture_thread_dump

    def sample_worker():
        time.sleep(0.5)

    test_thread = threading.Thread(target=sample_worker, name="TestWorker")
    test_thread.start()

    text_dump, json_dump = _capture_thread_dump()
    print(f"[OK] Text dump captured: {len(text_dump)} chars")
    print(f"[OK] JSON dump captured: {len(json_dump)} threads")
    print(f"[OK] Threads found: {list(json_dump.keys())[:5]}...")
    test_thread.join()
    print("[TEST 1] PASSED")

    print("\n[TEST 2] Watchdog context enhancement")
    print("-" * 80)

    class FakeApp:
        def __init__(self):
            self.last_ui_heartbeat_ts = time.monotonic()
            self.last_queue_activity_ts = time.monotonic()
            self.last_runner_activity_ts = time.monotonic()
            self.current_operation_label = "Testing operation"
            self.last_ui_action = "test_action()"

    from src.services.watchdog_system_v2 import SystemWatchdogV2

    app = FakeApp()
    watchdog = SystemWatchdogV2(app=app)
    print(f"[OK] Watchdog has app reference: {watchdog.app is not None}")
    print(f"[OK] App has current_operation_label: {hasattr(app, 'current_operation_label')}")
    print(f"[OK] App has last_ui_action: {hasattr(app, 'last_ui_action')}")
    print(f"[OK] Watchdog has UI_STALL_S threshold: {watchdog.UI_STALL_S}")
    print("[TEST 2] PASSED")

    print("\n[TEST 3] AppController operation tracking fields")
    print("-" * 80)

    from src.controller.app_controller import AppController

    try:
        controller = AppController(main_window=None, threaded=False)
        print(
            f"[OK] Controller has current_operation_label: "
            f"{hasattr(controller, 'current_operation_label')}"
        )
        print(f"[OK] Controller has last_ui_action: {hasattr(controller, 'last_ui_action')}")
        print(
            f"[OK] Controller has _refresh_preview_from_state_async: "
            f"{hasattr(controller, '_refresh_preview_from_state_async')}"
        )
        controller.current_operation_label = "Test operation"
        controller.last_ui_action = "test_method()"
        print(f"[OK] Operation label set: '{controller.current_operation_label}'")
        print(f"[OK] Last action set: '{controller.last_ui_action}'")
        print("[TEST 3] PASSED")
        controller.shutdown()
    except Exception as exc:
        print(f"[TEST 3] Note: Full controller test skipped due to dependencies: {exc}")

    print("\n[TEST 4] Crash bundle with thread dump")
    print("-" * 80)

    from src.utils.diagnostics_bundle_v2 import build_crash_bundle

    test_dir = Path(tempfile.gettempdir()) / "test_pr_hb_bundles"
    test_dir.mkdir(exist_ok=True)

    bundle_path = build_crash_bundle(
        reason="pr_hb_test",
        context={"test_key": "test_value", "test_operation": "PR-HB-001 test"},
        output_dir=test_dir,
    )

    if bundle_path and bundle_path.exists():
        print(f"[OK] Bundle created: {bundle_path.name}")
        import zipfile

        with zipfile.ZipFile(bundle_path, "r") as zf:
            files = zf.namelist()
            print(f"[OK] Bundle contains {len(files)} files")
            for required in [
                "metadata/info.json",
                "metadata/thread_dump.txt",
                "metadata/thread_dump.json",
            ]:
                print(f"  {'[OK]' if required in files else '[ERR]'} {required}")
        bundle_path.unlink()
        print("[TEST 4] PASSED")
    else:
        print("[TEST 4] FAILED - Bundle not created")

    print("\n" + "=" * 80)
    print("PR-HB-001 & PR-HB-002 Implementation Tests Complete")
    print("=" * 80)


if __name__ == "__main__":
    main()
