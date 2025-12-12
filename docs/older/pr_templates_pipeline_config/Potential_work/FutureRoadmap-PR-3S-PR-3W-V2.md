1. Future Roadmap: PR-3S → PR-3W (Learning Tab Extensions)

These are intentionally deferred and can be turned into full PR templates later. For now, think of them as labeled parking spots.

PR-3S – Learning X/Y Plot Experiments (Two-Parameter Sweeps)

Extend the Learning tab to support two variables under test (e.g., CFG × steps, LoRA strength × denoise).

Adds an experiment mode where the center panel shows a matrix grid of variants instead of a simple list.

Integrates with existing LearningPlan / LearningState so each cell (x,y) is a variant with its own images and ratings.

PR-3T – Learning Results Browser & History View

Add a “History” view to the Learning tab for browsing previous experiments: filters by date, variable, prompt, stage.

Uses existing JSONL LearningRecordWriter as the backing store; surfaces basic analytics (e.g., “CFG 7–9 tends to be best for this prompt type”).

PR-3U – Recommendation Engine v1 (Use Learning Data to Suggest Settings)

Read existing LearningRecords and offer simple recommendations in Pipeline (and optionally Prompt) tabs.

Example: when you pick a prompt + stage combo, show: “Based on past runs, CFG ~8 and 22–28 steps perform best.”

This builds directly on the Learning tab’s goal of capturing structured experiment results.

PR-3V – Advanced Multi-Arm Bandit / Tournament Mode

Experimental “auto-pruning” mode where the system tries multiple variants, lets you rate them, then focuses on winners automatically.

Still uses the pipeline as the execution engine; Learning tab orchestrates rounds of experiments and selections.

PR-3W – Export, Reporting, and Sharing of Learning Artifacts

Tools to export experiment results (images + configs + ratings) into:

CSV / JSON summaries

Folder structures with sidecar metadata

Helpful for offline review, documentation, or sharing with others.

These stay explicitly out of scope for the current Learning implementation (PR-3A–3R) and live in a “Future Learning Roadmap” section until we’re ready.