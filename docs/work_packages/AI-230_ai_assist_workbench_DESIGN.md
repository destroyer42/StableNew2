# AI-230 (design for review): AI Assist workbench - tabs, one-step apply, undo, and a robustness pass

Status: **design for owner review. Not authorized. No code is written until the owner approves it and answers the decisions
in section 7.** Dated 2026-11-25. Builds on AI-202, AI-210/211 (plan advice), AI-212 (slot variety) and AI-213 (new slot
proposals, merged in PR 398). Truth after any merge lives in `docs/Subsystems/AiAssist/AI_ASSIST.md`.

## 1. Why: what the owner found by using it

1. **The window is crowded.** One scrolling window stacks three request buttons, Advise plan, Slot variety (with a slot
   checklist), New slot, a status line, a runtime-detail toggle and a 22-line text box. Everything is visible at once and
   nothing says which part you are in.
2. **Accepting is hard to find, and every function accepts differently.** Rewrite uses the bottom **Accept rewrite** button;
   variety and new-slot need you to select a list row and then press a button beside the list; Advise plan only has **Copy step**.
   The bottom Accept button stays disabled for three of the four functions. A refused or rejected proposal shows no button at all.
3. **New-slot proposals were refused for the wrong reason.** The AI-213 judge refuses any proposal that takes the matrix past
   its combination limit. The planner's own behavior (`plan_matrix_expansion`) is that the limit only **caps how many
   combinations compile per prompt row** (`selected = min(theoretical, limit)`); it is not an error. A pack whose matrix is
   already past its limit (the owner's, with eight slots) can therefore never accept any new slot. The owner's generation is
   deliberately capped to low numbers, so growth is not a meaningful risk to them.
4. **No undo.** Neither the editor nor the Matrix tab keeps an undo stack, so a mistaken Apply is reverted by hand.
5. **Small trust gaps.** The new-slot review shows an insertion point as an index and a snippet, not the sentence with the
   marker in place; a model refusal hides its reason by design; the dialog is a snapshot opened once and left open while the
   operator changes slots or packs.

## 2. Facts checked in the code (so the plan rests on them)

- One `PromptAiSuggestions` owner and one `AiSuggestionDialog(tk.Toplevel)` (618 lines); `prompt_ai_suggestions.py` is 1,211
  lines. Request, judge, review and stale-check logic already live outside the widgets (`src/gui_v2/ai_*.py`), so the layout can
  change without touching the contracts or the judges.
- Every mutation already goes through one explicit, stale-checked, all-or-nothing path per function (workspace setters for
  rewrite, `MatrixTabPanel.append_slot_value`, `append_slot` + `insert_slot_marker`). Those stay the only writers.
- A new slot is appended **last**; the planner varies the last dimension fastest, so under a cap a new slot is exercised, not starved.
- The Matrix tab already warns about undefined `[[markers]]` (`find_undefined_slots`); nothing warns about a defined slot that no
  prompt uses, or about duplicate values.
- Invariants in `AI_ASSIST.md` section 8 (nothing executable, no edit without an explicit operator Accept, nothing derived from
  prompts persisted, refusals never repaired) are not changed by anything below.

## 3. Proposed design

### 3.1 One workbench, five tabs, one review model

The same window, same single-flight owner, with a tab strip. A persistent header shows the target pack and slot, the Preview
label with the model, and one status line with elapsed time and **Cancel**. Tabs:

| Tab | Holds |
|-----|-------|
| **Prompt** | Rewrite and Target Fit (and Workflow Choice, disabled with its one-line reason until a source exists) |
| **Matrix slots** | Variety and new-slot proposals behind one goal box and a mode switch |
| **Plan** | Advise plan (advice only; Copy step) |
| **Check** | Deterministic matrix and prompt checks; no model (3.5) |
| **Details** | Model identity, last outcome code, "Show runtime detail", what was sent (counts only) |

Every model function returns the same kind of thing to the same list: a **proposed change card**. A card has a one-line summary,
a before/after preview (for a new slot: the sentence with the `[[marker]]` highlighted in place; for variety: the slot with the
new value appended), a verdict (offered, or rejected with the fixed reason), an effect line (for a slot: "possible
combinations A to B; compiled per prompt row: N of B, limit L"), and its own **Apply** button. Cards are checkable;
**Apply selected (n)** and **Apply all offered** sit under the list. Rejected cards are shown greyed with the reason.

```
+- AI Assist  (Preview - Ollama - qwen3.5:4b)   Pack: Neon_After_Dark - Slot 1 ------+
| [ Prompt ] [ Matrix slots ] [ Plan ] [ Check ] [ Details ]                          |
|-------------------------------------------------------------------------------------|
| Mode: ( ) Add values to existing slots   (*) Propose new slots                      |
| Goal: [ with a companion or pet                    ]  [Suggest]   12 s   [Cancel]   |
| Quick goals: lighting - environment - camera - mood - pose                          |
|                                                                                     |
| [x] companion: dog, cat, owl, fox                 4 values   7,200 -> 28,800 possible|
|     ...a knight in a forest[[companion]], wearing armor, at dusk      compiled 8 of  |
|                                                    [ Apply ]                28,800  |
| [ ] pet_mood: rejected - name already used                                          |
|                                                                                     |
| [ Apply selected (1) ]  [ Apply all offered ]              Applied: 0   [ Undo last ]|
| Nothing is saved, previewed, compiled, queued or generated by Apply.                |
+-------------------------------------------------------------------------------------+
```

The three different accept patterns become one: **Apply** on a card. Apply is still an explicit per-press operator action
(invariant 2). There is **no hands-off auto-apply**; the nearest thing is **Apply all offered**, which applies the visible,
checked list in order and stops at the first stale or failed item.

### 3.2 Apply journal and Undo

Each Apply records, in memory only, the exact before/after state of the thing it changed (rewrite: both texts; variety: slot and
value; new slot: slot row plus marker offset). **Undo last** reverses the most recent Apply when the workspace still equals
that Apply's after-state; otherwise it refuses and says why. The journal is cleared on close, pack change, slot change and
visibility change, and never persisted (invariant 7). This replaces "delete the row and the marker by hand" and resolves
AI-213 decision 4 with something stronger than an editor undo step.

### 3.3 Matrix limit: informational, not a refusal

Remove `matrix_limit` as a verdict. Show "possible A to B; compiled per prompt row N of B (limit L, from <source>)". Keep the
structural bounds (slot count, name and value rules, value count). If the owner prefers a guard, it becomes an optional
**soft warning** above a configurable ceiling, not a rejection.

### 3.4 One flow from "no fitting slot" to a proposal

When variety is refused or the selected slot list is empty, the result carries a **Propose a new slot for this goal** button
that switches the mode and reuses the goal text (AI-213 decision 5's "later change"). Quick-goal chips pre-fill common goals;
they are static text, not stored operator history.

### 3.5 Check tab (deterministic, no model)

Cheap, exact, and the highest accuracy-per-effort item: defined slots no prompt references; `[[markers]]` with no slot (existing
logic, reused); duplicate or near-duplicate values (case/whitespace/plural); empty values; values the Matrix editor would
re-parse differently (commas); very unbalanced slot sizes. Each finding has a manual pointer to the Matrix tab row and, for
duplicates, an **Apply** that removes only the exact duplicate (same journal and Undo).

### 3.6 Always-current context

The header and the tab content re-read the current pack and slot on tab focus and on the existing one-second refresh; a change
invalidates any outstanding cards with a visible "context changed" row rather than a silent clear.

## 4. Additional opportunities (ranked)

1. **Check tab (above).** Deterministic, no model, immediately useful. Do first after the shell.
2. **Phrase to slot.** Select a phrase in the prompt ("at dusk") and have the model propose a slot name and values with the
   phrase kept as the first value; Apply replaces exactly that span with `[[slot]]`. This is how an operator really turns a
   prompt into a matrix and is more valuable than inserting a marker between clauses. It **rewrites a span of the sentence**, so it
   needs its own owner decision (section 7, Q5) and the same all-or-nothing, byte-checked rule.
3. **Live "what this slot produces".** For a new-slot card, show the first few compiled prompts using the planner's own
   expansion (`combination_at`), so the operator sees the effect before pressing Apply. No model involved.
4. **Accuracy levers, measured not assumed.** (a) Build a case set from the owner's real packs (the lighting refusal, the
   companion/pet goal, environments) and run it through the existing contract-acceptance harness for Qwen3.5-4B and LFM3,
   recording acceptance, refusal and judge-rejection rates per model. (b) Few-shot examples in the slot framings. (c) Deterministic
   de-duplication of offered values against existing values. (d) An explicit **Ask for more** button instead of any automatic
   retry (invariant: no retry fills a shortfall). (e) Confirm the Ollama request uses a JSON schema or format constraint and
   that the model stays loaded between presses; both are unverified here.
5. **Session-only recent goals** so a goal can be re-run after a stale invalidation. Memory only; cleared on close.
6. **Dock instead of floating (optional).** A side panel in the Prompt tab keeps the editor and Matrix tab visible while
   reviewing. A larger layout change; see Q4.

## 5. Constraints, non-goals, anti-goals

- Unchanged: the contracts, validators, judges' rules (except `matrix_limit` becoming informational), the service, the
  runtime and every protected path (`src/pipeline/`, `src/queue/`, `argv.py`, `RunLimits`, qualification identities).
- Non-goals: automatic apply without a press; saving, previewing, compiling or queuing anything from AI Assist; any new model,
  runtime or provider; a quality claim from demos.
- Anti-goals (would make it a failure even if it works): a second path that writes workspace state around the existing
  stale-checked mutators; any persisted prompt, goal or suggestion text; hiding a refusal or rejection reason.

## 6. Work packages (each independently reviewable; Standard class unless noted)

| ID | Scope | Depends on | Done when |
|----|-------|------------|-----------|
| **AI-230a** | Small fix first: `matrix_limit` becomes an informational effect line; first offered card auto-selected so the Apply button is live; rejected rows listed in the list greyed with reasons. | none | Journey test: a pack already past its limit accepts a new slot; docs and tests updated |
| **AI-230b** | Review model: one `ProposedChange` card type; per-kind adapters over the existing judges and mutators; Apply journal and **Undo last**. No visible layout move. | a | Atomic apply/undo tests per kind; stale after-state refuses Undo; no-log and no-persist tests |
| **AI-230c** | Workbench shell: tab strip, persistent header and status, Details tab, cards list with Apply / Apply selected / Apply all; migrate Prompt, Slots and Plan content. Keep existing widget attribute names where tests use them. | b | Existing journey tests green or deliberately migrated; screenshots on a real display |
| **AI-230d** | Matrix slots tab: mode switch, one goal box, "Propose a new slot for this goal" from a refusal, quick goals, in-context sentence preview, live "what this slot produces". | c | Journey tests for routing and preview |
| **AI-230e** | Check tab: deterministic checks and exact-duplicate Apply. | b, c | Unit tests per check; no model needed |
| **AI-230f** | Accuracy: case set from the owner's packs; few-shot framing; value de-dup; Ask for more; confirm schema/keep-alive. **Needs an operator model run (owner's activation).** | d | Per-model acceptance table recorded; Preview label kept |
| **AI-230g** (optional) | Phrase to slot, only if Q5 is approved. | d | Byte-exact span replacement tests; undo test |

Order: a (ships alone, fixes what you hit today), then b, c, d and e (e can run beside d), then f; g last. Each lands as its own
PR so none is large. Every PR regenerates `docs/CODE_MAP.md`, keeps the `STATUS.md` AI line to one line, and runs the full
required gate; a, b and e need no model or display, and c and d need a short on-screen check by the owner.

## 7. Decisions for the owner (recommendation first)

1. **Matrix limit.** Recommendation: informational only, no refusal and no warning ceiling. Alternative: soft warning above a
   configurable ceiling.
2. **Apply model.** Recommendation: per-card **Apply** plus **Apply selected / Apply all offered**, still one explicit press,
   with **Undo last**. Alternative: no batch buttons, one card at a time.
3. **Undo.** Recommendation: the in-memory apply journal in 3.2 (per session, cleared on pack/slot change). Alternative: keep the
   manual-revert note.
4. **Window.** Recommendation: keep the floating window but with tabs and a larger default size. Alternative: dock into the
   Prompt tab (more work, editor always visible).
5. **Phrase to slot (AI-230g).** Recommendation: yes, as a last, separately approved package, because it is the most useful
   behavior and the only one that rewrites part of the sentence. Alternative: never.
6. **Order.** Recommendation: ship **AI-230a** immediately as its own small PR, then the rest in order. Alternative: do the
   whole redesign before anything ships.
