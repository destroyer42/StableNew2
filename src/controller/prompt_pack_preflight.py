"""Wire fresh PromptPack preflight to the existing GUI dispatcher, never the runner."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any

from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.prompting.pack_lora_selection import KleinSelectionError


class SelectionReviewBridge:
    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self._lock = threading.Lock()

    def _token(self) -> str:
        state = self.controller._app_state
        return repr(
            (
                getattr(state, "job_draft", None),
                getattr(state, "current_config", None),
                getattr(state, "run_config", None),
                getattr(state, "intent_config", None),
                getattr(state, "content_visibility_mode", None),
            )
        )

    def begin(self, entries: Any) -> Any:
        token = self._token()
        app = getattr(self.controller, "_app_controller", None)
        deadline = time.monotonic() + 300

        def request_key(items: Any) -> Any:
            from src.pipeline.global_prompt_policy import apply_global_prompt_policy

            # Compare the selected source request without rereading Tk global controls.
            # That policy has already been frozen by the canonical controller projection.
            return [
                replace(
                    item,
                    config_snapshot=apply_global_prompt_policy(
                        item.config_snapshot,
                        positive_enabled=False,
                        positive_text="",
                        negative_enabled=False,
                        negative_text="",
                    ),
                )
                for item in items
            ]

        source_key = request_key(entries)

        def current() -> bool:
            if app is None:
                return True
            draft = getattr(self.controller._app_state, "job_draft", None)
            current_entries = request_key(getattr(draft, "packs", ()) or ())
            return (
                not getattr(app, "_is_shutting_down", False)
                and token == self._token()
                and source_key == current_entries
                and time.monotonic() < deadline
            )

        def validate() -> None:
            if app is not None and getattr(app, "_ui_thread_id", None) == threading.get_ident():
                raise KleinSelectionError(
                    "Prepare Klein LoRA evidence with background Preview before admission"
                )
            if not current():
                raise KleinSelectionError(
                    "Klein preflight cancelled, expired or source changed; rebuild Preview"
                )

        def notify(text: str) -> None:
            if app is not None:
                app._ui_dispatch(lambda: app._append_log(text))

        def review(requests: Any) -> Any:
            if app is None or not self._lock.acquire(blocking=False):
                raise KleinSelectionError(
                    "Klein batch review requires the active GUI; another review may be in progress"
                )
            done = threading.Event()
            abandoned = threading.Event()
            result: list[Any] = []

            def review_current() -> bool:
                return not abandoned.is_set() and current()

            def show() -> None:
                try:
                    if review_current():
                        from src.gui.klein_lora_selection_dialog import review_loras

                        root = app._get_ui_root()
                        if root is None:
                            raise KleinSelectionError("Klein batch review needs an active GUI")
                        result.append(
                            review_loras(
                                root,
                                requests,
                                visible=getattr(app.app_state, "content_visibility_mode", "")
                                == "nsfw",
                                is_current=review_current,
                            )
                        )
                except Exception as exc:
                    result.append(exc)
                finally:
                    done.set()

            try:
                app._ui_dispatch(show)
                if not done.wait(max(0, deadline - time.monotonic())):
                    abandoned.set()
                    raise KleinSelectionError("Klein batch review expired; rebuild Preview")
                if not review_current() or not result or result[0] is None:
                    raise KleinSelectionError(
                        "Klein batch review cancelled or source changed; rebuild Preview"
                    )
                if isinstance(result[0], Exception):
                    raise KleinSelectionError(
                        "Klein batch review failed; rebuild Preview"
                    ) from result[0]
                return result[0]
            finally:
                self._lock.release()

        review.validate = validate  # type: ignore[attr-defined]
        review.cancelled = lambda: not current()  # type: ignore[attr-defined]
        review.notify = notify  # type: ignore[attr-defined]
        return review


def get_prompt_pack_builder(controller: Any) -> PromptPackNormalizedJobBuilder | None:
    if not controller._config_manager or not getattr(controller, "_job_builder", None):
        return None
    builder = getattr(controller, "_prompt_pack_builder", None)
    if builder is None:
        builder = PromptPackNormalizedJobBuilder(
            config_manager=controller._config_manager,
            job_builder=controller._job_builder,
            packs_dir=controller._config_manager.packs_dir,
            lora_selection_policy=True,
            selection_review=SelectionReviewBridge(controller),
        )
        controller._prompt_pack_builder = builder
    return builder
