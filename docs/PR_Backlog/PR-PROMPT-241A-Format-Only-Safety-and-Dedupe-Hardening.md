# PR-PROMPT-241A - Format-Only Safety and Dedupe Hardening

Status: Planned
Priority: HIGH
Effort: SMALL
Phase: Prompt Optimizer v3 Foundation
Date: 2026-03-21

## Summary

Harden the existing prompt optimizer so its default path is provably safe and
non-semantic.

## Primary Outcomes

- LoRA dedupe no longer collapses different weights
- weighted prompt syntax is not silently normalized into semantic loss
- `preserve_unknown_order` and `preserve_lora_relative_order` become real,
  enforced behaviors
- the default path remains format-only and fail-open
