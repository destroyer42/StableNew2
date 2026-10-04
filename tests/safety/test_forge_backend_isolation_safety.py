"""PR-IMG-FORGE-100: Forge knowledge stays behind the backend/client/ports seams.

GUI and controllers express intent and render projections; they never build Forge payloads, name
Forge API routes/options, or choose a backend. The only controller-side mention allowed is the
runtime-ports factory that constructs the configured client.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = (
    "forge_additional_modules",
    "sd-modules",
    "ForgeWebUIClient",
    "ForgeWebUIImageBackend",
    "forge_ref_a1111_home",
)
ALLOWED = {Path("src/controller/ports/default_runtime_ports.py")}
GUARDED_DIRS = ("src/controller", "src/gui", "src/gui_v2")


def test_no_controller_or_gui_module_builds_forge_payloads_or_names_forge_routes() -> None:
    offenders: list[str] = []
    for directory in GUARDED_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            relative = path.relative_to(ROOT)
            if relative in ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            offenders.extend(f"{relative}: {name}" for name in FORBIDDEN if name in text)
    assert offenders == []


def test_generic_runner_has_no_forge_specific_dispatch_or_api_fields() -> None:
    text = (ROOT / "src/pipeline/pipeline_runner.py").read_text(encoding="utf-8")
    for token in ("forge", "Forge", "sd-modules", "forge_additional_modules"):
        assert token not in text, token
