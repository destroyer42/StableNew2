# StableNew GUI/UX audit and improvement tranche

**Date:** 2026-10-22  
**Status:** Point-in-time product-owner audit and candidate implementation sequence; not a claim of a completed runtime qualification or approval of every future PR.  
**Source baseline:** Remote \`main\` at \`991aebc6c409b7174d7d10e2df20b337f28fbc5d\` (already contains PR-GUI-420 responsive Photo Optimize layout).  
**Owner intent:** Preserve the workflow-centric top navigation while making the actual tasks clear, finishing incomplete controls, eliminating redundant entry points, and surfacing canonical artifacts correctly.  
**Authority:** At implementation time re-check current checkout/branch/SHA/diff, \`AGENTS.md\`, \`STATUS.md\`, \`docs/CODEX_MAP.md\`, \`docs/CODE_MAP.md\` and relevant living subsystem docs. This audit is not current repository truth after the stated baseline.

## Assessment method and confidence

- **[C] Code-verified:** current GUI/source or living subsystem documentation directly establishes the implementation behavior.
- **[O] Operator-reported:** reproduced by the owner in the Windows application, but not independently reproduced with an instrumented UI session here.
- **[D] Design judgment:** user-journey issue inferred from the verified layout and owner outcomes.
- **[T] Test needed:** behavior needs a deterministic regression reproduction before a change is accepted.

The live Windows worktree, local installed model/LoRA inventory, runtime GPU state and physical output files were not inspected. There were no physical-generation or model-quality comparisons as part of this audit. Per-work-package investigation must confirm defects against the latest source rather than promote historical observations to current truth.

## Product direction

Retain the existing stable top-level task groups: **Create (Prompt, Pipeline), Edit (Review, Photo Optimize), Motion (Video Workflow, SVD Img2Vid, Movie Clips), Learn (Learning), Advanced (Character Training on hold)**. Do not renumber or delete persisted tab IDs. Improve the tasks *within* the workspaces and use progressive disclosure for advanced controls.

Operator journeys:

1. **Create:** Choose a prompt/pack and model -> set current-job quantity/seed -> optionally enhance -> inspect effective preview -> queue.
2. **Edit:** Select existing asset(s) -> choose quick edit or managed photo-set work -> inspect/edit/compare -> freeze and queue derived jobs.
3. **Motion:** Choose image or sequence -> make motion clip -> play the recorded movie -> optionally assemble clips.
4. **Learn:** Discover/rate promising outputs or design an explicitly controlled experiment -> compare -> curate -> use evidence without mixing observational and experimental claims.

The GUI remains a projection and authoring surface. **Do not create a second queue, runner, persistence authority, compiler, cancellation owner, process authority, or live fallback.** Keep immutable NJR compilation, JobService admission, SQLite job lifecycle, replay lineage and content-visibility policy intact.

## Tab / section findings

| Area | Finding and supporting surface | Recommended outcome | Confidence |
|---|---|---|---|
| Pipeline / Saved Recipes | \`src/gui/sidebar_panel_v2.py\` has list/save/load/apply/delete handlers; it is **not dead code**, but terminology and which settings take effect are unclear. | Explain effective config, reconcile preset/recipe/pack responsibilities; preserve user recipes. | [C,D] |
| Pipeline / Pack Selector | The dropdown is a saved Pack List selection, not necessarily a list of pack-specific configs; owner reports it empty/nonfunctional. | Name it accurately, distinguish genuinely empty inventory from broken callbacks, test config actions. | [C,O,T] |
| Pipeline / Output | \`output_settings_panel_v2.py\` mixes output directory/format/route with batch size and seed mode. | Global defaults in Settings; current-job quantity and seed at point of use; preserve explicit overrides. | [C,D] |
| Pipeline / Stages | \`stage_cards_panel_v2.py\` exposes txt2img, img2img, ADetailer, upscale; Refiner and Hires are txt2img advanced metadata. | Fresh creation foregrounds txt2img and optional enhancements; existing-image img2img authored via Edit. Hide legacy options before considering removal. | [C,D] |
| Pipeline / Reprocess | Sidebar embeds a Reprocess Images panel and legacy Review guidance. | Use Edit as the primary reprocess entry, with intentional one-click handoff where useful. | [C,D] |
| Pipeline / Preview | \`preview_panel_v2.py\` checkbox only reveals a *persisted generated image* for the selected job; no draft image is created. | Distinguish job preview vs generated-artifact preview; make empty states and job source unambiguous. | [C,O] |
| Pipeline / History | \`job_history_panel_v2.py\` image-only artifact thumbnail hides playable MP4; Video Workflow Recent outputs already has bounded video playback. | Select canonical primary media by type, reuse \`VideoPreviewWidget\`, open/reveal the recorded clip not poster. | [C,O] |
| Prompt / Cinematic Template | \`prompt_tab_frame_v2.py\` shows catalog IDs and blank variables despite descriptions in \`data/prompt_templates.json\`. | Friendly labels, example-filled editable values and live composed prompt. | [C,D] |
| Prompt / LoRA keywords | \`lora_keyword_detector.py\` and LoRA browser/Keywords dialog already exist; metadata coverage and affordance need checking against installed assets. | Show evidenced triggers beside chosen LoRA, insert explicitly, distinguish missing metadata from no triggers. Never guess words. | [C,O,T] |
| Prompt / Style Consistency | \`data/style_loras.json\` ships \`cinematic_grit\` and \`storybook_painterly\` *example entries* that require separately installed weights. | Default chooser to available, compatible, evidence-backed assets; explain missing examples. | [C,O] |
| Prompt / Conditioning | \`controlnet_units_panel.py\` exposes low-level OpenPose/Canny/Depth fields and requires pre-rendered maps. | Guided modality examples, legal defaults, reference-map preview and readiness. No promise of automatic preprocessing. | [C,D] |
| Prompt / Matrix | Living PromptPacks doc §5.1/§13 reports fanout=sequential, unseeded random, truncation, unresolved tokens. | Fix semantic contract and preview/admission equality before adding friendly variation templates and count previews. | [C,D] |
| Prompt / Optimizer | \`sdxl_prompt_optimizer.py\` supports LoRA-token extraction and anchoring; default \`preserve_lora_relative_order=True\` can intentionally interleave tags. Anchor-boost option currently does not alter output. | Test effective prompt ordering/LoRA cardinality and model policy, expose before/after, remove ineffective settings. | [C,O,T] |
| Edit / Review | \`review_tab_frame_v2.py\` combines inspection, metadata, ratings, prompt edits, masks, outpaint and queued reprocess. | Task-specific actions with a shared selection and effective-settings summary. | [C,D] |
| Edit / Photo Optimize | Recent PR-GUI-420 improves responsive layout, but persistent per-photo baselines, photo batch operations and Review still overlap. Documented synchronous I/O remains a concern in \`PHOTO_REVIEW_REPROCESS.md\` §8. | Quick Edit vs Managed Photo Set using shared navigation/projections, not merged data stores; remove Tk-thread I/O. | [C,O,D] |
| Motion / Video Workflow | Already has Basic/Advanced, readiness, Make Video handoffs, Recent outputs player, experiments, and sequence controls (\`VIDEO_PIPELINE.md\`). | Preserve successful simplifications, improve cross-tab handoff and discoverability. | [C,D] |
| Motion / SVD | Has recommended presets and many inference/postprocessing controls. | Preset first, advanced settings disclosed as needed; consistent outputs/playback. | [C,D] |
| Motion / Movie Clips | Queued CPU assembly supports images, videos, ordering and settings. | Clear timeline/ordered-source view and playable final movie. | [C,D] |
| Learning / Designed Experiments | Design, plan and ratings share an intricate three-pane editor; frozen controlled experiments already exist. | Design -> Preview -> Run -> Compare -> Rate, with special studies behind Advanced. | [C,O,D] |
| Learning / Discovered Outputs | Separate folder scan, discovered groups, cleanup and ratings. | An intelligible unreviewed-output inbox. | [C,O,D] |
| Learning / Staged Curation | Candidate advancement and Review handoff are implemented; terminology does not explain the intended outcome. | Improve Selected Images with visible lineage and next step, preserving evidence distinction. | [C,O,D] |
| Advanced / Character Training | \`STATUS.md\` states hold pending a trainer. | Retain hold messaging; do not silently enable training. | [C] |

## Critical appraisal and ordering

**Do not rebuild the entire GUI.** A simultaneous rewrite would jeopardize stable tab persistence, image-edit lineage, the queue boundary and ongoing video work, and would conflate visual improvements with correctness fixes.

**Do not delete Refiner, Hires or stored img2img behavior merely because the controls are seldom used.** First change the default navigation and authoring surface, audit references and preserve historical jobs; permanent retirement is a separate owner decision.

**Do not treat a checkbox, empty dropdown or LoRA catalog mismatch as necessarily one root cause.** Inspect state, data sources, exact callbacks and installed inventory. The preview checkbox is known to lack a generated draft image by design; LoRA metadata infrastructure already exists.

**Correct media identity and underlying prompt/Matrix correctness before polish.** A pretty prompt editor with nondeterministic preview expansion or wrong executed tags would be worse than the current UI. For Edit, preserve per-asset Photo Optimize sidecars and whole-selection frozen reprocess admission.

## Candidate work-package sequence

PR names are proposal identifiers, not merged/approved PRs. Each must recheck current authority and obtain owner permission to execute/publication.

| Wave / order | Proposed PR | Bounded operator outcome | Models: Claude Code / Codex | Expected usage (cache-read / output) |
|---|---|---|---|---|
| 1 / 1 | GUI-UX-500 | Truthful Pipeline/Pack empty states, Preview wording, navigation help and no-op audit; no behavior changes | Sonnet 5.5 High / GPT-6.1 Sol High | ~5M / 35k |
| 1 / 2 | **GUI-UX-510** | Video-first recorded artifact selection and History/History Browser playback, original-file actions, missing states | Sonnet 5.5 High / GPT-6.1 Sol High | ~6M / 40k |
| 2 / 3 | GUI-UX-520 | Saved recipe vs pack config ownership, config write integrity, output destination default placement | Sonnet 5.5 XHigh / GPT-6.1 Sol XHigh | ~10M / 65k |
| 2 / 4 | GUI-UX-530 | Simplify Pipeline stage defaults and move new img2img/reprocess entry to Edit, preserving saved-job semantics | Sonnet 5.5 High / GPT-6.1 Sol High | ~7M / 45k |
| 2 / 5 | GUI-UX-540 | Cinematic examples, visible LoRA triggers and truthful installed-style selection | Sonnet 5.5 High / GPT-6.1 Sol High | ~7M / 45k |
| 2 / 6 | GUI-UX-550 | Guided map-based Conditioning with valid defaults and previews | Sonnet 5.5 High / GPT-6.1 Sol High | ~6M / 40k |
| 2 / 7 | GUI-UX-560 | Matrix semantic contract, seeded variation and preview/admission equivalence; owner decision before changing old-pack behavior | Sonnet 5.5 XHigh / GPT-6.1 Sol XHigh | ~10M / 65k |
| 2 / 8 | GUI-UX-570 | Prompt Optimizer executed-order fidelity and meaningful before/after | Sonnet 5.5 High / GPT-6.1 Sol High | ~6M / 40k |
| 3 / 9 | GUI-UX-580 | Coherent Quick Edit vs Managed Photo Set, safe shared UI, responsive I/O; independent persistence kept | Sonnet 5.5 XHigh / GPT-6.1 Sol XHigh | ~12M / 75k |
| 3 / 10 | GUI-UX-590 | Learning guided experiment/curation tasks, ratings remain evidence-correct | Sonnet 5.5 XHigh / GPT-6.1 Sol XHigh | ~10M / 65k |
| 4 / 11 | GUI-UX-600 | Motion and Movie Clips cross-workflow navigation, settings and output consistency | Sonnet 5.5 High / GPT-6.1 Sol High | ~7M / 45k |

**Host:** Prefer current productive Local/Desktop session, especially Tk, SQLite, Windows file paths, installed LoRAs and user outputs. Model recommendations are the lowest tier expected to complete the full bounded package; the estimates are *planning orders of magnitude*, never measured costs. Record one actual \`Model / usage\` line from \`python tools/usage_report.py --since-commit <first_commit> --line\` per PR and investigate usage >3x estimate.

**Dependencies:** 510 can execute independently of 500 because it repairs an artifact display seam without modifying Prompt/Pack controls. 520 before 530; correctness/metadata proof before broader Prompt UX; 580 only after edit-entry ownership is resolved. 600 follows stabilization of output playback.

**Open decision gates:** (1) hide vs retire Refiner/Hires/Pipeline img2img, (2) Matrix mode and random seed migration semantics, (3) default LoRA-token ordering vs preserving authored position. Do not have agents make these changes implicitly.

## GUI-UX-510 acceptance contract

- On selecting an existing recorded still, display the correct image.
- On selecting a finished SVD, Comfy workflow, or queued movie assembly record containing a supported video file, the **recorded video path** wins over a poster/source PNG. The History panel and inherited searchable History Browser reuse the existing cancellable, bounded \`VideoPreviewWidget\`; no second decoder or background process authority.
- A clip's Open/Reveal actions target the **recorded video**, using \`src/utils/os_shell.py\` safe wrappers; failing actions report a visible error. A missing clip shows an explicit missing state, not its poster as a false successful result. Frames-only outputs are not mislabeled as playable.
- Unselecting, hiding, changing selection, applying content-visibility policy or destroying the view cancels/stops preview state; repeated refresh of an unchanged selection does not re-decode. All Tk mutations remain on the GUI thread.
- Source handoffs (Make Video, SVD, Movie Clips), replay, manifests, existing user files and job lifecycle are unchanged. No data migration; no GPU or production runtime required for deterministic tests.
- Tests cover direct video artifacts, top-level bundles, legacy metadata, movie assembly, missing clips, legacy images, frames-only, Open/Reveal and player stop/refresh behavior. Run focused tests and then the canonical PR gate on Python 3.14; required \`required\`, \`full-suite\` and \`windows\` checks determine merge readiness.

## Reference points

- \`src/gui/view_contracts/task_navigation_contract.py\`: nine stable tab IDs and workflow groups.
- \`src/gui/sidebar_panel_v2.py\`, \`src/gui/preview_panel_v2.py\`, \`src/gui/job_history_panel_v2.py\`.
- \`src/gui/views/prompt_tab_frame_v2.py\`, \`src/gui/widgets/lora_picker_panel.py\`, \`src/gui/widgets/matrix_tab_panel.py\`, \`src/gui/widgets/controlnet_units_panel.py\`, \`src/prompting/sdxl_prompt_optimizer.py\`.
- \`src/gui/views/review_tab_frame_v2.py\`, \`src/gui/views/photo_optimize_tab_frame_v2.py\`, \`src/gui/views/learning_tab_frame_v2.py\`.
- \`src/gui/widgets/video_preview_widget_v2.py\`, \`src/gui/views/video_workflow_recent_outputs_panel_v2.py\`, \`src/video/video_artifact_helpers.py\`.
- Living docs: \`docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md\`, \`docs/Subsystems/GUI/GUI_STYLE_GUIDE.md\`, \`docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md\`, \`docs/Subsystems/Learning/LEARNING.md\`, \`docs/Subsystems/Video/VIDEO_PIPELINE.md\`.
- Canonical repo governance: \`AGENTS.md\`, \`STATUS.md\`, \`docs/AI_MODEL_SELECTION.md\`, \`docs/CODEX_WORK_PACKAGE_TEMPLATE.md\`.

**No recommendation here authorizes physical qualification, stored job migrations, deletion of user data, retired-stage semantic changes, force-push or merge.**
