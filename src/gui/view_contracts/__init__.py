"""Toolkit-agnostic view contracts for GUI surfaces."""

from src.gui.view_contracts.feedback_panel_contract import FeedbackPanelState, update_feedback_state
from src.gui.view_contracts.form_section_contract import FormSectionState, update_form_section
from src.gui.view_contracts.pipeline_layout_contract import (
    get_visible_stage_order,
    normalize_window_geometry,
)
from src.gui.view_contracts.prompt_editor_contract import (
    build_editor_warning_text,
    build_slot_labels,
    find_undefined_slots,
)
from src.gui.view_contracts.queue_status_contract import (
    QueueStatusState,
    resolve_queue_status_display,
    resolve_queue_status_from_label,
)
from src.gui.view_contracts.selection_list_contract import SelectionListState, update_selection_list
from src.gui.view_contracts.status_banner_contract import StatusBannerState, update_status_banner

__all__ = [
    "FeedbackPanelState",
    "FormSectionState",
    "QueueStatusState",
    "SelectionListState",
    "StatusBannerState",
    "get_visible_stage_order",
    "build_editor_warning_text",
    "build_slot_labels",
    "find_undefined_slots",
    "normalize_window_geometry",
    "resolve_queue_status_display",
    "resolve_queue_status_from_label",
    "update_feedback_state",
    "update_form_section",
    "update_selection_list",
    "update_status_banner",
]
