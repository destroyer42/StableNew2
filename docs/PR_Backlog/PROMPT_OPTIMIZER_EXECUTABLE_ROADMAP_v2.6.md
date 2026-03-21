PROMPT_OPTIMIZER_EXECUTABLE_ROADMAP_v2.6.md

Status: Active planning document
Updated: 2026-03-21

## Purpose

Convert the deep prompt-optimizer research into an executable PR sequence that
hardens today’s formatter and then grows it into a deterministic, policy-driven
prompt decision system.

## Slot in the Current Roadmap

This tranche is intentionally queued after the current secondary-motion video
sequence and before broader low-product-value cleanup. It is high-value product
work, but it should not interrupt `PR-VIDEO-237` through `PR-VIDEO-241`.

## Execution Sequence

### 1. `PR-PROMPT-241A-Format-Only-Safety-and-Dedupe-Hardening`

Primary outcome:

- make the default optimizer path strictly safe and non-semantic
- stop dedupe behavior from collapsing LoRA weight variants or weighted token
  meaning
- make current config flags like `preserve_unknown_order` and
  `preserve_lora_relative_order` real and testable

### 2. `PR-PROMPT-241B-Orchestrator-and-Intent-Bundle-Recommend-Only`

Primary outcome:

- add a StableNew-owned optimizer orchestrator and typed prompt intent bundle
- emit structured prompt context and recommendations without mutating prompts
  or configs

### 3. `PR-PROMPT-241C-Stage-Policy-Engine-and-Auto-Safe-Fill-Missing`

Primary outcome:

- add stage-specific safe policy selection for missing or `AUTO` config fields
- never override explicit user values

### 4. `PR-PROMPT-241D-Manifest-Schema-v3-and-Replay-Contract`

Primary outcome:

- add a versioned `prompt_optimizer_v3` decision bundle to manifests
- make the decision payload deterministic and replay-grade

### 5. `PR-PROMPT-241E-Learning-Hooks-and-Tuning-Scaffolding`

Primary outcome:

- add opt-in learning hooks and bounded tuning scaffolding for optimizer and
  policy evaluation

## Guardrails

- no new GUI-owned prompt logic
- no backend-specific logic inside the prompting subsystem
- fail-open behavior remains mandatory in every PR of this series
- prompt optimization and adaptive refinement must remain distinct but
  compatible systems
