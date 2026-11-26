# AI-212: suggest more values for a pack's existing matrix slots

Status: work package (execution contract). Truth after merge lives in `docs/Subsystems/AiAssist/AI_ASSIST.md`.

## Objective

- Why: the owner's first two "Advise plan" goals were "Make the settings have more variety, and have the females looks have
  more variety" and "Add more variety to the looks of the people, and add some variety to the pose, lighting". A stage/model
  plan cannot answer either: both are about prompt *content*. The owner's packs keep that content in matrix slots (a prompt
  sentence with `[[character]]`, `[[outfit]]`, `[[location]]`, `[[lighting]]`, `[[framing]]` markers, each slot a
  comma-separated value list in the Prompt tab's Matrix sub-tab).
- Outcome: in the AI suggestion dialog the operator types a short goal and presses **Suggest variety**. The model proposes new
  values for the pack's *existing* slots; deterministic code judges each value; the operator adds valid values one at a time
  with **Add selected value**, and each addition is exactly the edit a person typing `,value` at the end of that slot's
  Values entry makes. Nothing is saved, queued or generated.
- In scope: typed `SLOT_VARIETY` kind (contract, framing, schema, strict validator); a deterministic per-value judge outside
  `src/ai_assist`; a toolkit-neutral review model; one public `MatrixTabPanel.append_slot_value` that drives the panel's
  existing edit handler; the dialog section; tests; `AI_ASSIST.md`, the runbook, `STATUS.md` AI Assist line, `CODE_MAP.md`.
- Explicit exclusions: no new slot, no removal or edit of an existing value, no change to the prompt sentence, slot names,
  matrix mode/limit/seed or enablement; no save; any Intent / compiler / queue path; any change under `src/pipeline/` or
  `src/queue/`; no change to `argv.py`, `RunLimits`, `render_prompt` output for the four existing kinds, the frozen
  qualification identities, `allow_candidate`, `strict_offline` or any ratchet ceiling; no model, binary, GPU or backend is run.

## Execution class and model recommendation

- Execution class: **Standard** (known architecture: a fifth typed kind on the AI-210 pattern plus a narrow GUI surface; the
  matrix edit authority is reused, not added).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High (substantial known-architecture PR,
  `docs/AI_MODEL_SELECTION.md`). Executed by Claude Code Opus 5.5.
- Task start: 2026-11-14T15:27:40Z (first recorded timestamp), Claude Code session `fc805161-6e77-4b96-b330-0c5e989ab72b`,
  started by coordinating session `local_ded6f184-9d33-48d3-876e-43da15db7f73`. Branch `feat/ai-212-slot-variety` from
  `origin/main` `ba108e1f`.

## Controller Surface Assessment

No controller or coordinator code changes. `AiAssistIntegration.submit` is reused unchanged (the judge is pure and cheap and
runs on the GUI thread at delivery, against the matrix state as it is then). `AppController` and the composition root are not
touched: the matrix source is the Prompt tab's own `workspace_state`, which `PromptAiSuggestions` already holds. No ceiling
changes.

## Where the matrix state lives and how acceptance reaches it

- Authority: `PromptWorkspaceState.get_matrix_config()` returns `current_pack.matrix` (`MatrixConfig`, slots of
  `MatrixSlot(name, values)`). The Matrix sub-tab (`src/gui/widgets/matrix_tab_panel.py`) edits it in place.
- The one manual edit path for a slot's values is `MatrixTabPanel._on_slot_changed(index)`: it reads the row's Name and
  Values entries, splits the values on `,` and strips them, writes `slot.name` / `slot.values`, drops the slot's
  `preserved` round-trip keys (`__item__`, `name`, `values`) and calls `on_matrix_changed`, which the Prompt tab binds to
  `_on_matrix_changed` (`workspace_state.mark_dirty()`, quick-insert refresh, slot validation).
- Acceptance therefore calls a new public `MatrixTabPanel.append_slot_value(index, value)`, which refuses when the row's
  entries differ from the state (a pending manual edit), puts `existing + "," + value` into the Values entry and calls
  `_on_slot_changed(index)`. The resulting pack state, dirty flag and refreshes are those of the manual edit by construction;
  a test compares the two state diffs. No code writes `MatrixSlot.values` for the AI path.
- The list-format rules (join with `,`; split on `,`, strip, drop empties) move from the panel into
  `src/gui_v2/matrix_editor_view.py` (`values_text`, `parse_values_text`) so the panel and the judge share one definition.
- Because the manual path re-parses the whole entry, it would split a stored value that contains a comma, convert a non-text
  value to text, or strip a name with surrounding spaces. A slot whose name and values do not survive that round trip
  unchanged is **not offered** (excluded from the request, with a count in the status line), so accepting a value can never
  change an existing value or name.

## Schema (`ai_assist.suggestion/1`, kind `slot_variety`)

Request (`AssistRequest`): `goal_text` (at most 1000 characters, the plan goal's limit) and `matrix_slots`: a tuple of
`(name, existing_values)` pairs, 1 to 12 slots, names unique, 1 to 64 characters, at most 64 existing values per slot, the
names and values together at most 6000 characters (so the frame plus the 768-token answer budget fits the 4096-token
context). No positive/negative prompt, target policy, model list, workflow list or stage list may be set.
`content_class` is `sensitive` when the content-visibility resolver rates the pack name, goal and slot values `nsfw`, the
same resolver call existing prompt requests use.

Framing: the frame's usual header and refusal line; authored DATA between the reserved markers:

```
=====BEGIN_AUTHORED_DATA=====
GOAL:
<goal>
SLOT: <name>
VALUE: <existing value>
...
=====END_AUTHORED_DATA=====
```

The goal, every slot name and every value is refused (`INVALID_REQUEST`, nothing spawned) if it contains a reserved marker
(`=====BEGIN_AUTHORED_DATA=====`, `=====END_AUTHORED_DATA=====`, `POSITIVE_PROMPT:`, `NEGATIVE_PROMPT:`, `GOAL:`, `SLOT:`,
`VALUE:`); a name or value with a line break is refused too. Nothing is rewritten.

Response, ok branch (all payload fields required, `additionalProperties: false`):

```
{"schema": "ai_assist.suggestion/1", "status": "ok", "kind": "slot_variety",
 "slots": [ {"slot": <enum of the request's slot names>,
             "values": [<string, maxLength 80>, ...1 to 6],
             "rationale": <string, maxLength 160>} , ...1 to number of slots ],
 "changes": [optional, as for every kind]}
```

Only constructs proven for b11840 and b11960 (AI-202 section 10.3): `oneOf`, `const`, `enum`, `type` object/array/string,
`properties`, `required`, `additionalProperties`, `items`, `minItems`, `maxItems`, `maxLength`. `minItems: 1` on `slots` and on
`values` means the grammar cannot close an empty answer; the two-field document of AI-202c matches neither branch.

Limits (P3 style, a breach is a rejection, never a truncation):

| Bound | Value | Breach |
|---|---|---|
| goal | 1000 characters | request refused |
| slots in a request | 1 to 12 | request refused |
| existing values per slot | 64 | request refused |
| names + existing values | 6000 characters | request refused |
| slot entries in an answer | 1 to the request's slot count, each slot at most once | `MALFORMED` (`slots_missing`, `too_many_slots`, `slot_repeated`, `slot_not_in_closed_list`) |
| new values per slot entry | 1 to 6 | `MALFORMED` (`values_missing`, `too_many_values`) |
| one value | 80 characters, text, no control characters | `MALFORMED` (`value_too_long`, `value_not_text`, `value_control_characters`) |
| rationale | 1 to 160 characters | `MALFORMED` (`rationale_missing`, `rationale_too_long`) |

`AssistSuggestion.slot_values` carries `SlotValues(slot, values, rationale)`; `to_diagnostics` reports only slot and value
counts.

## Deterministic per-value judge (outside `src/ai_assist`)

`judge_variety` (`src/gui_v2/ai_slot_variety.py`) gives every proposed value one verdict, **offered** or **rejected(reason)**,
against the matrix state read at completion and again at each acceptance. In order:

1. the slot no longer exists, or is no longer offered (not text-editable without change) — `slot_missing`, `slot_not_editable`;
2. hidden by the current visibility mode — `hidden` (the text is not shown);
3. empty or blank — `empty`; leading or trailing whitespace — `surrounding_whitespace`; longer than 80 — `too_long`;
4. a line break or control character — `line_break`; a comma — `comma`; `[` or `]` (matrix markers) — `matrix_marker`;
   `<` or `>` (extra-network tokens) — `angle_token`; `__` (wildcard tokens) — `wildcard_marker`; a reserved frame marker —
   `reserved_marker`;
5. the same as an existing value of that slot (case-insensitive, whitespace collapsed) — `duplicate_existing`; the same as an
   earlier proposal for that slot — `duplicate_suggestion`.

Rejected values are listed with the reason and never offered for acceptance; nothing is repaired, trimmed or reworded.

## Acceptance and the stale check

- Acceptance is one explicit press per value. The snapshot records the pack object, the matrix object and the request-time
  `(name, values, editable)` state of every slot. At each press the current state must equal that snapshot plus exactly the
  values this review has already added; otherwise the review is cleared and acceptance refused ("The pack or its matrix slots
  changed since the request"), as the rewrite path does. The value is re-judged against the current state, then added through
  `append_slot_value`; afterwards the state must equal the expected state with that one value appended, which becomes the
  new expectation.
- Result: the pack is "modified, unsaved" through `_on_matrix_changed`, exactly as a manual edit. Save, Preview and Add to
  Queue stay the operator's ordinary actions.

## Privacy and trust

- Slot names, values, the goal and suggestions are authored text: never logged or persisted. The event record keeps its
  whitelisted fields (`input_chars` counts goal, names and values; `request_digest` is the truncated hash); no new field.
  Existing kinds' digests are unchanged (the slot component is appended only when slots are present).
- "Show runtime detail" keeps its in-memory-only rule. Closing the dialog, a visibility change or a new request clears the
  goal, the review and the detail.
- Every variety surface carries the Preview label when the trust tier is Preview; `qualified` stays false.

## Validation plan

Focused: `tests/ai_assist/test_slot_variety.py` (request bounds and kind exclusivity, framing as data, marker and line-break
refusal, schema shape and empty-answer rejection, validator bounds, service run with the fake child, event privacy),
`tests/ai_assist/test_ai202c.py` extended to the fifth kind (schema keyword list, required fields), `tests/gui_v2/test_ai_slot_variety.py`
(each judge reason, review model, no forbidden import), `tests/gui_v2/test_ai_suggestions_112.py` journey (acceptance equals a
manual edit as a state diff, stale refusal, no save/queue, Preview label, scrubbing), the matrix panel tests. Then
`tests/ai_assist`, `tests/gui_v2`, `tests/system`, `tests/tools` (frozen digest tests unmodified), the ratchet tools,
`tools/ci/run_pr_gate.py`, `git diff --check`, regenerated `docs/CODE_MAP.md`.

## Acceptance and evidence boundary

- Implementation: the code and documents above.
- Demonstration: deterministic tests with fakes only.
- Qualification: none. No model has been run for this kind; whether Qwen3.5 or LFM3 produce useful values, stay within the
  768-token answer budget for a large pack, or fill the grammar sensibly is unverified until the owner tries it.
- Held: any physical inference; anything beyond adding values to existing slots.
