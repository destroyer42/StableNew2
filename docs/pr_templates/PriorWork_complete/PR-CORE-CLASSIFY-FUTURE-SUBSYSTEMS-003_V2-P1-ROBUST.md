# PR-CORE-CLASSIFY-FUTURE-SUBSYSTEMS-003_V2-P1-ROBUST

**Goal:** Re-apply PR-003 classification in a context-robust way by adding a small,
standardized `Subsystem` header comment to each future subsystem file. These patches
only *insert* lines at the top of files (no context-sensitive body changes), making
them resilient to prior edits and Codex partial application.

Below are unified diffs for the remaining subsystem files. Each hunk simply inserts:

```python
# Subsystem: <Name>
# Role: <short description>
```

at the very top of the module.

## Learning core

diff --git a/src/learning/dataset_builder.py b/src/learning/dataset_builder.py
index 0000000..0000000 100644
--- a/src/learning/dataset_builder.py
+++ b/src/learning/dataset_builder.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Aggregates pipeline run outputs into datasets for training/evaluation.
+

diff --git a/src/learning/feedback_manager.py b/src/learning/feedback_manager.py
index 0000000..0000000 100644
--- a/src/learning/feedback_manager.py
+++ b/src/learning/feedback_manager.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Captures explicit ratings and notes for completed runs.
+

diff --git a/src/learning/learning_adapter.py b/src/learning/learning_adapter.py
index 0000000..0000000 100644
--- a/src/learning/learning_adapter.py
+++ b/src/learning/learning_adapter.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Builds learning plans and sweeps from base configs and pipeline context.
+

diff --git a/src/learning/learning_contract.py b/src/learning/learning_contract.py
index 0000000..0000000 100644
--- a/src/learning/learning_contract.py
+++ b/src/learning/learning_contract.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Defines core dataclasses and contracts shared across the learning subsystem.
+

diff --git a/src/learning/learning_execution.py b/src/learning/learning_execution.py
index 0000000..0000000 100644
--- a/src/learning/learning_execution.py
+++ b/src/learning/learning_execution.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Coordinates execution of learning-mode runs without GUI dependencies.
+

diff --git a/src/learning/learning_feedback.py b/src/learning/learning_feedback.py
index 0000000..0000000 100644
--- a/src/learning/learning_feedback.py
+++ b/src/learning/learning_feedback.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Defines feedback domain models for learning-mode evaluations.
+

diff --git a/src/learning/learning_plan.py b/src/learning/learning_plan.py
index 0000000..0000000 100644
--- a/src/learning/learning_plan.py
+++ b/src/learning/learning_plan.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Defines learning plans and run steps used by learning execution.
+

diff --git a/src/learning/learning_profile_sidecar.py b/src/learning/learning_profile_sidecar.py
index 0000000..0000000 100644
--- a/src/learning/learning_profile_sidecar.py
+++ b/src/learning/learning_profile_sidecar.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Associates model/LoRA profiles with learning runs via sidecar metadata.
+

diff --git a/src/learning/learning_record.py b/src/learning/learning_record.py
index 0000000..0000000 100644
--- a/src/learning/learning_record.py
+++ b/src/learning/learning_record.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Defines learning record schemas and persistence helpers.
+

diff --git a/src/learning/learning_record_builder.py b/src/learning/learning_record_builder.py
index 0000000..0000000 100644
--- a/src/learning/learning_record_builder.py
+++ b/src/learning/learning_record_builder.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Builds LearningRecord instances from pipeline outputs and metadata.
+

diff --git a/src/learning/learning_runner.py b/src/learning/learning_runner.py
index 0000000..0000000 100644
--- a/src/learning/learning_runner.py
+++ b/src/learning/learning_runner.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Drives end-to-end learning plan execution.
+

diff --git a/src/learning/model_profiles.py b/src/learning/model_profiles.py
index 0000000..0000000 100644
--- a/src/learning/model_profiles.py
+++ b/src/learning/model_profiles.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Declares model and LoRA profile descriptors for learning runs.
+

diff --git a/src/learning/recommendation_engine.py b/src/learning/recommendation_engine.py
index 0000000..0000000 100644
--- a/src/learning/recommendation_engine.py
+++ b/src/learning/recommendation_engine.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Explores parameter space to recommend improved configurations.
+

diff --git a/src/learning/run_metadata.py b/src/learning/run_metadata.py
index 0000000..0000000 100644
--- a/src/learning/run_metadata.py
+++ b/src/learning/run_metadata.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Captures structured metadata for each learning run.
+


## Learning GUI/controller

diff --git a/src/gui/controllers/learning_controller.py b/src/gui/controllers/learning_controller.py
index 0000000..0000000 100644
--- a/src/gui/controllers/learning_controller.py
+++ b/src/gui/controllers/learning_controller.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Bridges the learning GUI tab and the core learning subsystem.
+

diff --git a/src/gui/learning_state.py b/src/gui/learning_state.py
index 0000000..0000000 100644
--- a/src/gui/learning_state.py
+++ b/src/gui/learning_state.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Stores learning-mode UI state and user selections.
+

diff --git a/src/gui/learning_review_dialog_v2.py b/src/gui/learning_review_dialog_v2.py
index 0000000..0000000 100644
--- a/src/gui/learning_review_dialog_v2.py
+++ b/src/gui/learning_review_dialog_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Presents recent learning runs for review and rating.
+

diff --git a/src/gui/views/learning_plan_table.py b/src/gui/views/learning_plan_table.py
index 0000000..0000000 100644
--- a/src/gui/views/learning_plan_table.py
+++ b/src/gui/views/learning_plan_table.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Renders a table of learning plans and planned runs.
+

diff --git a/src/gui/views/learning_review_panel.py b/src/gui/views/learning_review_panel.py
index 0000000..0000000 100644
--- a/src/gui/views/learning_review_panel.py
+++ b/src/gui/views/learning_review_panel.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Shows learning run results and feedback controls.
+

diff --git a/src/gui/views/learning_tab_frame.py b/src/gui/views/learning_tab_frame.py
index 0000000..0000000 100644
--- a/src/gui/views/learning_tab_frame.py
+++ b/src/gui/views/learning_tab_frame.py
@@ -1,0 +1,3 @@
+# Subsystem: Learning
+# Role: Hosts the full learning tab layout in the GUI.
+


## Queue

diff --git a/src/queue/__init__.py b/src/queue/__init__.py
index 0000000..0000000 100644
--- a/src/queue/__init__.py
+++ b/src/queue/__init__.py
@@ -1,0 +1,3 @@
+# Subsystem: Queue
+# Role: Exposes queue models and the single-node runner for local execution.
+

diff --git a/src/queue/job_history_store.py b/src/queue/job_history_store.py
index 0000000..0000000 100644
--- a/src/queue/job_history_store.py
+++ b/src/queue/job_history_store.py
@@ -1,0 +1,3 @@
+# Subsystem: Queue
+# Role: Persists completed job history for inspection and learning.
+

diff --git a/src/queue/job_model.py b/src/queue/job_model.py
index 0000000..0000000 100644
--- a/src/queue/job_model.py
+++ b/src/queue/job_model.py
@@ -1,0 +1,3 @@
+# Subsystem: Queue
+# Role: Defines the Job domain model, statuses, and priorities.
+

diff --git a/src/queue/job_queue.py b/src/queue/job_queue.py
index 0000000..0000000 100644
--- a/src/queue/job_queue.py
+++ b/src/queue/job_queue.py
@@ -1,0 +1,3 @@
+# Subsystem: Queue
+# Role: Implements the in-memory job queue contract.
+

diff --git a/src/queue/single_node_runner.py b/src/queue/single_node_runner.py
index 0000000..0000000 100644
--- a/src/queue/single_node_runner.py
+++ b/src/queue/single_node_runner.py
@@ -1,0 +1,3 @@
+# Subsystem: Queue
+# Role: Executes queued jobs on a single node in FIFO/priority order.
+


## Cluster

diff --git a/src/cluster/__init__.py b/src/cluster/__init__.py
index 0000000..0000000 100644
--- a/src/cluster/__init__.py
+++ b/src/cluster/__init__.py
@@ -1,0 +1,3 @@
+# Subsystem: Cluster
+# Role: Exposes cluster worker descriptors and registry primitives.
+

diff --git a/src/cluster/worker_model.py b/src/cluster/worker_model.py
index 0000000..0000000 100644
--- a/src/cluster/worker_model.py
+++ b/src/cluster/worker_model.py
@@ -1,0 +1,3 @@
+# Subsystem: Cluster
+# Role: Describes individual worker capabilities for cluster scheduling.
+

diff --git a/src/cluster/worker_registry.py b/src/cluster/worker_registry.py
index 0000000..0000000 100644
--- a/src/cluster/worker_registry.py
+++ b/src/cluster/worker_registry.py
@@ -1,0 +1,3 @@
+# Subsystem: Cluster
+# Role: Tracks available workers and their state for distributed execution.
+


## AI settings generator

diff --git a/src/ai/settings_generator_adapter.py b/src/ai/settings_generator_adapter.py
index 0000000..0000000 100644
--- a/src/ai/settings_generator_adapter.py
+++ b/src/ai/settings_generator_adapter.py
@@ -1,0 +1,3 @@
+# Subsystem: AI
+# Role: Transforms learning data into AI-friendly requests for settings generation.
+

diff --git a/src/ai/settings_generator_contract.py b/src/ai/settings_generator_contract.py
index 0000000..0000000 100644
--- a/src/ai/settings_generator_contract.py
+++ b/src/ai/settings_generator_contract.py
@@ -1,0 +1,3 @@
+# Subsystem: AI
+# Role: Defines contracts/enums for AI-driven settings suggestions.
+

diff --git a/src/ai/settings_generator_driver.py b/src/ai/settings_generator_driver.py
index 0000000..0000000 100644
--- a/src/ai/settings_generator_driver.py
+++ b/src/ai/settings_generator_driver.py
@@ -1,0 +1,3 @@
+# Subsystem: AI
+# Role: Hosts the integration point to the real AI backend (stubbed for now).
+


## Adapters

diff --git a/src/gui/model_list_adapter_v2.py b/src/gui/model_list_adapter_v2.py
index 0000000..0000000 100644
--- a/src/gui/model_list_adapter_v2.py
+++ b/src/gui/model_list_adapter_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Provides model/VAE lists to GUI widgets without Tkinter coupling.
+

diff --git a/src/gui/prompt_pack_adapter_v2.py b/src/gui/prompt_pack_adapter_v2.py
index 0000000..0000000 100644
--- a/src/gui/prompt_pack_adapter_v2.py
+++ b/src/gui/prompt_pack_adapter_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Exposes prompt pack summaries and metadata to GUI widgets.
+

diff --git a/src/gui_v2/adapters/__init__.py b/src/gui_v2/adapters/__init__.py
index 0000000..0000000 100644
--- a/src/gui_v2/adapters/__init__.py
+++ b/src/gui_v2/adapters/__init__.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Groups Tk-free adapter modules used by GUI V2.
+

diff --git a/src/gui_v2/adapters/learning_adapter_v2.py b/src/gui_v2/adapters/learning_adapter_v2.py
index 0000000..0000000 100644
--- a/src/gui_v2/adapters/learning_adapter_v2.py
+++ b/src/gui_v2/adapters/learning_adapter_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Connects learning GUI controls to the learning subsystem.
+

diff --git a/src/gui_v2/adapters/pipeline_adapter_v2.py b/src/gui_v2/adapters/pipeline_adapter_v2.py
index 0000000..0000000 100644
--- a/src/gui_v2/adapters/pipeline_adapter_v2.py
+++ b/src/gui_v2/adapters/pipeline_adapter_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Translates GUI pipeline overrides into controller payloads.
+

diff --git a/src/gui_v2/adapters/randomizer_adapter_v2.py b/src/gui_v2/adapters/randomizer_adapter_v2.py
index 0000000..0000000 100644
--- a/src/gui_v2/adapters/randomizer_adapter_v2.py
+++ b/src/gui_v2/adapters/randomizer_adapter_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Connects GUI randomizer controls to the randomization engine.
+

diff --git a/src/gui_v2/adapters/status_adapter_v2.py b/src/gui_v2/adapters/status_adapter_v2.py
index 0000000..0000000 100644
--- a/src/gui_v2/adapters/status_adapter_v2.py
+++ b/src/gui_v2/adapters/status_adapter_v2.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Routes controller/pipeline events into StatusBarV2 updates.
+

diff --git a/src/gui_v2/randomizer_adapter.py b/src/gui_v2/randomizer_adapter.py
index 0000000..0000000 100644
--- a/src/gui_v2/randomizer_adapter.py
+++ b/src/gui_v2/randomizer_adapter.py
@@ -1,0 +1,3 @@
+# Subsystem: Adapters
+# Role: Provides a legacy import shim to the V2 randomizer adapter.
+

