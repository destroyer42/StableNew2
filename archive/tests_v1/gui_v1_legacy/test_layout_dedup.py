"""PR-1: Layout Cleanup & Component De-duplication tests.

Verifies there is a single PipelineControlsPanel instance and that the
Randomization tab is present in the main notebook.
"""

from src.gui.main_window import StableNewGUI
from src.gui.pipeline_controls_panel import PipelineControlsPanel


def _walk_widgets(root):
    """Yield all descendant widgets starting at root."""
    stack = [root]
    while stack:
        w = stack.pop()
        yield w
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass


class TestLayoutDedup:
    def test_single_pipeline_controls_and_randomization_tab(self, tk_root):
        gui = StableNewGUI(root=tk_root)

        # Count PipelineControlsPanel instances in widget tree
        count = sum(1 for w in _walk_widgets(tk_root) if isinstance(w, PipelineControlsPanel))
        assert count == 1, f"Expected 1 PipelineControlsPanel, found {count}"

        # Verify Randomization tab exists
        nb = getattr(gui, "center_notebook", None)
        assert nb is not None, "Main notebook not found on GUI"
        titles = [nb.tab(t, "text") for t in nb.tabs()]
        assert "Randomization" in titles, f"Randomization tab missing; tabs: {titles}"
