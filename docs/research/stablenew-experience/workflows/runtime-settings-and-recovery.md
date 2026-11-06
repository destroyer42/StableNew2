# Workflow W9 — Runtime, settings and recovery

**Discovery status: OPEN.** Last updated 2026-11-05.

## Observed current state [V/D]
- Persistent header (Run, Stop, Preview, Settings, Refresh, Help Mode, Debug, Readiness), group navigation, "About This Tab", and a bottom zone (Operator Log with Details toggle and warning count; Status with progress bar, WebUI state, Launch WebUI, Retry, Crash Bundle). Visible in every retained screenshot; together about a third of a 1280×680 window (EV-14).
- Runtime safety: endpoint lifecycle, backend-scoped outage containment with startup hold, GPU device-loss quarantine, shutdown admission fence, managed-Forge identity attestation. External A1111/Comfy are never adopted, restarted or killed; ambiguous dispatched POSTs are never replayed.
- OPS-01 (partial journey): backend unreachable/dropped/rejected, changed model, close during generation, reopen and reconcile. On `main` it fails by design on `failure_cause_visible_to_operator` (EV-08) and records a running-vs-held mismatch (EV-09). Local 833 repairs both and adds GP833-F1 (no "preparing" state) as an owner decision.
- Resource-preflight refusal not driven by any journey (EV-12). Queue pause/resume/cancel integration-only.
- Settings: Engine Settings (Application Defaults: default output folder), Startup Defaults, current-job overrides (EV-21).

## Owner direction (brief)
Prerequisite failures with actionable diagnostics; inline errors with causes and next actions; queue status visible without excessive log space; distinct current-job overrides, model profiles and startup defaults.

## Confirmed decisions (repository)
Cancel and Return requeues only on positive dispatch evidence; otherwise cancelled and action-required. A durable CANCELLING status is an **open owner decision** (decision 11). GPU hold lifted 2026-10-18; device-loss quarantine remains.

## Hypotheses [H]
H1: A single *Status & Readiness* surface answering "can I run this now, and if not why?" replaces Readiness window + status bar + banner + log lookups. H2: The Operator Log should collapse to one line by default and expand as a drawer (already partly so: Details toggle). H3: Recovery actions (Retry, Launch WebUI, Return to Queue) should be offered next to the error that needs them.

## Alternatives
(a) Keep layout, shrink chrome at small heights. (b) Replace Operator Log row with a status drawer. (c) Make readiness a pre-flight panel adjacent to the primary action.

## Flows
Current: Run/Queue → problem appears as banner/log/status text → open Readiness/log for cause. Ideal: PENDING.

## Discovery contract — status
1–5 PENDING · 6 Expert: Debug Hub, Crash Bundle, runtime settings · 7 Duplicates: readiness shown in four surfaces · 8 Reuse: n/a · 9 AI: Tier-1 "explain this failure" candidate · 10 Boundaries: no adoption/kill of external runtimes · 11 This workflow *is* failure explanation · 12 Artifact: restored operability · 13 Acceptance: none.

## Open questions
Q1 Which failures are frequent for the operator in practice? (no frequency data) Q2 Should recovery ever offer actions that StableNew is not permitted to take on an external runtime? Q3 Owner decision on GP833-F1 and on a "preparing" job state.
