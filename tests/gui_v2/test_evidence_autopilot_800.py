"""Real Tk model selection, offline planning, default checks and inert Learning draft actions."""

import copy
import time
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.assets.registry import AssetRegistrySnapshot
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.gui.views.model_evidence_window import ModelEvidenceWindow
from src.learning.experiment_store import LearningExperimentStore
from tests.learning_v2.test_evidence_autopilot_800 import context as context_fixture
from tests.learning_v2.test_profile_publication_660 import make_publication


def pump(root, window):
    deadline = time.monotonic() + 5
    while window._busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not window._busy, window.status.get()


@pytest.fixture
def ui(tk_root, tmp_path, monkeypatch):
    context = context_fixture.__wrapped__(tmp_path)
    resolver = make_publication(tmp_path).resolver
    monkeypatch.setattr("src.generation_profiles.identity.ModelIdentityResolver", lambda: resolver)
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.AssetRegistry",
        lambda: SimpleNamespace(cached_snapshot=lambda: AssetRegistrySnapshot(())),
    )
    monkeypatch.setattr(
        "src.gui.views.model_evidence_window.load_operator_catalog", lambda: context.catalog
    )
    owner = ttk.Frame(tk_root)
    controller = LearningController(LearningState())
    controller.authoring_baseline = lambda: copy.deepcopy(context.baseline)
    controller.app_state = SimpleNamespace(resources=copy.deepcopy(context.resources))
    owner.learning_controller = controller
    owner.experiment_store = LearningExperimentStore(tmp_path / "experiments")
    owner._on_open_experiment_library = Mock()
    owner._restore_from_store_payload = Mock(return_value=True)
    window = ModelEvidenceWindow(owner)
    window._resolver = lambda: resolver
    window.census = {
        "assets": [
            {
                "kind": "checkpoint",
                "relative": "test.safetensors",
                "family": "sdxl",
                "identity_status": "pending",
                "size": 1,
                "header": {},
            }
        ]
    }
    window._render_assets()
    window.tree.selection_set("0")
    # Do not depend on platform-specific Treeview event scheduling for the routing test.
    window._selected_model_changed()
    pump(tk_root, window)
    yield SimpleNamespace(root=tk_root, owner=owner, window=window, context=context)
    window._close()
    owner.destroy()


def test_discovery_needs_no_prompt_or_lookup_and_maintenance_is_secondary(ui, monkeypatch):
    window = ui.window
    monkeypatch.setattr(
        window,
        "_choose_qualification_prompt",
        Mock(side_effect=AssertionError("Discovery must not prompt")),
    )
    monkeypatch.setattr(
        window._lookup,
        "refresh",
        Mock(side_effect=AssertionError("Discovery must not use network")),
    )
    window._plan()
    pump(ui.root, window)
    dialog = window._proposal_dialog
    assert window.proposed_button.cget("text") == "Proposed Experiments (2)"
    assert len(dialog.selection_ids()) == 2
    assert "24 images" in dialog.status.get()
    ui.root.update_idletasks()
    assert dialog.winfo_width() <= dialog.winfo_screenwidth()
    assert dialog.winfo_height() <= dialog.winfo_screenheight() - 50
    for button in (dialog.save_button, dialog.preview_button, dialog.queue_button):
        assert button.winfo_ismapped()
        assert (
            button.winfo_rooty() + button.winfo_height()
            <= dialog.winfo_rooty() + dialog.winfo_height()
        )
    checked = dialog.selection_ids()[0]
    dialog.tree.selection_set(checked)
    # A key event requires real focus, which a parallel Tk census can move.
    dialog.tree.focus_force()
    ui.root.update()
    assert dialog.tree.focus_get() is dialog.tree
    dialog.tree.event_generate("<space>")
    ui.root.update()
    assert checked not in dialog.selection_ids()
    dialog._toggle()
    blocked = next(p for p in dialog.plan.proposals if not p.runnable)
    dialog.tree.selection_set(blocked.proposal_id)
    before = dialog.selection_ids()
    dialog._toggle()
    assert dialog.selection_ids() == before
    dialog._describe()
    assert "Evidence:" in dialog.details.get("1.0", "end")
    labels = [
        window.evidence_menu.entrycget(i, "label")
        for i in range(window.evidence_menu.index("end") + 1)
    ]
    assert any("Hugging Face" in label for label in labels)
    assert any("Import" in label for label in labels)
    assert not window._details_host.winfo_manager()


def test_queue_to_learning_persists_drafts_only_and_preserves_active_state(ui):
    window = ui.window
    window._plan()
    pump(ui.root, window)
    previous = ui.owner.learning_controller.learning_state.to_dict()
    window._save_selected(window._proposal_dialog, queue_to_learning=True)
    pump(ui.root, window)
    assert len(ui.owner.experiment_store.list_handles()) == 2
    assert ui.owner.learning_controller.learning_state.to_dict() == previous
    ui.owner._on_open_experiment_library.assert_called_once()
    assert "No jobs admitted" in window.status.get()
    assert ui.owner.learning_controller.execution_controller is None


def test_preview_chooses_one_context_only_after_click_and_admits_nothing(ui, monkeypatch):
    window = ui.window
    window._plan()
    pump(ui.root, window)
    choose = Mock(return_value=("a lighthouse at dusk", "blurry", {"prompt_source": "custom"}))
    monkeypatch.setattr("src.gui.views.model_evidence_window.choose_prompt_context", choose)
    dialog = window._proposal_dialog
    window._preview_selected(dialog)
    pump(ui.root, window)
    assert choose.call_count == 1
    assert "canonical Learning Previews compiled" in dialog.status.get()
    assert ui.owner.experiment_store.list_handles() == []


def test_changed_selection_invalidates_open_findings_and_discards_old_worker(ui):
    window = ui.window
    window._plan()
    pump(ui.root, window)
    dialog = window._proposal_dialog
    generation = window._generation
    window.tree.selection_remove(*window.tree.selection())
    window._selected_model_changed()
    assert window._generation > generation
    assert not dialog.selection_ids()
    assert str(dialog.preview_button.cget("state")) == "disabled"
    assert window.proposal_plan is None
    assert not window.proposals
    assert ui.owner.experiment_store.list_handles() == []
    assert ui.owner.learning_controller.learning_state.current_experiment is None


def test_resource_drift_disables_stale_actions_without_creating_drafts(ui):
    window = ui.window
    window._plan()
    pump(ui.root, window)
    dialog = window._proposal_dialog
    ui.owner.learning_controller.app_state.resources["samplers"].append("new sampler")
    window._save_selected(dialog, queue_to_learning=False)
    pump(ui.root, window)
    assert "stale" in window.status.get().lower()
    assert str(dialog.save_button.cget("state")) == "disabled"
    assert not dialog.selection_ids()
    assert ui.owner.experiment_store.list_handles() == []
