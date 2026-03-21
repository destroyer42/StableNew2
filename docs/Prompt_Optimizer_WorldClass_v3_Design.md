Prompt_Optimizer_WorldClass_v3_Design.md

Status: Active design reference
Updated: 2026-03-21

## Purpose

Define the target architecture for the next-generation StableNew prompt
optimizer so roadmap and PR planning can treat it as a deterministic, safe,
intent-aware policy system instead of just a formatter.

## Design Direction

The current optimizer remains valuable, but it is primarily a formatting and
ordering layer. The v3 target upgrades that layer into a StableNew-owned
decision system with four separable responsibilities:

- parser and structured prompt context
- intent analysis
- stage policy recommendation and safe auto-fill
- replay-grade decision recording

## Non-Negotiable Invariants

- fail open: any optimizer error returns unchanged prompts and no config
  mutation
- no surprise content injection in the default path
- no override of explicit user choices; only missing or `AUTO` keys may be
  auto-filled
- deterministic decision bundles written to manifests for replay and learning
- prompting modules remain GUI-agnostic and backend-agnostic

## Execution Queue

The executable rollout is tracked in:

- `docs/PR_Backlog/PROMPT_OPTIMIZER_EXECUTABLE_ROADMAP_v2.6.md`

That tranche is currently planned as:

- `PR-PROMPT-241A-Format-Only-Safety-and-Dedupe-Hardening`
- `PR-PROMPT-241B-Orchestrator-and-Intent-Bundle-Recommend-Only`
- `PR-PROMPT-241C-Stage-Policy-Engine-and-Auto-Safe-Fill-Missing`
- `PR-PROMPT-241D-Manifest-Schema-v3-and-Replay-Contract`
- `PR-PROMPT-241E-Learning-Hooks-and-Tuning-Scaffolding`

## Relationship to Existing Systems

- `PR-HARDEN-228` remains the canonical prompt-patch merge-order foundation
- adaptive refinement remains the policy system for refinement decisions, not a
  replacement for prompt optimization
- the prompt optimizer tranche should follow the current secondary-motion video
  tranche, not interrupt it

## Source Research

This design was derived from:

- `docs/deep-research-report-prompt-optimization-world-class.md`
- `docs/StableNew2 Prompt Optimizer Deep Research_ World‑Class, Safe, Intent‑Aware, Policy‑Driven.pdf`
