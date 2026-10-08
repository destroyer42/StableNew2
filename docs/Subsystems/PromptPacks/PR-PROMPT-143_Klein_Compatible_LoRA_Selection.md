# PR-PROMPT-143 — Klein-compatible PromptPack LoRA selection

## Execution profile and validation

**Standard, difficult bounded compiler/provenance/Tk work.** Recommended models:
Codex GPT-6.1 Sol XHigh; Claude Code Sonnet 5.5 XHigh. Local/Desktop fits the Tk
submission and registry seams. This effort reduces retries across structured
prompt ownership, background preflight, immutable provenance and backend checks.

Controller Surface Assessment: AppController stays unchanged. PipelineController
delegates builder construction to `src/controller/prompt_pack_preflight.py`; its
surface shrinks from 1,785 to 1,775 lines and the ratchet ceiling falls with it.
The helper coordinates the existing compiler and Tk dispatcher. It owns no queue,
runner, compatibility classifier or runtime lifecycle.

Token-Efficient Validation Plan: temporary production-path compiler/submission
fixtures first; PR-PROMPT-140 and exact Klein evidence/qualification next; affected
Learning/global-prompt/Matrix/queue/replay regressions; bounded mutation checks;
scoped Ruff/mypy and exact diff; one final prescribed PR gate in an isolated
checkout. Installed PromptPacks, models, runtime configuration and physical
generation are outside coding validation.

## Fresh-work contract

The production PromptPack builder factory enables an explicit selection policy
for the exact qualified Klein profile whose LoRA contract admits one adapter.
Generic PR-PROMPT-140 compilation keeps its compile-safe uncertainty semantics;
SDXL and other targets do not enter this selection policy. Learning Model
Comparison keeps its separate evidence-completeness gate and frozen arms.

All rows and Matrix variants are resolved to structured `PackPromptIntent`
before selection. Contributions retain canonical order: actors, authored row
LoRAs, then Style Consistency. The source remains unchanged, including weights,
triggers and Matrix data.

One `CompileEvidence` context prepares the existing AssetRegistry LoRA snapshot
once per build, off Tk, using its existing cache transaction and cancellation
support. Exact Klein decisions come from `classify_klein_lora`; each distinct
name is assessed once. Only the LoRA roots are refreshed. Warm fingerprints
reuse byte identities; cold or changed LoRAs require the registry's existing
hashing to establish identity. No checkpoint scan, network or GPU work occurs.
Unavailable roots, failed refreshes or unreadable matching metadata refuse
preflight. A complete assessment that cannot positively verify an individual
adapter reports `unverified`; it never calls uncertainty incompatibility.

| Verified-compatible candidates | Action |
|---|---|
| Zero | Automatically select none |
| One | Automatically select it at its authored weight |
| Two or more | Require one batch operator review before any NJR exists |

The scrollable batch review offers first, last, a specific compatible adapter,
none or cancel independently for each prompt. Optional first/last/none applies
to every prompt requiring a choice. First/last addresses only the ordered
verified-compatible list. Hidden-content mode suppresses pack and asset names.

The bridge uses the existing GUI dispatcher for the dialog. Source/config/
visibility changes, shutdown, cancelled review or the bounded preflight deadline
invalidate results. Registry cancellation follows the same current-source check.
A stale source request is rejected even if it starts after the draft changed.
Direct Tk calls are refused before evidence preparation. Progress is sent to the
existing application log; frozen decision details appear in Preview Details.

## Structure, adaptation and effective execution

`pack_lora_selection.py` owns the pure choice and frozen evidence contract.
The canonical `adapt_structured_prompt` receives the completed selection and
retains only its chosen structured adapter. Definitively incompatible,
conflicting and unverified adapters are excluded with their original status and
reason. Compatible adapters not chosen are marked `not_selected`.

Existing trigger ownership remains canonical. Removing an actor/style adapter
removes only exclusively owned trigger contributions; shared or LoRA-less
ownership survives. Row prose is never substring-deleted. Manually typed inline
LoRA tokens stay untouched and remain subject to fail-closed backend validation.
An inline token conflicting with a frozen structured selection is refused.

The chosen effective tags, authored weight, rendered tokens and NJR declarations
agree. Effective style participation is recorded separately from source actor/
style intent. Normal target policy still owns dialect, negative, embeddings,
global prompts, optimizer participation and qualified controls.

## Immutable evidence and admission

NJR schema and `SourceKind.PROMPT_PACK` stay unchanged. Frozen provenance contains:

- `source_prompt_intent`: canonical structured source, before target selection;
- `source_actors` and ordinary plan/story intent where supplied;
- `klein_lora_selection`, contract `klein_lora_selection/1`: exact target profile,
  choice, ordered source adapters and canonical JSON digest, selected adapter
  identity/weight, and every exclusion's status, reason and index;
- `prompt_adaptation`, contract `prompt_adaptation/1`: existing engine version and
  content-free source-to-effective operations, including explicit selection.

The selection manifest is copied into executable config metadata as well as
provenance. Backend NJR validation requires these projections to agree. The
contract validates source digest, source/index coverage, compatible identities,
selected/excluded statuses and choice consistency. The digest fingerprints
structured evidence; AssetRegistry remains the sole adapter byte-identity owner.

All assessments and choices finish before NJR materialization. Add to Queue and
Run Now use the same builder policy and existing atomic `JobService.submit_njrs`
path. Cancellation or failed preflight admits no jobs. No dialog, selection or
selection-preparation scan runs in the queue worker.

Existing final backend qualification remains mandatory: exact profile/model,
count, weights, refreshed compatibility and served-file identity. The selected
adapter's refreshed SHA must match the frozen choice. Failure refuses dispatch;
it never chooses a replacement. Replay copies the frozen prompts and manifests
with new lineage and does not reopen the pack or rerun selection/adaptation.
Frozen base prompts remain distinct from executor global/optimizer changes and
runtime final-prompt readback.

## Regression anchors

`tests/pipeline/test_klein_pack_selection_143.py` covers automatic and explicit
choices, complete/failed evidence, Matrix/actor/style ownership, source bytes,
replay, visibility and persisted evidence corruption at both backend boundaries.
`tests/controller/test_pack_selection_preflight_143.py` covers real Add/Run
submission seams, cancellation, stale requests, Tk exclusion and production
policy wiring. `tests/gui_v2/test_pack_lora_dialog_143.py` covers batch and
independent Tk decisions with hidden identities.

Modal regression coverage deliberately keeps another interpreter alive and
uses the shared isolated `tk_root` fixture. Test callbacks have bounded cleanup;
assertions and pytest timeout failures propagate after closing the modal wait.
Invalid choices use a mocked error popup. This preserves real production review
behavior while preventing automated tests from waiting for an operator.

## Hosted validation repair

Execution Profile + Model/Reasoning Recommendation: Narrow, known-root-cause
test/CI repair; Codex GPT-6.1 Sol Medium or Claude Code Sonnet 5.5 Medium.
Local/Desktop retains the Windows Tk reproduction context. Controller Surface
Assessment: no production or controller changes. Token-Efficient Validation
Plan: reconstruct the original affected targets, diagnose the GUI prefix with
per-test output, prove browser dispatch and modal failures with bounded fixtures,
run focused repaired seams, execute the original affected selection with a
desktop-launch audit, reuse unchanged compiler evidence, then run the required
gate once on settled source.

The first batch-choice test formerly created a raw Tk root instead of using the
isolated fixture. In a combined suite, selection variables bound to a surviving
default interpreter while widgets belonged to the new interpreter. Acceptance
read the unchanged variables and opened an error popup inside `wait_window`.
Separately, the WebUI watchdog startup test omitted its existing browser mock;
its successful fake launch reached the real desktop browser dispatcher.

The repair changes tests and CI safeguards only. Browser-dispatch guards fail
on unintended calls while expected launch behavior is asserted through the
existing mock. The affected job retains the 300-second per-test limit using a
thread timer, plus a 30-minute job deadline. The default Linux signal timer
raises a pytest failure that Tk callback exception handling can catch; a bounded
reproducer using the exact pytest-timeout 2.4.0 handler establishes this limitation.
See [pytest-timeout's implementation](https://github.com/pytest-dev/pytest-timeout/blob/2.4.0/pytest_timeout.py).
No model selection, compatibility, provenance, submission or runtime behavior
changes in this repair.
