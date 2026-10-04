"""Explicit passive runtime capture. No Torch import, CUDA initialization or process ownership."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .provenance import git_read

_PYTHON_PROBE = """
import ast, importlib.metadata as md, json, platform, sys
packages = {}
for installed in md.distributions():
    name = installed.metadata.get('Name')
    if name: packages[name.lower().replace('_','-')] = installed.version
cuda = None
try:
    p = md.distribution('torch').locate_file('torch/version.py')
    for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t,ast.Name) and t.id=='cuda' for t in targets): cuda = ast.literal_eval(node.value)
except (OSError, ValueError, md.PackageNotFoundError): pass
print(json.dumps({'python':sys.version, 'executable':sys.executable, 'environment_prefix':sys.prefix,
                 'platform':platform.platform(),'packages':packages,'torch_cuda':cuda}))
"""


def capture_runtime(
    *, python: Path, forge_root: Path, adetailer_root: Path, launch_command: list[str],
    process_evidence: dict[str, Any], run_command: Any = subprocess.check_output,
) -> dict[str, Any]:
    runtime = json.loads(run_command([str(python), "-I", "-B", "-c", _PYTHON_PROBE], text=True))
    try:
        gpu = run_command(["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total",
                           "--format=csv,noheader"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        gpu = "unavailable"
    return {**runtime, "gpu_observation": gpu, "forge_sha": git_read(forge_root, "rev-parse", "HEAD"),
            "adetailer_sha": git_read(adetailer_root, "rev-parse", "HEAD"),
            "launch_command": list(launch_command), "process_evidence": dict(process_evidence),
            "ownership_note": "PID observation confers no ownership; no process is adopted"}
