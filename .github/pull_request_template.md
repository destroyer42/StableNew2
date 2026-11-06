## Outcome

## Execution class

Narrow / Standard / Architectural

## Model recommendation

Claude Code model + effort; Codex model + effort; why this is the lowest tier likely to finish the package; expected usage (order of magnitude).

## Architecture and invariants affected

## Controller-surface effect

## Focused validation

## Required CI

## Acceptance and evidence boundary

Rule: `AGENTS.md` section 8. Write N/A, NOT RUN, NOT TESTED or HOLD where that is the truth; passing CI is not qualification.

- Accepted outcome: <observable result and disposition>
- Evidence mode: <documentation inspection | deterministic test | simulated desktop/integration | physical runtime | operator-reviewed output | NOT RUN>
- Evidence identity: <exact source SHA; named tests, logs or accepted archives>
- Qualification claim: <QUALIFIED + accepted verdict reference | N/A | NOT TESTED | HOLD>
- Not demonstrated: <scope this evidence does not establish>
- Owner decision or blocker: <decision or blocker, or N/A>
- Existing evidence reused: <source SHA and why it still applies, or N/A>

## Known non-blocking debt

## Unrelated user work preserved

## Follow-up

## Model / usage

Per `docs/AI_MODEL_SELECTION.md`: the window starts before repository discovery and ends after closeout; tokens only.

- Sessions: <host:id for every participating session; name any shared-session window>
- Model and effort: <actual model + effort>
- Repair passes and result: <n; PASS | FAIL | BLOCKED>
- Measurement window: <task-start, recorded before discovery> to <closeout-end>, ISO 8601 with timezone
- Measured tokens: <`python tools/usage_report.py --since <task-start> --until <closeout-end> --session <host:id> --line` output, or UNAVAILABLE and why>
