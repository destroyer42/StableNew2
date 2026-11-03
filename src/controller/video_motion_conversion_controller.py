"""Motion asset conversion on the Video Workflow controller (PR-VID-MOTION-354).

Thin delegates only: the work lives in ``ConversionWorkbench`` and the library.  Every call is an explicit operator action run
on a view-owned worker; nothing here queues a job, builds an NJR, starts a model runtime or touches the GPU.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from src.video.motion_conversion.batch import BatchRunner, scan_for_batch
from src.video.motion_conversion.ports import BatchPorts, ConversionPorts, WorkflowChoice
from src.video.motion_conversion.workbench import ConversionWorkbench
from src.video.motion_library.config import load_library_root
from src.video.motion_library.store import LibraryError
from src.video.workflow_frame_count import frame_count_policy, legal_frame_counts


class VideoMotionConversionControllerMixin:
    """Requires ``_workflow_registry`` and the Motion Library mixin on the host controller."""

    def motion_conversion_workbench(self) -> ConversionWorkbench:
        root = load_library_root()
        if not root:
            raise LibraryError(
                "Choose a Motion Library folder first; converted clips are kept beside it."
            )
        slot = self.__dict__.setdefault("_motion_conversion_slot", {})
        bench = slot.get(root)
        if bench is None:
            bench = slot[root] = ConversionWorkbench(library_root=root)
        return bench  # type: ignore[no-any-return]

    def motion_conversion_workflow(self, workflow_id: str, version: str) -> WorkflowChoice:
        registry = getattr(self, "_workflow_registry", None)
        if registry is None or not workflow_id:
            return WorkflowChoice()
        for spec in registry.list_specs_for_backend("comfy"):
            if spec.workflow_id == workflow_id and (
                not version or spec.workflow_version == version
            ):
                policy = frame_count_policy(spec)
                return WorkflowChoice(
                    workflow_id=spec.workflow_id,
                    workflow_version=spec.workflow_version,
                    display_name=str(spec.display_name),
                    spec=spec,
                    default_frames=policy["default"] if policy else 17,
                    legal_frames=tuple(legal_frame_counts(spec)),
                )
        return WorkflowChoice()

    def motion_conditioning_preview(
        self,
        video_path: str,
        video_sha256: str,
        target_size: tuple[int, int],
        cancel: threading.Event,
    ) -> Any:
        """Approximate Canny preview of an existing clip (worker-side; reads the file, writes nothing)."""

        return self.motion_conversion_workbench().conditioning_preview(
            video_path, target_size=target_size, video_sha256=video_sha256, cancel=cancel
        )

    def motion_conversion_ports(
        self, selected_workflow: Callable[[], tuple[str, str]]
    ) -> ConversionPorts:
        def bench() -> ConversionWorkbench:
            return self.motion_conversion_workbench()

        def workflow() -> WorkflowChoice:
            return self.motion_conversion_workflow(*selected_workflow())

        def plan(
            facts: Any, probe: Any, choice: WorkflowChoice, request: Any, character_state: Any
        ) -> Any:
            return bench().plan_from_request(
                facts, probe, choice.spec, dict(request), choice.default_frames, character_state
            )

        def accept(
            directory: str, name: str, tags: tuple[str, ...], terms: str, cancel: threading.Event
        ) -> Any:
            return bench().accept(
                self.motion_library(),  # type: ignore[attr-defined]
                directory,
                name=name,
                tags=tags,
                usage_terms=terms,
                cancel=cancel,
            )

        return ConversionPorts(
            remembered_blender=lambda cancel: bench().remembered_blender(cancel),
            select_blender=lambda path, cancel: bench().select_blender(path, cancel),
            describe=lambda path, cancel: bench().describe_source(path, cancel),
            probe=lambda facts, cancel: bench().probe(facts, cancel),
            convert=lambda p, preview, cancel: bench().convert(p, preview=preview, cancel=cancel),
            accept=accept,
            conditioning=lambda video, sha, source_sha, size, cancel: bench().conditioning_preview(
                video,
                target_size=size,
                video_sha256=sha,
                derivative_of_sha256=source_sha,
                cancel=cancel,
            ),
            workflow=workflow,
            check_character=lambda facts, path: bench().check_character(facts, path),
            build_plan=plan,
            last_diagnostic=lambda: bench().last_diagnostic(),
            diagnostic_text=lambda path: bench().diagnostic_text(path),
        )

    def motion_batch_ports(self, selected_workflow: Callable[[], tuple[str, str]]) -> BatchPorts:
        """Ports for Batch Convert Motion: an offline folder conversion (no job, no queue, no GPU)."""

        def bench() -> ConversionWorkbench:
            return self.motion_conversion_workbench()

        def run(
            inventory: Any,
            entries: Any,
            confirmation: Any,
            cancel: threading.Event,
            progress: Callable[[Any], None],
            include_existing: bool,
        ) -> Any:
            runner = BatchRunner(bench(), self.motion_library())  # type: ignore[attr-defined]
            return runner.run(
                inventory,
                entries,
                confirmation=confirmation,
                cancel=cancel,
                progress=progress,
                include_existing=include_existing,
            )

        return BatchPorts(
            remembered_blender=lambda cancel: bench().remembered_blender(cancel),
            scan=lambda folder, settings, cancel: scan_for_batch(
                bench(), folder, settings, cancel=cancel
            ),
            run=run,
            workflow=lambda: self.motion_conversion_workflow(*selected_workflow()),
            diagnostic_text=lambda path: bench().diagnostic_text(path),
        )


__all__ = ["VideoMotionConversionControllerMixin"]
