# Controlled Textual Inversion Embedding experiments

Outcome: one designated textual-inversion embedding position varies (Presence, Weight or
Identity; positive or negative channel; 2-8 candidates, 1-3 images each, maximum 24) in the
existing Learning Design/Preview/Run/Compare/Rate flow. Fixed embeddings, prompt text, the other
channel, settings, seeds and model are frozen. Asset identity comes from `AssetRegistry` evidence
plus a header-only safetensors inspection; `ModelPolicy` admits the target. Full embedding-set
prompt readback is required for a controlled variant; a mismatch marks it uncontrolled. Backend
consumption is claimed only from the backend's by-name `TI` report. Ratings stay experiment-local
and never recommend or publish.

Execution Profile: Standard, difficult cross-file correctness/evidence package; Windows
Local/Desktop, one primary session, no delegation.
Model recommendation: Claude Code Sonnet 5.5 XHigh. Backend-syntax correction, frozen
composition, asset identity and three-level evidence justify this tier.
Session: `claude:0dbe0893-bde0-48f0-94fe-86c216d2847b`.
Task start: `2026-10-25T21:48:56-04:00`.

Starting point: main at `a0ee79e4`. Implementation in `C:/Users/rob/qual/StableNew-embed700`,
branch `learning/learn-embed-700-controlled-embeddings`. Local main is not changed.

Owner-approved correction: the pinned Forge Neo (`d70373eb`) removes every unregistered
`<name:args>` tag before tokenization, so the PromptPack/Learning `<embedding:Name>` rendering was
never consumed by the backend. Every compile path now renders the backend invocation
(`render_embedding_invocation`: `Name`, or `(Name:w)`); `render_embedding_reference` stays the
PromptPack TXT/JSON authoring and storage notation. PromptPack storage and parsing are untouched.
Known remaining instance: the executor's aesthetic-embedding injection still appends the
`<embedding:Name>` notation (out of scope; recorded in `STATUS.md` Known debt). Optimizer analysis
records that read embeddings from prompt text no longer list compiled (bare-name) embeddings; the
structured NJR fields remain the identity.

Controller Surface Assessment: LearningController 4,097 -> 4,096 physical lines. Dispatch of the
three controlled studies now goes through one thin table
(`learning_controller_services/controlled_studies.py`); domain freeze/readback/conclusion is
toolkit-neutral (`src/learning/embedding_experiment.py`, `embedding_inventory.py`); coordination
lives in the controller-services namespace; the Tk authoring frame is separate. No ceiling
increase.

Owners: renderer `src/utils/embedding_prompt_utils.py`; inventory/identity `embedding_inventory.py`
over `AssetRegistry` and `src/assets/observation.py`; freezing `embedding_experiment.freeze_candidates`
over the canonical `resolve/adapt/render_pack_intent`; NJR materialization
`learning_controller_services/embedding_experiment.py` over `ordinary_njr`; runtime evidence
`embedding_experiment.readback_reason` / `execution_evidence` via `experiment_reconciliation`
(backend report captured by the executor as `backend_textual_inversion`); recommendation
isolation `recommendation_engine.excluded_studies`.

Exclusions: physical generation, WebUI start/restart, model or embedding file mutation,
deserializing `.pt`/`.bin` containers, PromptPack rewrite, rating/NJR migration, new
browser/compiler/queue/runner/store, recommendation or profile publication, push, remote PR,
merge.

Validation: new tests `tests/learning_v2/test_embedding_experiment_700.py` (78),
`tests/gui_v2/test_embedding_design_700.py` (15), `tests/utils/test_embedding_invocation_700.py`
(25) and `tests/pipeline/test_executor_textual_inversion_report_700.py`; Learning, pipeline, GUI,
assets and tools regressions; canonical `python tools/ci/run_pr_gate.py` (see the completion
report for the outcome).
