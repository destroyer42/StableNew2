# PR-LEARN-010: Analytics Dashboard

**Status:** DRAFT  
**Priority:** P3 (LOW)  
**Phase:** 4 (Recommendations & Analytics)  
**Depends on:** PR-LEARN-009  
**Estimated Effort:** 4-6 hours

---

## 1. Problem Statement

Users need visibility into learning trends and experiment effectiveness:

1. **No historical view** — Can't see how parameters performed across multiple experiments
2. **No trend analysis** — Can't identify patterns in successful settings
3. **No statistics summary** — Can't see aggregate data about ratings and experiments
4. **No export capability** — Can't share or archive analytics

---

## 2. Success Criteria

After this PR:
- [ ] Analytics panel shows experiment statistics
- [ ] Display rating distributions per parameter
- [ ] Show experiment history with success metrics
- [ ] Export analytics to JSON/CSV
- [ ] Integration with existing review panel

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/views/learning_analytics_panel.py` | CREATE | New analytics display panel |
| `src/gui/views/learning_review_panel.py` | MODIFY | Add analytics tab/section |
| `src/gui/controllers/learning_controller.py` | MODIFY | Add analytics data methods |
| `src/learning/learning_analytics.py` | CREATE | Analytics computation engine |
| `tests/learning_v2/test_analytics_panel.py` | CREATE | Test analytics display |
| `tests/learning_v2/test_learning_analytics.py` | CREATE | Test analytics engine |

---

## 4. Implementation Steps

### Step 1: Create Analytics Engine

**File:** `src/learning/learning_analytics.py`

```python
"""Analytics engine for learning experiments.

PR-LEARN-010: Provides statistical analysis and trend detection.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from src.learning.learning_record import LearningRecordWriter


@dataclass
class ParameterStats:
    \"\"\"Statistics for a parameter value.\"\"\"
    parameter_name: str
    value: Any
    rating_count: int
    mean_rating: float
    median_rating: float
    std_dev: float
    min_rating: int
    max_rating: int


@dataclass
class ExperimentSummary:
    \"\"\"Summary of an experiment's results.\"\"\"
    experiment_id: str
    parameter_name: str
    total_variants: int
    total_ratings: int
    best_value: Any
    best_rating: float
    worst_value: Any
    worst_rating: float
    completion_rate: float


@dataclass
class AnalyticsSummary:
    \"\"\"Complete analytics summary.\"\"\"
    total_experiments: int
    total_ratings: int
    avg_rating: float
    experiments: list[ExperimentSummary]
    parameter_stats: list[ParameterStats]


class LearningAnalytics:
    \"\"\"Compute analytics from learning records.\"\"\"

    def __init__(self, record_writer: LearningRecordWriter):
        self.record_writer = record_writer

    def get_experiment_summary(self, experiment_id: str) -> ExperimentSummary | None:
        \"\"\"Get summary statistics for a specific experiment.\"\"\"
        # Get all ratings for this experiment
        ratings = self.record_writer.get_ratings_for_experiment(experiment_id)
        if not ratings:
            return None

        # Group by parameter value
        value_ratings: dict[Any, list[int]] = {}
        for img_path, rating in ratings.items():
            # Extract parameter value from metadata (would need enhancement)
            # For now, use simplified approach
            value_ratings.setdefault(img_path, []).append(rating)

        if not value_ratings:
            return None

        # Compute statistics
        all_ratings = [r for rs in value_ratings.values() for r in rs]
        avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 0

        # Find best and worst
        value_avgs = {
            val: sum(ratings) / len(ratings)
            for val, ratings in value_ratings.items()
        }
        best_value = max(value_avgs, key=value_avgs.get, default=None)
        worst_value = min(value_avgs, key=value_avgs.get, default=None)

        return ExperimentSummary(
            experiment_id=experiment_id,
            parameter_name="",  # Would extract from metadata
            total_variants=len(value_ratings),
            total_ratings=len(all_ratings),
            best_value=best_value,
            best_rating=value_avgs.get(best_value, 0) if best_value else 0,
            worst_value=worst_value,
            worst_rating=value_avgs.get(worst_value, 0) if worst_value else 0,
            completion_rate=1.0,  # Would calculate from planned vs actual
        )

    def get_parameter_statistics(self, parameter_name: str) -> list[ParameterStats]:
        \"\"\"Get statistics for all values of a parameter across experiments.\"\"\"
        # This would aggregate across all experiments
        # For now, return empty list as stub
        return []

    def get_overall_summary(self) -> AnalyticsSummary:
        \"\"\"Get overall analytics summary.\"\"\"
        # Count total experiments (unique experiment IDs)
        all_records = self.record_writer.records
        experiment_ids = set(
            r.metadata.get("experiment_name", "")
            for r in all_records
            if r.metadata.get("experiment_name")
        )

        # Count total ratings
        total_ratings = sum(
            1 for r in all_records
            if r.metadata.get("user_rating") is not None
        )

        # Calculate average rating
        ratings = [
            r.metadata.get("user_rating", 0)
            for r in all_records
            if r.metadata.get("user_rating") is not None
        ]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        # Get summaries for each experiment
        experiment_summaries = []
        for exp_id in experiment_ids:
            summary = self.get_experiment_summary(exp_id)
            if summary:
                experiment_summaries.append(summary)

        return AnalyticsSummary(
            total_experiments=len(experiment_ids),
            total_ratings=total_ratings,
            avg_rating=avg_rating,
            experiments=experiment_summaries,
            parameter_stats=[],
        )

    def export_to_json(self, output_path: Path) -> None:
        \"\"\"Export analytics to JSON file.\"\"\"
        summary = self.get_overall_summary()
        with open(output_path, 'w') as f:
            json.dump(asdict(summary), f, indent=2, default=str)

    def export_to_csv(self, output_path: Path) -> None:
        \"\"\"Export analytics to CSV file.\"\"\"
        import csv
        summary = self.get_overall_summary()

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Experiment ID",
                "Parameter",
                "Total Variants",
                "Total Ratings",
                "Best Value",
                "Best Rating",
                "Worst Value",
                "Worst Rating",
            ])

            for exp in summary.experiments:
                writer.writerow([
                    exp.experiment_id,
                    exp.parameter_name,
                    exp.total_variants,
                    exp.total_ratings,
                    exp.best_value,
                    exp.best_rating,
                    exp.worst_value,
                    exp.worst_rating,
                ])
```

### Step 2: Create Analytics Panel

**File:** `src/gui/views/learning_analytics_panel.py`

```python
"""Analytics display panel for learning system.

PR-LEARN-010: Shows experiment statistics, trends, and summaries.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any


class LearningAnalyticsPanel(ttk.Frame):
    \"\"\"Panel displaying learning analytics and statistics.\"\"\"

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Summary section
        self.rowconfigure(1, weight=1)  # Experiments table
        self.rowconfigure(2, weight=0)  # Export section

        # Summary section
        self.summary_frame = ttk.LabelFrame(self, text="Overall Statistics", padding=5)
        self.summary_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.summary_text = tk.Text(self.summary_frame, height=6, width=40, state="disabled")
        self.summary_text.pack(fill="x")

        # Experiments table
        self.experiments_frame = ttk.LabelFrame(self, text="Experiment History", padding=5)
        self.experiments_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        # Treeview for experiments
        columns = ("Parameter", "Variants", "Ratings", "Best Value", "Best Rating")
        self.experiments_tree = ttk.Treeview(
            self.experiments_frame,
            columns=columns,
            show="tree headings",
            selectmode="browse",
        )

        for col in columns:
            self.experiments_tree.heading(col, text=col)
            self.experiments_tree.column(col, width=100)

        self.experiments_tree.pack(fill="both", expand=True)

        # Scrollbar
        scrollbar = ttk.Scrollbar(
            self.experiments_frame,
            orient="vertical",
            command=self.experiments_tree.yview,
        )
        scrollbar.pack(side="right", fill="y")
        self.experiments_tree.config(yscrollcommand=scrollbar.set)

        # Export section
        self.export_frame = ttk.LabelFrame(self, text="Export", padding=5)
        self.export_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        export_button_frame = ttk.Frame(self.export_frame)
        export_button_frame.pack(fill="x")

        ttk.Button(
            export_button_frame,
            text="Export to JSON",
            command=self._on_export_json,
        ).pack(side="left", padx=2)

        ttk.Button(
            export_button_frame,
            text="Export to CSV",
            command=self._on_export_csv,
        ).pack(side="left", padx=2)

        ttk.Button(
            export_button_frame,
            text="Refresh",
            command=self._on_refresh,
        ).pack(side="left", padx=2)

    def update_analytics(self, analytics_summary: Any) -> None:
        \"\"\"Update the display with new analytics data.\"\"\"
        # Update summary text
        self.summary_text.config(state="normal")
        self.summary_text.delete(1.0, tk.END)

        if not analytics_summary:
            self.summary_text.insert(tk.END, "No analytics data available.")
            self.summary_text.config(state="disabled")
            return

        lines = []
        lines.append(f"Total Experiments: {analytics_summary.total_experiments}\\n")
        lines.append(f"Total Ratings: {analytics_summary.total_ratings}\\n")
        lines.append(f"Average Rating: {analytics_summary.avg_rating:.2f} ⭐\\n")

        self.summary_text.insert(tk.END, "".join(lines))
        self.summary_text.config(state="disabled")

        # Update experiments tree
        self.experiments_tree.delete(*self.experiments_tree.get_children())

        for exp in analytics_summary.experiments:
            self.experiments_tree.insert(
                "",
                "end",
                text=exp.experiment_id,
                values=(
                    exp.parameter_name or "N/A",
                    exp.total_variants,
                    exp.total_ratings,
                    exp.best_value or "N/A",
                    f"{exp.best_rating:.2f}",
                ),
            )

    def _on_export_json(self) -> None:
        \"\"\"Handle JSON export button.\"\"\"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )

        if file_path and hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "export_analytics_json"):
                try:
                    controller.export_analytics_json(file_path)
                    messagebox.showinfo("Export", f"Analytics exported to {file_path}")
                except Exception as e:
                    messagebox.showerror("Export Error", str(e))

    def _on_export_csv(self) -> None:
        \"\"\"Handle CSV export button.\"\"\"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

        if file_path and hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "export_analytics_csv"):
                try:
                    controller.export_analytics_csv(file_path)
                    messagebox.showinfo("Export", f"Analytics exported to {file_path}")
                except Exception as e:
                    messagebox.showerror("Export Error", str(e))

    def _on_refresh(self) -> None:
        \"\"\"Handle refresh button.\"\"\"
        if hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "refresh_analytics"):
                controller.refresh_analytics()
```

### Step 3: Add Analytics Methods to LearningController

**File:** `src/gui/controllers/learning_controller.py`

**Add at end of file:**
```python
    def get_analytics_summary(self) -> Any | None:
        \"\"\"Get overall analytics summary.\"\"\"
        if not self._learning_record_writer:
            return None

        from src.learning.learning_analytics import LearningAnalytics

        analytics = LearningAnalytics(self._learning_record_writer)
        return analytics.get_overall_summary()

    def refresh_analytics(self) -> None:
        \"\"\"Refresh analytics display.\"\"\"
        summary = self.get_analytics_summary()
        if hasattr(self, "_analytics_panel"):
            self._analytics_panel.update_analytics(summary)

    def export_analytics_json(self, file_path: str) -> None:
        \"\"\"Export analytics to JSON file.\"\"\"
        if not self._learning_record_writer:
            raise RuntimeError("No learning record writer configured")

        from pathlib import Path
        from src.learning.learning_analytics import LearningAnalytics

        analytics = LearningAnalytics(self._learning_record_writer)
        analytics.export_to_json(Path(file_path))

    def export_analytics_csv(self, file_path: str) -> None:
        \"\"\"Export analytics to CSV file.\"\"\"
        if not self._learning_record_writer:
            raise RuntimeError("No learning record writer configured")

        from pathlib import Path
        from src.learning.learning_analytics import LearningAnalytics

        analytics = LearningAnalytics(self._learning_record_writer)
        analytics.export_to_csv(Path(file_path))
```

### Step 4: Integrate Analytics Panel into Learning Tab

**File:** `src/gui/views/learning_review_panel.py`

**Option 1: Add as a new tab in a notebook**
**Option 2: Add as collapsible section**

For simplicity, we'll add an "Analytics" button that opens a separate window:

```python
# Add after recommendations section:
        # Analytics button
        self.analytics_button = ttk.Button(
            self.recommendations_frame,
            text="View Analytics",
            command=self._on_view_analytics,
        )
        self.analytics_button.pack(side="right", padx=(5, 0))

# Add method:
    def _on_view_analytics(self) -> None:
        \"\"\"Open analytics window.\"\"\"
        controller = self._get_learning_controller()
        if not controller:
            return

        # Create analytics window
        analytics_window = tk.Toplevel(self.master)
        analytics_window.title("Learning Analytics")
        analytics_window.geometry("800x600")

        from src.gui.views.learning_analytics_panel import LearningAnalyticsPanel

        analytics_panel = LearningAnalyticsPanel(analytics_window)
        analytics_panel.pack(fill="both", expand=True)

        # Store reference for refresh
        controller._analytics_panel = analytics_panel

        # Load initial data
        controller.refresh_analytics()
```

### Step 5: Create Tests

**File:** `tests/learning_v2/test_learning_analytics.py`

```python
\"\"\"Tests for learning analytics engine.

PR-LEARN-010: Analytics Dashboard
\"\"\"
from __future__ import annotations

import tempfile
from pathlib import Path

from src.learning.learning_analytics import LearningAnalytics
from src.learning.learning_record import LearningRecord, LearningRecordWriter


def test_get_overall_summary_empty():
    \"\"\"Verify summary with no records.\"\"\"
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(str(records_path))

        analytics = LearningAnalytics(writer)
        summary = analytics.get_overall_summary()

        assert summary.total_experiments == 0
        assert summary.total_ratings == 0
        assert summary.avg_rating == 0


def test_get_overall_summary_with_ratings():
    \"\"\"Verify summary calculation with ratings.\"\"\"
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(str(records_path))

        # Create test records
        for rating in [3, 4, 5]:
            record = LearningRecord.from_pipeline_context(
                base_config={"prompt": "test"},
                variant_configs=[{"cfg": 7.0}],
                randomizer_mode="learning_experiment",
                randomizer_plan_size=1,
                metadata={
                    "experiment_name": "test_exp",
                    "user_rating": rating,
                },
            )
            writer.append_record(record)

        analytics = LearningAnalytics(writer)
        summary = analytics.get_overall_summary()

        assert summary.total_experiments == 1
        assert summary.total_ratings == 3
        assert summary.avg_rating == 4.0


def test_export_to_json():
    \"\"\"Verify JSON export.\"\"\"
    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        output_path = Path(tmpdir) / "analytics.json"

        writer = LearningRecordWriter(str(records_path))
        analytics = LearningAnalytics(writer)

        analytics.export_to_json(output_path)

        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)
            assert "total_experiments" in data


def test_export_to_csv():
    \"\"\"Verify CSV export.\"\"\"
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        output_path = Path(tmpdir) / "analytics.csv"

        writer = LearningRecordWriter(str(records_path))
        analytics = LearningAnalytics(writer)

        analytics.export_to_csv(output_path)

        assert output_path.exists()

        with open(output_path) as f:
            content = f.read()
            assert "Experiment ID" in content
```

**File:** `tests/learning_v2/test_analytics_panel.py`

```python
\"\"\"Tests for analytics panel GUI.

PR-LEARN-010: Analytics Dashboard
\"\"\"
from __future__ import annotations

import tkinter as tk

from src.gui.views.learning_analytics_panel import LearningAnalyticsPanel
from src.learning.learning_analytics import AnalyticsSummary, ExperimentSummary


def test_analytics_panel_creation():
    \"\"\"Verify analytics panel can be created.\"\"\"
    root = tk.Tk()
    try:
        panel = LearningAnalyticsPanel(root)
        assert panel.summary_text is not None
        assert panel.experiments_tree is not None
    finally:
        root.destroy()


def test_update_analytics_empty():
    \"\"\"Verify display with no analytics.\"\"\"
    root = tk.Tk()
    try:
        panel = LearningAnalyticsPanel(root)
        panel.update_analytics(None)

        content = panel.summary_text.get(1.0, tk.END)
        assert "No analytics" in content
    finally:
        root.destroy()


def test_update_analytics_with_data():
    \"\"\"Verify display with analytics data.\"\"\"
    root = tk.Tk()
    try:
        panel = LearningAnalyticsPanel(root)

        summary = AnalyticsSummary(
            total_experiments=2,
            total_ratings=10,
            avg_rating=4.2,
            experiments=[
                ExperimentSummary(
                    experiment_id="test_exp",
                    parameter_name="CFG Scale",
                    total_variants=3,
                    total_ratings=5,
                    best_value=7.5,
                    best_rating=4.8,
                    worst_value=5.0,
                    worst_rating=3.2,
                    completion_rate=1.0,
                )
            ],
            parameter_stats=[],
        )

        panel.update_analytics(summary)

        content = panel.summary_text.get(1.0, tk.END)
        assert "Total Experiments: 2" in content
        assert "Total Ratings: 10" in content

        # Check tree has one item
        items = panel.experiments_tree.get_children()
        assert len(items) == 1
    finally:
        root.destroy()
```

---

## 5. Verification

### 5.1 Manual Verification

1. Run multiple learning experiments and rate images
2. Open Analytics view from review panel
3. Verify statistics are displayed correctly
4. Export analytics to JSON and CSV
5. Verify files contain correct data

### 5.2 Automated Verification

```bash
pytest tests/learning_v2/test_learning_analytics.py -v
pytest tests/learning_v2/test_analytics_panel.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-009
- **Enables:** Future enhancement PRs for advanced analytics

---

## 7. Future Enhancements

- Add line charts showing rating trends over time
- Implement parameter comparison graphs
- Add filtering by date range or experiment type
- Export to Excel format with charts
- Add statistical significance testing
