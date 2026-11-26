from __future__ import annotations

import json
from pathlib import Path

from src.learning.run_metadata import write_run_metadata


def test_run_metadata_file(tmp_path: Path) -> None:
    run_id = "run-123"
    base_dir = tmp_path / "runs"
    meta_path = write_run_metadata(
        run_id,
        {"txt2img": {"steps": 10}},
        packs=[{"pack_name": "packA", "prompt": "sample"}],
        one_click_action="none",
        stage_outputs=[{"stage": "txt2img", "path": "a/b.png"}],
        base_dir=base_dir,
        async_write=False,
    )
    assert meta_path.exists()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == run_id
    assert payload["packs"] == [{"pack_name": "packA", "prompt": "sample"}]
