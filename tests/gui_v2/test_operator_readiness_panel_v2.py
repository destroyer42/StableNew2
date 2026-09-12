from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.gui.main_window_v2 import MainWindowV2
from src.gui.panels_v2.operator_readiness_panel_v2 import (
    OperatorReadinessPanelV2,
    format_product_support_label,
    is_intro_dismissed,
    persist_intro_dismissal,
)
from src.services.operator_readiness_service import (
    OperatorReadinessRecord,
    OperatorReadinessSnapshot,
    OperatorReadinessState,
    ProductSupportState,
    product_support_surfaces,
)
from src.services.ui_state_store import UIStateStore


@dataclass
class _FakeJobService:
    history_store: object


class _FakeSettings:
    def load_settings(self) -> dict[str, str]:
        return {"output_dir": "C:/configured/output"}


class _FakeWebUI:
    def get_state(self) -> str:
        return "ready"


def test_support_labels_follow_phase_one_policy() -> None:
    surfaces = {surface.id: surface for surface in product_support_surfaces()}

    assert MainWindowV2._support_tab_title("prompt", "Prompt") == "Prompt"
    assert MainWindowV2._support_tab_title("svd", "SVD Img2Vid") == "SVD Img2Vid"
    assert "- Adv" in format_product_support_label(
        "Learning", surfaces["learning"].state
    )
    assert "- Deferred" in format_product_support_label(
        "Future", ProductSupportState.DEFERRED
    )
    assert surfaces["prompt"].state is ProductSupportState.SUPPORTED
    assert surfaces["pipeline"].state is ProductSupportState.SUPPORTED
    assert surfaces["svd"].state is ProductSupportState.SUPPORTED


def test_intro_dismissal_merges_scoped_state_without_erasing_other_ui_state(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")
    store.save_state(
        {
            "window": {"geometry": "1200x800+10+10"},
            "tabs": {"selected_index": 2},
            "content_visibility": {"mode": "sfw"},
            "operator_readiness": {"other": "preserved"},
        }
    )

    assert not is_intro_dismissed(store)
    assert persist_intro_dismissal(store)
    saved = store.load_state()

    assert saved is not None
    assert is_intro_dismissed(store)
    assert saved["operator_readiness"] == {"other": "preserved", "intro_dismissed": True}
    assert saved["window"] == {"geometry": "1200x800+10+10"}
    assert saved["tabs"] == {"selected_index": 2}
    assert saved["content_visibility"] == {"mode": "sfw"}


def test_main_window_readiness_service_reuses_live_authorities() -> None:
    repository = object()
    webui = _FakeWebUI()
    controller = type(
        "Controller",
        (),
        {
            "job_service": _FakeJobService(repository),
            "webui_connection_controller": webui,
            "_config_manager": _FakeSettings(),
            "_packs_dir": Path("C:/user/packs"),
        },
    )()
    window = MainWindowV2.__new__(MainWindowV2)
    window.app_controller = controller

    service = window._build_operator_readiness_service()

    assert service._repository is repository
    assert service._webui_connection is webui
    assert service._prompt_pack_dir_provider() == Path("C:/user/packs")
    assert service._output_dir_provider() == Path("C:/configured/output")


class _FakeReadinessService:
    def __init__(self, snapshot: OperatorReadinessSnapshot) -> None:
        self.snapshot = snapshot
        self.collect_calls = 0
        self.source_paths: list[str | None] = []

    def collect(self, *, source_image_path: str | None = None) -> OperatorReadinessSnapshot:
        self.collect_calls += 1
        self.source_paths.append(source_image_path)
        return self.snapshot


def _snapshot() -> OperatorReadinessSnapshot:
    records = (
        OperatorReadinessRecord(
            id="ready",
            display_name="Ready record",
            state=OperatorReadinessState.READY,
            summary="Ready summary.",
            blocking_reasons=(),
            operator_actions=(),
            source="test",
        ),
        OperatorReadinessRecord(
            id="action",
            display_name="Action record",
            state=OperatorReadinessState.ACTION_REQUIRED,
            summary="Action summary.",
            blocking_reasons=("A blocker.",),
            operator_actions=("Take an action.",),
            source="test",
        ),
        OperatorReadinessRecord(
            id="optional",
            display_name="Optional record",
            state=OperatorReadinessState.OPTIONAL,
            summary="Optional summary.",
            blocking_reasons=(),
            operator_actions=("Optional action.",),
            source="test",
        ),
        OperatorReadinessRecord(
            id="unknown",
            display_name="Unknown record",
            state=OperatorReadinessState.UNKNOWN,
            summary="Unknown summary.",
            blocking_reasons=(),
            operator_actions=("Inspect diagnostics.",),
            source="test",
        ),
    )
    return OperatorReadinessSnapshot(
        support_surfaces=product_support_surfaces(),
        records=records,
    )


@pytest.mark.gui
def test_panel_renders_all_readiness_states_and_refresh_is_read_only(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    fake_service = _FakeReadinessService(_snapshot())
    store = UIStateStore(tmp_path / "ui_state.json")
    panel = OperatorReadinessPanelV2(
        tk_root,
        service=fake_service,
        source_image_path_provider=lambda: "C:/source.png",
        ui_state_store=store,
    )
    panel.pack()
    tk_root.update_idletasks()

    assert fake_service.collect_calls == 1
    assert fake_service.source_paths == ["C:/source.png"]
    assert panel.record_widgets["ready"]["badge"].cget("text") == "[Ready]"
    assert panel.record_widgets["action"]["badge"].cget("text") == "[Action required]"
    assert panel.record_widgets["optional"]["badge"].cget("text") == "[Optional]"
    assert panel.record_widgets["unknown"]["badge"].cget("text") == "[Unknown]"
    assert "A blocker." in panel.record_widgets["action"]["detail"].cget("text")
    assert panel.intro_frame.winfo_manager() == "grid"

    panel.dismiss_intro_var.set(True)
    panel._dismiss_intro_if_selected()
    assert is_intro_dismissed(store)
    assert panel.intro_frame.winfo_manager() == ""
    panel._show_intro()
    assert panel.intro_frame.winfo_manager() == "grid"

    panel.refresh()
    assert fake_service.collect_calls == 2
    assert store.load_state()["operator_readiness"] == {"intro_dismissed": True}
