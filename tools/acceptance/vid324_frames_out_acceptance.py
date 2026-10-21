"""PR-VID-WAN-324 real acceptance: one Wan2.2 TI2V-5B job on the frames-out graph (1.3.0).

The frames-out spec is not in the built-in catalog until this run proves it, so this wrapper adds it to the
registry for this process only and then drives the PR-VID-190 acceptance harness unchanged (isolated scratch
workspace and queue, production chain ``VideoWorkflowController -> NJR -> JobService -> PipelineRunner.run_njr ->
ComfyWorkflowVideoBackend``, the operator's Comfy settings read-only, no process stopped or adopted).

    python -m tools.acceptance.vid324_frames_out_acceptance <source.png> [--dry]
"""

from __future__ import annotations

import sys

from tools.acceptance import vid190_queue_recycling_acceptance as harness

REPORTS_DIR = "reports/vid324"


def _register_frames_out_version() -> None:
    from src.video import workflow_registry
    from src.video.workflow_catalog import _build_wan22_ti2v_5b_i2v_v1_3

    builtin = workflow_registry.build_builtin_workflow_specs

    def with_frames_out() -> tuple:
        return (*builtin(), _build_wan22_ti2v_5b_i2v_v1_3())

    workflow_registry.build_builtin_workflow_specs = with_frames_out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    source = next((arg for arg in args if not arg.startswith("-")), None)
    if source is None:
        raise SystemExit(
            "usage: python -m tools.acceptance.vid324_frames_out_acceptance <source.png> [--dry]"
        )
    _register_frames_out_version()
    passthrough = [
        source,
        "--suite",
        "ti2v",
        "--only",
        "A",
        "--workflow-version",
        "1.3.0",
        "--reports-dir",
        REPORTS_DIR,
    ]
    if "--dry" in args:
        passthrough.append("--dry")
    return harness.main(passthrough)


if __name__ == "__main__":
    sys.exit(main())
