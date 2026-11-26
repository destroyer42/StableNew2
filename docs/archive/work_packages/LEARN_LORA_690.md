# Controlled LoRA composition experiments

Outcome: one designated LoRA position varies (Add / Remove, Replace, or Compare
Candidates at a common strength; 2-8 candidates, 1-3 images each, maximum 24) in the
existing Learning Design/Preview/Run/Compare/Rate flow. Fixed LoRAs, prompt text,
negative prompt, settings, seeds and model are frozen. Asset identity comes from
`AssetRegistry` evidence and `ModelPolicy` admits the whole effective set. Full
LoRA-set prompt readback is required for a controlled variant; a mismatch marks it
uncontrolled. Ratings stay experiment-local and never recommend or publish.

Execution Profile: Standard, difficult cross-file correctness/evidence package;
Windows Local/Desktop, one primary session, no delegation.
Model recommendation: Claude Code Sonnet 5.5 XHigh. Frozen composition, asset identity,
adaptation and readback proof justify this tier.
Session: `claude:d1fa478c-76c8-4ca3-8a94-9cb44a6663d9`.
Task start: `2026-10-25T20:20:45-04:00`.

Starting point: main at `7ceb683f6cf1ae1ae9e222f8db9ede0072780e08`. Implementation in
`C:/Users/rob/qual/StableNew-lora690`, branch `learning/learn-lora-690-controlled-composition`.
Local main is not changed.

Controller Surface Assessment: LearningController 4,084 -> 4,097 physical lines (+13).
Domain freeze/readback/conclusion is toolkit-neutral (`src/learning/lora_composition.py`,
`lora_inventory.py`); coordination lives in the controller-services namespace; the Tk
authoring frame is separate. Controller dispatch stays thin. No ceiling increase.

Owners: inventory/identity `lora_inventory.py` over `AssetRegistry`; freezing
`lora_composition.freeze_candidates` over the canonical `resolve/adapt/render_pack_intent`;
NJR materialization `learning_controller_services/lora_composition.py` over `ordinary_njr`;
runtime evidence `lora_composition.readback_reason` via `experiment_reconciliation`;
recommendation isolation `recommendation_engine.excluded_studies`.

Exclusions: physical generation, WebUI start/restart, model mutation, PromptPack rewrite,
rating/NJR migration, new browser/compiler/queue/runner/store, recommendation or profile
publication, push, remote PR, merge.

Validation: new tests `tests/learning_v2/test_lora_composition_690.py` (55) and
`tests/gui_v2/test_lora_composition_design_690.py` (10); Learning, GUI and tools regressions;
canonical `python tools/ci/run_pr_gate.py` OK. Known pre-existing failure:
`tests/tools/test_operator_journey_gui.py::test_full_fake_journey_including_review_and_ratings`
(`LoRA-Discovery` thread shutdown timeout, fails on main).
