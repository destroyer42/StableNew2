# PR-PROMPT-241C - Stage Policy Engine and Auto-Safe Fill Missing

Status: Planned
Priority: HIGH
Effort: MEDIUM
Phase: Prompt Optimizer v3 Policy Rollout
Date: 2026-03-21

## Summary

Use prompt intent and conflicts to generate stage policies that only fill
missing or explicitly `AUTO` keys.

## Primary Outcomes

- stage policy engine for txt2img, img2img, ADetailer, and upscale
- no override of explicit user choices
- rationale and warning capture for every applied or recommended policy
