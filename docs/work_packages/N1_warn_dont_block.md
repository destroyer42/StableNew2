# N1: warn, don't block

## Objective

- Outcome: a governance, qualification or recognition status on something the operator can select is a visible
  warning at Preview/Queue, not a refusal, and a policy refusal never happens at dispatch after the operator has
  walked away. Real safety and data-integrity blocks stay, and are reported as early as they can be known.
- In scope (owner approval 2026-11-25, "Approve as proposed", with two changes: warnings say why and how to make it
  work, and observed execution should outrank registry evidence):
  - W1/W6, experimental video workflows. Queue on a header that shows the warning is the job's recorded opt-in. There
    is no re-pick after restore or handoff, and the Storyboard checkbox is replaced by a warning. The accepted
    warning is frozen in `provenance.metadata.accepted_warnings`. `JobService` admission refuses any experimental
    workflow without its opt-in; before, it did so only for controlled motion.
  - W2/W3, Forge checkpoints without a qualified profile (FLUX layouts, unrecognised DiT, Z-Image other than Turbo,
    f3-image-small, FLUX.2 Klein 9B):
    - the picker labels them `(unqualified)`, with the why-and-fix text;
    - the dispatch gate returns a `PolicyWarning` and runs the job with Forge's module selection left as it is
      (option a);
    - Pipeline Queue records the warning the picker showed;
    - a file that is positively a text encoder or VAE is still refused.
  - W4, real blocks moved to Queue. The image backend stage chain and ADetailer on an exact-profile model were checked
    only in `run_njr`. They are now shared with Queue admission (`src/pipeline/image_admission.py`).
  - W8, the ControlNet dispatch bug. `forge_controlnet_units.validate_target` now uses the registry family lookup.
  - Helpful real blocks: a FLUX.1 profile's missing module files name the folder they go in.
  - Warnings are data (`src/pipeline/policy_warnings.py`), so the phone gateway (RG-140, control S12) renders the
    same records. The phone video path records surface `phone`.
- Explicit exclusions:
  - **W7 is a follow-up package (N1b).** These are the Learning, Review, ControlNet, mask and outpaint features that
    require "registry-verified SDXL". The owner's rule ("if it works, it works": observed execution outranks
    registry evidence) needs its own evidence design. See "Not done" below.
  - Eval suite arms keep their authored per-arm opt-in.
  - The 600 s whole-job ceiling, and queue pausing on repeated failures.
  - Fun Control 1.0.0 stays refused: its pinned `not_qualified` policy is immutable, and the 1.1.0 trial is the
    queueable version.
  - Live VRAM floors stay at dispatch; they are live measurements. Static host-RAM minimums stay blocks (owner Q3).
  - Not moved to Queue in this package, though they are still dispatch-only real blocks:
    - the Klein 32 GB host-RAM check;
    - hypernetworks on Forge;
    - localized-only ADetailer on A1111;
    - FFmpeg missing for Movie Clips;
    - RIFE without a frame rate.

    Each needs its own Preview twin. They are listed for a follow-up. N1c (`N1c_early_real_blocks.md`) moves all five
    to Queue admission.

## Execution class and model recommendation

- Execution class: Architectural (amends an `AGENTS.md` section 2 rule; owner-approved wording, see "Wording
  deviation").
- Execution location: Local.
- Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- Expected usage: about 30M cache-read, 250k output (three read-only inventory subagents plus implementation).

## Exact start state and authorities

- Task start: 2026-11-25T21:20:56-05:00. Session `claude:b4df9986-48ad-4a71-89ac-97e4e6a4aaa2` plus three read-only
  inventory subagents in the same session stream. Started by session `local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`.
- Repository and branch: `destroyer42/StableNew2`, `claude/ecstatic-turing-1267bc`.
- Required start SHA / `origin/main`: dbdfa2a3.
- Canonical docs consulted: `AGENTS.md`, `STATUS.md`, `docs/Subsystems/Video/VIDEO_PIPELINE.md` sections 1.1, 4 and
  10, `docs/Subsystems/Image/MODEL_PROFILES.md`, RG-100 control S12 (branch `docs/rg-100-phone-review-gateway`).

## Surface assessment

- Controller surface touched: Yes.
  - `src/controller/video_workflow_controller.py` (one line shorter than on `main`; projects `policy_warnings`; its test limit is under 260 lines).
  - `src/controller/pipeline_controller_services/queue_submission_service.py` (+7).
  - None of the four ratcheted controllers changed size.
- Architecture authority changed: Yes. `AGENTS.md` section 2 gains the N1 bullet. `VIDEO_PIPELINE.md` invariants 3 and
  4 are amended.
- No second queue, runner, compiler or history authority. Acceptance is frozen on the NJR before
  `JobService.submit_njrs`. Dispatch reads only the NJR's provenance.

## Wording deviation from the approved draft

The approved draft said "`JobService.submit_njrs` refuses a job whose warnings were not accepted".

Applied to image models, that would turn today's dispatch refusal into a Queue refusal on every path that cannot yet
show the warning: PromptPack batches, Learning, Review and the phone. That is still a block. So the landed wording
narrows it:

- `JobService` refuses an **experimental workflow** without its recorded opt-in; `AGENTS.md` section 2 already
  required that opt-in.
- No other warning refuses a job.
- Dispatch never refuses for policy.

The owner should confirm this.

## Not done (follow-up N1b)

"Registry-verified SDXL" means that StableNew's asset registry read the checkpoint's safetensors header and classified
it as an SDXL base model. A model refused by these features is one whose header could not be classified, or that has
no registry snapshot yet. It is not one that was proven to be the wrong kind.

These features refuse such a model at Preview:

- Learning Embedding, LoRA Composition, Prompt Slot, Two-Axis and Model Comparison
- ControlNet
- the Review mask editor and outpaint
- guided ADetailer and img2img

N1b would do two things:

- Make an unclassified family a warning wherever the backend can physically run the operation. A positively
  identified wrong family stays a block.
- Count observed successful execution of the exact model and operation in the job repository as evidence that
  outranks the registry (the owner's rule).

## Completion report

See the session report (`AGENTS.md` section 8).
