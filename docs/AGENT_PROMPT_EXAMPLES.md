# StableNew Agent Prompt Examples

These prompts are intentionally short. The repository and agent customizations
supply the operating procedure.

## Feature / end state

Add automatic VAE selection for locally discovered image checkpoints.

End state:
When the operator selects a known checkpoint, StableNew automatically resolves
the recommended VAE or explicit no-VAE choice from governed asset metadata,
while preserving an operator override.

Constraints:
No backend-specific decision logic in the GUI. Preserve replayability and the
existing NJR/runtime authorities.

Take this from discovery through PR-ready verification. Stop only for a
material product or architecture choice.

## Bug

Image generation sometimes leaves Add to Queue disabled after Add to Job.

Reproduce the current behavior, determine root cause from current repository
evidence, implement the smallest correct fix, add regression coverage, run
proportional validation, and make the result PR-ready. Preserve unrelated work.

## Technology research

Evaluate the current best supported implementation path for directed
whole-body image-to-video motion on the StableNew target machine.

Use current upstream evidence. Compare candidate runtime requirements,
licensing, Windows/Comfy integration fit, backend neutrality, and expected
quality against StableNew's current video contract. Return a bounded
qualification recommendation. Do not install models or change production code.

## Architecture

We want one common capability model for image and video backends so the UI can
offer only settings the selected backend supports.

Determine whether this fits current authorities. Identify the smallest coherent
architecture change, affected boundaries, migration path, and acceptance
criteria. Do not implement until any material architecture decision is
identified for approval.

## Independent review

Review the current worktree against its task contract as a hostile verifier.
Try to disprove that the change is correct. Inspect the actual diff and current
code, run focused verification, and report only actionable findings with
evidence. Do not edit the implementation.

## PR closeout

Make the current accepted work PR-ready. Run the deterministic preflight,
inspect the final diff, update only canonical docs whose truth changed, commit
the scoped work, push the feature branch, and prepare/open the PR. Do not merge
to main or publish a release.
