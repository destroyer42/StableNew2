from __future__ import annotations

import json
import zipfile
from pathlib import Path

from src.utils.diagnostics_bundle_v2 import build_crash_bundle


def test_pressure_reason_bundle_includes_process_state_webui_tail_and_gpu(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.utils.diagnostics_bundle_v2._collect_process_inspector_lines",
        lambda: ["pid=1 StableNew"],
    )
    monkeypatch.setattr(
        "src.utils.diagnostics_bundle_v2.collect_gpu_snapshot",
        lambda: {"provider": "nvidia-smi", "devices": [{"index": 0, "memory_used_mb": 1000}]},
    )

    class _Manager:
        def get_recent_output_tail(self, max_lines: int = 200):  # noqa: ARG002
            return {"stdout_tail": "webui tail", "stderr_tail": "", "launch_profile": "sdxl_guarded"}

    monkeypatch.setattr(
        "src.utils.diagnostics_bundle_v2.get_global_webui_process_manager",
        lambda: _Manager(),
    )

    bundle = build_crash_bundle(
        reason="ui_heartbeat_stall",
        output_dir=tmp_path,
    )

    assert bundle is not None
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "metadata/process_inspector.txt" in names
        assert "runtime/webui_tail.json" in names
        assert "metadata/gpu_snapshot.json" in names
        info = json.loads(zf.read("metadata/info.json"))
        assert info["bundle_features"]["include_process_state"] is True
        assert info["bundle_features"]["include_webui_tail"] is True
