# Workflow inventory

Source basis: `STATUS.md` capabilities, `task_navigation_contract.py`, the GUI ownership map, living subsystem docs and `coverage_matrix.v1.json` (all at `ed1e989f`). **Inventory, not discovery:** the owner has not yet reviewed any workflow (each is `DISCOVERY OPEN`; see [workflows/](workflows/)). Entry points are tabs/surfaces named in those docs; they were not re-walked in the live application.

Coverage classes: **FDJ** full desktop journey · **PJ** partial journey · **INT** integration-only · **UNT** untested (see `coverage_matrix.v1.json`). Every class excludes physical GPU/model evidence (EV-31).

## 1. Inventory

| # | Workflow (record) | Operator outcome today | Entry points [V/D] | Prerequisites and dependencies | Duplication / overlap | Current coverage | Unqualified |
|---|---|---|---|---|---|---|---|
| W1 | **Create image** — [create-image.md](workflows/create-image.md) | Pack + model → Preview → Add to Queue → Job History → image | Prompt tab; Pipeline tab (sidebar composer, Preview, Queue, Job History); header Run/Preview | Backend running (Forge default, A1111 rollback), checkpoint, PromptPack; managed-runtime readiness | Settings scopes (EV-21); header Run vs Pipeline Preview/Queue; Prompt vs Pipeline split | IMG-01 **FDJ**; ADetailer/upscale cards **INT** | Real checkpoints/quality; ADetailer/upscale end-to-end |
| W2 | **Prompt and models** — [prompt-and-models.md](workflows/prompt-and-models.md) | Author slots/LoRA/embeddings/Matrix/ControlNet; pick model + profile; see effective settings | Prompt tab; Pipeline Model row + profile strip; Learning (profile publication) | Asset registry; model policy; profile store; LoRA metadata | Model/profile in Pipeline *and* Learning baselines; ControlNet low-level fields | IMG-02 **FDJ**; LRN-02 **FDJ**; ControlNet, LoRA/embedding **INT**; Klein/Z-Image **PJ** | Real hashing/family detection; ControlNet guidance quality; prompt-optimizer fidelity (audit [C,T]) |
| W3 | **Edit and improve** — [edit-and-improve.md](workflows/edit-and-improve.md) | Select image(s) → mask/outpaint/reprocess/Photo Optimize → frozen Preview → queue derived job | Review; Photo Optimize; History "Edit Image in Review"; History "Regenerate with Changes"; Learning Staged Curation | Source image; Forge SDXL base for mask/outpaint; Smart Review (opt-in, unqualified) | Review ↔ Photo Optimize ↔ Pipeline reprocess ↔ History iterate | IMG-03 **PJ** (lineage defect on main); Photo Optimize **INT**; Smart Review **INT** | Edit quality; outpaint; real inpaint; Extend Canvas not driven (EV-13) |
| W4 | **Video and motion** — [video-and-motion.md](workflows/video-and-motion.md) | Image → "Make Video" → approved workflow → in-app playback | Review/History/Pipeline preview "Make Video"; Video Workflow; SVD Img2Vid; Motion Library | Comfy managed runtime; FFmpeg; model weights; RAM/VRAM readiness; Blender for conversion | Video Workflow vs SVD Img2Vid (two tabs, two engines); three Make Video doors | VID-01 **FDJ**; VID-02 **PJ** (Blender HOLD); Fun Control **INT** | Real runtime, VRAM headroom, clip quality; conversion; Prepare Motion Source |
| W5 | **Storyboards and movies** — [storyboards-and-movies.md](workflows/storyboards-and-movies.md) | Multi-shot sequence (one job, N segments) → Movie Clips assembly (queued CPU job) | Video Workflow "Multi-shot sequence"; Storyboard drafts; Movie Clips; Job History Resume/Replay | Approved TI2V workflow; segment ledger; FFmpeg | Storyboard form fields vs per-shot fields (GP832-F4) | VID-03 **FDJ**; Movie Clips **PJ**; strict resume/replay **INT** | Segment continuity/quality; resume on real runtime; assembly has no desktop journey |
| W6 | **Learning and experiments** — [learning-and-experiments.md](workflows/learning-and-experiments.md) | Design → Preview → Run → Compare → Rate; evidence catalog; profile publication | Learning tab (Designed / Discovered Outputs / Staged Curation); Model Comparison; Two-Axis; What Should I Test Next? | Registry-verified SDXL for controlled studies; ratings store | Discovered Outputs vs History; Staged Curation vs Review; special studies behind Advanced | LRN-01 **FDJ** (repaired layout); LRN-02 **FDJ**; Model Comparison / Prompt×Model **INT** | Statistical strength; real multi-model cost/RAM preflight |
| W7 | **Library, history and reuse** — [library-history-and-reuse.md](workflows/library-history-and-reuse.md) | Find a past job/asset; open, compare with parent, iterate, replay, batch | Pipeline Job History + Browse All; Motion Library; Review; PromptPack lists | SQLite repository; artifacts on disk | History is inside Pipeline (not a destination); Discovered Outputs; Motion Library separate | History **PJ**; batch ops **INT**; Compare with Parent blocked for masked edits on main (EV-07) | Large-history performance; full-text search not built (64-char prompt prefix) |
| W8 | **AI assistance and automation** — [ai-assistance-and-automation.md](workflows/ai-assistance-and-automation.md) | Prompt Suggest (disabled), Smart Review (opt-in), What Should I Test Next? (deterministic) | Prompt tab "Suggest…"; Review Smart Review; Learning | Offline installation (none qualified); ETW canary hold | None yet; any new assistant risks becoming a parallel path | Offline AI **INT** | Everything physical; every model NOT TESTED (EV-35) |
| W9 | **Runtime, settings and recovery** — [runtime-settings-and-recovery.md](workflows/runtime-settings-and-recovery.md) | Start/stop WebUI/Comfy, readiness, backend faults, queue pause/cancel, shutdown, settings | Header (Run/Stop/Settings/Refresh/Readiness/Debug); Operator Readiness window; Operator Log; WebUI Launch/Retry; Engine Settings | Managed runtimes; GPU quarantine; resource preflight | Readiness window vs status bar vs log vs banner | OPS-01 **PJ** (defects on main); queue pause/resume/cancel **INT** | Real GPU loss/process-kill recovery; resource-preflight refusal (EV-12) |

Out of scope for redesign work: Character Training (HOLD; no trainer bundled).

## 2. Cross-cutting capabilities (not workflows)

Queue/progress (Pipeline queue, header status, Operator Log), Operator Readiness, content-visibility policy, shared media inspector, diagnostics (Debug Hub, Crash Bundle), AI assistance. Hypothesis: these should be reachable *from every task* and own no competing execution path (see `EXPERIENCE_ARCHITECTURE.md` §4).

## 3. Issue-to-workflow matrix (initial)

Cell codes: **B** blocker · **D** duplication · **L** layout debt · **P** product-behavior defect · **C** candidate redesign work · **G** evidence gap. Lowercase = on a local unpublished branch or unverified.

| Issue (evidence) | W1 | W2 | W3 | W4 | W5 | W6 | W7 | W8 | W9 |
|---|---|---|---|---|---|---|---|---|---|
| Chrome ≈ one third of a 1280×680 window (EV-14) | L | L | L | L | L | L | L | | L |
| Nested panes capture the wheel (EV-16, brief §5) | l | | l | l | | | | | |
| Required actions below the fold (EV-17) | | | l | | | | | | |
| Review/Photo list taller than client (EV-18) | | | L | | | | | | |
| Multiple entry points per outcome (EV-15) | D | | D | D | | D | D | | |
| Settings scopes (EV-21) | D | D | | | | D | | | D |
| State progression spread over surfaces (EV-22, EV-09) | C | | | | | | C | | P |
| Masked-edit parent lineage (EV-07) | | | P | | | | P | | |
| Failure reason not visible (EV-08) | | | | | | | | | P |
| Running vs held state mismatch (EV-09) | | | | | | | | | P |
| Sequence admission wording/policy (EV-10) | | | | | P | | | | |
| Blender absent; conversion untested (EV-11) | | | | B(infra) | | | | | |
| Resource-preflight refusal never driven (EV-12) | | | | | | | | | G |
| Extend Canvas never driven (EV-13) | | | G | | | | | | |
| Disclosure-hidden controls (EV-19) | G | G | G | G | | | | | |
| Real DPI/assistive tech untested (EV-25, EV-29) | G | G | G | G | G | G | G | G | G |
| No operator timing baseline (gap 1) | G | G | G | G | G | G | G | G | G |
| Backend/model technical detail exposed early (brief §5) | C | C | | C | | | | | |

`B` appears once and is infrastructure, not UI. Nothing here is a confirmed redesign requirement until the owner reviews the matching workflow record.
