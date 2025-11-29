# StableNew – Next Features Backlog (v1.0)

_Last updated: 2025-11-15_

These are **candidate features** to pursue after:

1. Repo cleanup and doc consolidation (Phase 1)
2. Stability + TDD + core refactors (Phase 2)
3. GUI overhaul groundwork (Phase 3)

They’re intentionally high-level so they can be turned into design docs and small PRs later.

---

## 1. Video Pipeline Upgrade

**Goal:** Make video creation a first-class citizen, not an afterthought.

**Ideas:**

- Clean `VideoCreator` abstraction:
  - Input: ordered list of image paths + config.
  - Output: MP4 path and manifest entries.
- GUI controls for:
  - FPS, codec, resolution, bitrate.
  - Whether to generate a video automatically for each run.
- Tests:
  - Confirm video stage is invoked when `video_enabled` is true.
  - Manifest summaries include `video_path` or `video_summary` fields.

---

## 2. Distributed Workloads Across Local Network

**Goal:** Harness multiple machines/GPUs on your home network to run StableNew jobs.

**Ideas:**

- Define a simple “worker” JSON protocol:
  - Job payload: prompts, config, preset references.
  - Response: manifest + metadata, or pointer to output on shared storage.
- Implement a **headless worker** script:
  - Runs in a terminal or as a service on other machines.
  - Accepts HTTP requests from the primary StableNew instance.
- Front-end controller:
  - UI to select which node runs a job.
  - Simple status view for worker availability.

---

## 3. Job Queue & Scheduling Enhancements

**Goal:** Move from “single-run” to “job-oriented” workflows.

**Ideas:**

- A **job model**:
  - ID, name, status, created time, config, results path.
- Queue behavior:
  - Add job (from current configuration).
  - Run all queued jobs sequentially.
  - Pause/resume/clear queue.
- Integration with distributed workers:
  - Allow jobs to target specific workers or auto-assign.

---

## 4. Automated Refinement & Restoration Pipeline

**Goal:** Add an optional final cleanup pass to generated images.

**Ideas:**

- A “Refinement” stage that can:
  - Run a face restoration tool.
  - Apply upscaler/denoiser presets tuned for specific models.
  - Optionally apply a “web delivery” resizing step.
- Config for:
  - Whether to run refinement.
  - Which presets or tools to use.
- Tests:
  - Guard that refinement doesn’t alter prior pipeline invariants (e.g., manifests, file naming).

---

## 5. Advanced Queue / Batch Controls for Prompt Packs

**Goal:** Give power users more control over how prompt packs are consumed.

**Ideas:**

- Per-pack:
  - `max_images` / `max_prompts`.
  - Per-prompt overrides (e.g., specific negative prompts or model switches).
- Pack scheduling strategies:
  - Sequential, random, weighted random.
- Integration with randomization:
  - Ensure pack-level settings and randomization/prompt matrix play nicely together.
- Tests:
  - Journey tests that run multi-pack batches with specific scheduling and confirm logs, manifests, and counts.

---

These features should each be preceded by a small design doc (1–2 pages) before implementation, and every implementation should follow the **Controller → Implementer → Tester** model with TDD and small PRs.
