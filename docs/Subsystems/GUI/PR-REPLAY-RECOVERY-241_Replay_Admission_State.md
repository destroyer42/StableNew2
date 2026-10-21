# PR-REPLAY-RECOVERY-241 — Replay admission state

## Execution Profile + Model/Reasoning Recommendation

Standard, bounded repair of the existing Replay Job handoff. Model recommendation:
Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh. Local/Desktop fits the existing
Windows checkout and Tk validation. Expected usage: about 3M cache-read and 15k output
tokens. The admission and draft-state boundary warrants lifecycle-aware reasoning.

## Behavior and boundary

Replay Job compiles a new identity from the stored NJR, retaining parent lineage,
and submits it through JobService. It does not replace Pipeline Preview, edit the
draft, or overwrite the draft's last-run configuration, whether admission succeeds,
returns zero or raises. Its submission source is history_replay, so an original
Run Now action does not grant a new immediate-start policy. Normal queue auto-run
and dispatch holds still apply.

The compact History panel and Browse All report success only after the controller
confirms admission. Refusal and failure are visible beside the History actions.
Queue acceptance does not claim execution has started or completed.

This package adds no editable historical jobs, resource reconstruction, resource
identity guarantee, persistence model or runtime authority. Replay with Changes
remains on HOLD pending its separate resource-eligibility decision.

## Controller Surface Assessment

HistoryHandoffService owns hydration and submission. PipelineController loses its
two draft-state arguments; its ratchet ceiling falls by two lines. AppController's
zero-result log names admission refusal as well as missing snapshots. No new
controller responsibility or ceiling increase.

## Token-Efficient Validation Plan

Focused service/controller tests cover new identity, unchanged executable config
and seed, lineage, refusal/exception/success draft preservation, queue policy and
batch isolation. GUI tests cover truthful admission feedback in the shared panel.
Run the canonical gate once after focused checks. No production queue, runtime,
GPU, filesystem migration or physical generation is exercised.

## Validation evidence

67 focused tests and 21 image/video replay integration tests passed. Canonical gate
checks passed through isolated collection (10,885 tests, repository unchanged).
The required smoke completed with 349 passing tests after allowing its test-owned
loopback fake backend outside the sandbox. The first gate attempt identified
formatting/ratchet updates; a second encountered sandbox temporary-directory and
loopback restrictions. No gate/test contract was weakened. Hosted CI and the full
census are pending publication, which is not authorized by this package.
