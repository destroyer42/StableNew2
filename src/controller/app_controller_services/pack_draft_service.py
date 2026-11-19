"""Build selected PromptPack entries through the existing Add to Job lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.contracts import PackJobEntry
from src.controller.app_controller_services.gui_config_service import PackDraftConfig
from src.pipeline.site_create_settings import Choice, apply_site_settings
from src.utils.prompt_packs import PromptPackInfo

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SitePackDraft:
    slots: tuple[int, ...]
    revision: int
    current: Callable[[], bool]
    complete: Callable[[str], None]
    previous: tuple[PackJobEntry, ...] = ()
    overrides: tuple[tuple[str, Choice], ...] = ()


def build_pack_config(
    draft_config: PackDraftConfig,
    pack_config: dict[str, Any],
    stage_flags: dict[str, bool],
    randomizer_metadata: dict[str, Any],
    *,
    overrides: tuple[tuple[str, Choice], ...] = (),
) -> dict[str, Any]:
    config_snapshot = draft_config.merge(pack_config)
    if overrides:
        config_snapshot = apply_site_settings(config_snapshot, dict(overrides))
    pipeline_section = config_snapshot["pipeline"]
    for stage in ("adetailer", "upscale", "txt2img", "img2img"):
        pipeline_section[f"{stage}_enabled"] = stage_flags.get(stage, stage == "txt2img")
    config_snapshot.setdefault("randomization_enabled", randomizer_metadata["enabled"])
    return config_snapshot


def build_pack_entries(
    pack_id: str,
    pack: PromptPackInfo,
    prompts: list[dict[str, str]],
    config_snapshot: dict[str, Any],
    stage_flags: dict[str, bool],
    randomizer_metadata: dict[str, Any],
    *,
    slots: tuple[int, ...] | None = None,
) -> list[PackJobEntry]:
    return [
        PackJobEntry(
            pack_id=pack_id,
            pack_name=pack.name,
            config_snapshot=config_snapshot,
            prompt_text=row.get("positive", "").strip(),
            negative_prompt_text=row.get("negative", "").strip(),
            stage_flags=stage_flags,
            randomizer_metadata=randomizer_metadata,
            pack_row_index=index,
        )
        for index, row in enumerate(prompts)
        if slots is None or index in slots
    ]


def prepare_pack_draft(
    app: Any,
    pack_ids: list[str],
    read_rows: Callable[[Path], list[dict[str, str]]],
    selection: SitePackDraft | None = None,
) -> None:
    """Capture working settings on the GUI thread, then load pack rows off-thread."""
    if not pack_ids:
        return

    action = f"on_pipeline_add_packs_to_job({pack_ids})"
    app.current_operation_label = f"Adding {len(pack_ids)} pack(s) to job"
    app.last_ui_action = action

    def report_failure(message: str) -> None:
        app._append_log(f"[controller] {message}")
        app._update_status(message)
        app._clear_active_operation(action)
        if selection is not None:
            selection.complete("refused")

    try:
        stage_flags = app._build_stage_flags()
        randomizer_metadata = app._build_randomizer_metadata()
        draft_config = app._capture_pack_draft_config()
    except Exception as exc:  # noqa: BLE001 - refuse the entire Add to Job action
        report_failure(f"Could not add PromptPacks. {exc}")
        return

    def worker() -> None:
        entries: list[PackJobEntry] = []
        messages: list[str] = []
        try:
            for pack_id in pack_ids:
                pack = app._find_pack_by_id(pack_id)
                if pack is None:
                    messages.append(f"Pack not found: {pack_id}")
                    continue

                try:
                    pack_config = app._config_manager.load_pack_config(pack_id)
                except Exception as exc:  # noqa: BLE001 - preserve the saved-settings path for legacy packs
                    if draft_config.stage_overrides is not None:
                        raise
                    messages.append(f"Failed to read pack config for '{pack_id}': {exc}")
                    pack_config = None

                try:
                    config_snapshot = build_pack_config(
                        draft_config,
                        pack_config or {},
                        stage_flags,
                        randomizer_metadata,
                        overrides=selection.overrides if selection else (),
                    )
                except (TypeError, ValueError, AttributeError) as exc:
                    raise ValueError(f"Could not merge settings for '{pack_id}'. {exc}") from exc

                try:
                    prompts = read_rows(pack.path)
                except Exception as exc:  # noqa: BLE001 - report the unreadable pack and continue with others
                    messages.append(f"Failed to read pack '{pack_id}': {exc}")
                    continue
                if not prompts:
                    messages.append(f"Pack '{pack_id}' has no prompts")

                if selection is not None and (
                    not selection.current() or max(selection.slots) >= len(prompts)
                ):
                    raise ValueError("Selected PromptPack slots or settings changed.")
                entries.extend(
                    build_pack_entries(
                        pack_id,
                        pack,
                        prompts,
                        config_snapshot,
                        stage_flags,
                        randomizer_metadata,
                        slots=selection.slots if selection else None,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - report worker failure on the GUI thread
            log.exception("Failed to build the PromptPack draft")
            message = f"Could not add PromptPacks. {exc}"
            app._ui_dispatch(lambda: report_failure(message))
            return

        def publish() -> None:
            for message in messages:
                app._append_log(f"[controller] {message}")
            if entries and app.app_state:
                if selection is not None and not selection.current():
                    report_failure("PromptPack selection expired or the saved pack changed.")
                    return
                if (
                    app.app_state.add_packs_to_job_draft(
                        entries,
                        **(
                            {
                                "expected_empty_revision": selection.revision,
                                "site_entries": selection.previous,
                            }
                            if selection
                            else {}
                        ),
                    )
                    is not False
                ):
                    app._append_log(f"[controller] Added {len(entries)} pack entry(s) to job draft")
                    app.generation_profiles.note_draft_built()
                    if selection is not None:
                        selection.complete("draft_added")
                else:
                    if selection is not None:
                        report_failure("The desktop draft changed before the PromptPack was added.")
                        return
                    app._append_log(
                        "[controller] Packs not added: discard the open History variation first"
                    )
                app._mark_ui_dirty(preview=True)
            elif selection is not None:
                selection.complete("refused")
            app._clear_active_operation(action)

        app._ui_dispatch(publish)

    can_dispatch = callable(getattr(getattr(app, "main_window", None), "run_in_main_thread", None))
    if app.threaded and can_dispatch:
        app._spawn_tracked_thread(target=worker, name=f"PackAdd-{len(pack_ids)}", purpose=action)
    else:
        worker()
