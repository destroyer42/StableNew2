# PR-CLEAN-01 – File Access Logger (V2.5) – 2025-11-26

## Summary
Introduce a V2.5 file-access logging system into StableNew to trace every file accessed during runtime, enabling full clean-up of V1 vs V2 code and formalizing the migration path.

## Objectives
- Add a dedicated File Access Logger module.
- Monkeypatch `open`, `Path.open`, and `importlib.import_module` when enabled.
- Controlled by env var `STABLENEW_FILE_ACCESS_LOG=1`.
- Write logs as JSONL into `logs/file_access/`.
- No changes to default app behavior unless env flag enabled.

## Files Added (V2.5)
- `src/utils/file_access_log_v2.5_2025-11-26.py`

## Files Modified
- `src/main.py` – Add logger initialization + monkeypatch installer.

## Detailed Diff Instructions (for Codex)
### 1. Create new module
**Path:** `src/utils/file_access_log_v2.5_2025-11-26.py`

```python
# (full module content as provided previously)
```

### 2. Modify `src/main.py`
Insert imports:
```python
import builtins
import importlib
import traceback
from pathlib import Path
from src.utils.file_access_log_v2.5_2025-11-26 import FileAccessLogger
```

Insert logger initialization in `main()`:
```python
file_access_logger = None
if os.environ.get("STABLENEW_FILE_ACCESS_LOG") == "1":
    logs_dir = Path("logs") / "file_access"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"file_access-{int(time.time())}.jsonl"
    file_access_logger = FileAccessLogger(log_path)
    _install_file_access_hooks(file_access_logger)
```

Add `_install_file_access_hooks(...)` in same file:
```python
def _install_file_access_hooks(logger: FileAccessLogger) -> None:
    # wrap builtins.open
    # wrap Path.open
    # wrap importlib.import_module
```

## Acceptance Criteria
- Logger disabled unless env var set.
- When enabled, unique file accesses recorded.
- No regressions launching main GUI.
- Log file created under `logs/file_access/`.

## Deployment
After Codex applies the PR, run:
```
set STABLENEW_FILE_ACCESS_LOG=1
python -m src.main
```
Exercise GUI to generate the live-file usage map.
