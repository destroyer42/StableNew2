DEBUG HUB v2.6.md
Canonical Diagnostic Surface Reference

Status: Active canonical reference
Last Updated: 2026-03-30

## 0. Purpose

Debug Hub is the read-only diagnostic view over StableNew's canonical runtime
data.

It exists to explain what StableNew built, queued, ran, and recorded without
creating a second execution path.

## 1. Canonical Inputs

Debug Hub may read from:

- NJR-backed provenance
- canonical result summaries
- replay descriptors
- diagnostics descriptors
- runtime-host client state
- runtime-host diagnostics snapshots
- stage manifests
- history records
- diagnostics bundles

Debug Hub may not:

- rebuild fresh execution state from GUI drafts
- mutate queue, history, or runtime state
- become a second source of execution truth

## 2. What Debug Hub Should Show

At minimum, Debug Hub should let an operator inspect:

- effective job identity
- PromptPack or other intent provenance
- resolved prompt and negative prompt where relevant
- normalized execution config
- stage ordering
- model or backend selection
- result artifacts
- replay descriptors
- diagnostics bundle linkage
- failure context
- runtime-host transport and protocol version
- runtime-host connection state and host pid
- host startup or disconnect errors
- host-owned managed WebUI/Comfy runtime state

## 3. Image and Video Scope

Debug Hub is not image-only.

It must work with:

- still-image jobs
- SVD jobs
- workflow-video jobs
- future sequence and assembled-video jobs

It should prefer canonical artifact and result-summary structures over
stage-name-specific heuristics.

## 4. Current Canonical Result Relationship

The modern runtime produces canonical result summaries plus:

- `replay_descriptor`
- `diagnostics_descriptor`

When production is running through the GUI-owned child runtime host, Debug Hub
must also show both sides of that boundary clearly:

- the GUI client's connection and transport state
- the host runtime's pid, managed-runtime state, and host-owned diagnostics

Debug Hub should treat those as first-class entrypoints for understanding what
happened and how a run could be diagnosed or replayed.

## 5. Boundaries

Debug Hub is:

- introspection
- comparison
- operator support
- failure and provenance explanation

Debug Hub is not:

- a builder
- a queue controller
- a runner
- a backend debugger for internal runtime state outside what StableNew records

## 6. Source of Truth Rule

When Debug Hub and raw logs disagree, prefer:

1. canonical history/result data
2. stage manifests
3. diagnostics bundles
4. raw logs

Raw logs are evidence, not the primary execution contract.
