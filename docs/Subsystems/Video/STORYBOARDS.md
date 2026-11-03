# Saving and editing Storyboards

In Video Workflow, expand Advanced → Multi-shot sequence. A Storyboard is editable authoring intent; saving it never queues a job.

1. Choose a source image and workflow in the main form. Add 2–12 shots, each with a motion prompt, native frame length and seed intent.
   Blank prompts inherit the form prompt. Blank shot 1 seed inherits the form seed; later blank seeds and explicit `random` resolve only at admission.
2. Enter a Storyboard title, optional notes and clip name. **Save** creates or revises the draft in `%LOCALAPPDATA%/StableNew/storyboards/`.
   **Save As / Duplicate** creates a new Storyboard ID and independent shot IDs. **Rename** changes the title and saves. There is no library-delete action.
3. **Open** selects saved JSON from that library after restart. **Import JSON** validates an external manifest and saves an independent copy.
   **Export JSON** writes a new JSON file and refuses an existing destination. These files link external media; images/videos are not copied or overwritten.
4. Use **Duplicate Shot**, **Remove**, **Move Up** and **Move Down** to edit the ordered draft. Every shot keeps its label, prompt, native frames, seed
   and authored-anchor path/hash. Shot 1 uses the main source image. If a reordered first shot has a keyframe, clear it or move it back; it is never silently ignored.
5. **Preview Sequence Summary** checks source readiness, reports SHA-256 identity, provided versus carried anchors, legal frames, total native frames,
   approximate duration before overlap trims, workflow/version and incompatible controls. It never freezes random seeds or claims a final executable plan.
   Missing files can stay in a saved draft. A changed source/anchor blocks queueing until **Accept Current Media** explicitly records the current bytes;
   save again to retain that acceptance. The button links existing files and never edits them.
6. Reopened drafts retain their exact workflow version. **Use Selected Workflow** explicitly adopts the version currently selected in the main form.
   Experimental authorization is per job and is never restored from a draft. Fun Control/driving-video workflows remain incompatible with sequences.
7. **Queue Sequence** submits the displayed snapshot/order through existing sequence admission to one immutable NJR and one queue row. Refusals are inline,
   before any submission. Later edits affect only the authoring draft. **Unsaved changes** remains visible until the current draft is saved.

If another session saves first, a revision conflict refuses the stale save; reopen or Save As. Malformed or unknown-schema JSON is never rewritten.
An exclusive `.lock` protects concurrent writers. A crash can leave that lock; an operator must verify no writer remains before removing a stale lock.
No legacy `data/story_plans` or `data/continuity` files are migrated, deleted or rewritten.

In Job History, **Create Storyboard from Sequence** reads the job again from the canonical repository and verifies its frozen typed plan.
It opens a new unsaved draft with original-job/plan provenance, without changing or queueing the original job. Missing/changed source files are shown by Preview.
The editor supports homogeneous Comfy sequence plans with standard overlaps and assembly. It precisely refuses frozen settings it cannot express, including native
SVD model/settings, mixed workflows, differing per-shot negatives or custom assembly/color/overlap. Resume and full Replay retain their existing behavior.

## Proposed later contract: verified suffix regeneration

This is a follow-up proposal, not an implemented capability or an authorization to change execution ownership.

Editing any shot and queueing currently creates a new complete sequence. No prior segment or checkpoint is substituted or rewritten.
A future bounded contract would identify the first changed shot, freeze a new NJR/plan and verify all reused prefix evidence against the parent ledger,
including original plan digest, content hashes, exact boundaries and parent lineage. It must explicitly record reuse in the new job's own ledger.
With a carried anchor, every descendant depends on its preceding final frame and must be regenerated after an ancestor changes.
An independently authored image anchor could establish a new conditioning boundary only after its identity and all suffix inputs are verified; being a
provided anchor alone cannot prove outputs reusable. The existing strict resume contract is not an editor for a changed plan.
Checkpoint ownership, `JobRepository`, `JobService.submit_njrs` and `PipelineRunner.run_njr` remain authoritative. Product/architecture approval and
deterministic refusal tests must precede any such implementation.
