# Decision register

Rule: only items traceable to the owner's words or a repository authority are **ACCEPTED**. Proposals stay **PROPOSED** and are not decisions. Assessment verdicts are not owner decisions ("Neither verdict authorizes anything", GUI-PORT-742/743).

IDs: `DR-A#` accepted · `DR-P#` proposed (this research) · `DR-O#` open owner question.

## Accepted (recorded elsewhere; restated for traceability)

| ID | Decision | Date | Source | Alternatives rejected | Implication for this research |
|---|---|---|---|---|---|
| DR-A1 | Canonical path `Intent → Compiler → NJR → JobService → Queue/Repository → run_njr → Handler → Artifacts/History`; GUI captures intent and renders projections; fresh work is queued | standing | `AGENTS.md` §2 | second queue/runner/history authority | Every candidate shell binds to existing ports; AI cannot submit |
| DR-A2 | Approved Comfy workflows are production video backends; experimental needs the job's own opt-in, never a global switch | 2026-10-20 | `AGENTS.md` §2, `STATUS.md` decision 10 | global experimental switch | Auto engine choice must respect governance state and per-job opt-in |
| DR-A3 | Composition-root decision (11) accepted for the **Tk production host only**; does not authorize Qt or a second GUI host | 2026-10 | `GUI_Ownership_Map` §GUI-SEAM-730; `STATUS.md` decision 11 | n/a | COA B/C need a new decision; no mixed host |
| DR-A4 | Preserve the workflow-centric top navigation and stable tab IDs; "do not rebuild the entire GUI"; do not delete Refiner/Hires/img2img merely because rarely used | 2026-10-22 | GUI audit "Product direction", "Critical appraisal" | big-bang rewrite | **Superseded for research by DR-A15 (2026-11-05).** Still binding on production navigation and tab IDs. The "do not delete rarely used workflows" part is unaffected (DR-P9). |
| DR-A5 | PR-850 is research and documentation only: no Tk→Qt migration, no final toolkit decision, no prototype, no dependency/runtime/production change, no push/merge without explicit authorization | 2026-11-05 | PR-GUI-UX-850 brief §1, §13 | n/a | Scope guard for this directory |
| DR-A6 | AI must not submit directly; approval of an AI plan produces normal Intent; AI imports no queue/repository/runner/NJR | standing + brief | `AGENTS.md`; `AI_ASSIST.md` §8; brief §10 | direct AI submission | Contracts in AI_GUIDED_EXPERIENCE |
| DR-A7 | Offline AI Assist decisions D1–D12 (CPU-only v1, one-shot contained subprocess, hash-pinned models, refusals surfaced, no training capture) | 2026-10 | `AI_ASSIST.md` §1 | cloud/resident server | Any model-assisted tier is offline-only unless the owner reopens it |

### Owner answers recorded 2026-11-05 (in chat, after reviewing the closeout)

Recorded in the owner's words where quoted; implications are this research's reading and are marked as such.

| ID | Decision (owner's answer) | Alternatives not chosen | Implication for this research |
|---|---|---|---|
| DR-A8 | **No** operator requires screen-reader/assistive-tech support or true per-monitor scaling on non-100% displays today. The owner **disagrees that this stops the Qt work** and asks that it be recorded **without assuming Qt work is not still valuable.** | Treating "no requirement" as a stop for COA B | The earlier gate G0 and stop criterion ("stop COA B if no requirement a Tk redesign cannot meet") are **withdrawn** (QT_VS_TK_COAS §5). Qt is justified or not on the *other* Q-C criteria (layout engine, gallery/list virtualization, appearance, maintainability, packaging). Accessibility becomes a measured secondary criterion, not a gate. Q-C stays unmeasured. |
| DR-A9 | The local PR-833 branch (`b986c33c`) **is being reviewed and will be published as its own PR separately.** | Publish with this research; adopt as baseline now; discard | This research does not publish or depend on it. EV-07..EV-10 stay "repaired on a local, unmerged branch" until that PR merges; baselines (B2) run against `origin/main` unless the owner says otherwise. |
| DR-A10 | **Yes**: a claimed job awaiting an unreachable backend gets a distinct "preparing" state. "Running versus held is already a confirmed confusion." | Keep running/held only | EXPERIENCE_ARCHITECTURE §job states: "Preparing" is now an accepted state to design for. It does not exist in the product today; adding it is a separate implementation package (GP833-F1). |
| DR-A11 | **Yes** to model-assisted planning before offline AI Assist qualification completes: "how else will we test the models if not by trying to use them." | Wait for qualification first | Reading, **not** quoted: use is the way models get tested, so a supervised, clearly-labelled evaluation path is wanted. The existing invariants are unchanged unless the owner says otherwise: offline/contained, AI never submits, deterministic validator is the judge, refusals surfaced. **Conflict with repository authority (flagged by the independent review):** `AI_ASSIST.md` composes the service with `allow_candidate=False` and `strict_offline=True`, requires named authorization per model download and per inference, and `STATUS.md` holds qualification on D12b and an ETW canary. A "plan object" is also not one of the three `AssistSuggestion` kinds (`PROMPT_REWRITE`, `TARGET_FIT_ADVICE`, `WORKFLOW_CHOICE`), and invariants 1–2 plus the `ai_assist` import ratchet would need an owner-approved amendment. So DR-A11 records the owner's **direction**; it takes effect only through an owner-approved amendment to those documents and still needs per-download/per-inference authorization (DR-O11). AI also yields to generation (`AI_ASSIST` D10), so a Tier-3 step cannot run while a queued job is RUNNING. |
| DR-A12 | Improvement telemetry: **local** only, **90-day** retention. | (Research's reading, not stated by the owner: network telemetry; the earlier 30-day proposal) | AI_GUIDED §6 retention updated 30 → 90 days. Which signals, and opt-in vs default-on, were **not** stated; the content-free, opt-in proposals stay PROPOSED (DR-P7, DR-O5b). |
| DR-A13 | An approved AI plan offers **two options**: (a) **send to Preview**, or (b) **send to Preview and queue immediately, as if Queue had been clicked.** | Preview only; immediate start only | Both are explicit operator actions on an approved plan. Option (b) must go through the same compile → frozen preview → admission checks as the Queue button; the AI itself still never submits. AI_GUIDED §1/§2.4 revised. **Departure to confirm:** `EXPERIENCE_ARCHITECTURE` §5 item 1 (and the shipped rule "Add to Queue — frozen plan shown first") assume the operator sees the frozen preview before queueing; "queue immediately" compresses that into one click. `AGENTS.md` allows immediate start only via enqueue, so the path is compatible, but whether the preview must be displayed/acknowledged first is **unanswered** (DR-O6b(d)). |
| DR-A14 | Test participant: **only the owner.** | Owner plus outside testers | All usability evidence is single-operator (n = 1). VALIDATION §5 revised: repeated sessions replace "≥ 5 participants"; learning effects and expert bias must be reported; no claim of generalization to other operators. |
| DR-A15 | **Yes**, the PR-850 mandate supersedes the 2026-10-22 "preserve top-level groups and stable tab IDs" direction, **for research.** | Keep DR-A4 binding on research | DR-A4 is no longer binding on IA *research*. Production navigation, tab IDs and saved workspace state remain untouched until a separate owner decision. |
| DR-A16 | **Yes** to raising the declared minimum window height (e.g. 680 → 760) if compaction cannot give a usable work area. | Hold 680 permanently | Conditional: only after compaction is measured at 1280×680 (layout recommendation P1–P3, P6). No new height was chosen. A production change needs its own package. |
| DR-A17 | The layout recommendation's "Not recommended" list (no toolkit move, no re-theme, no per-user layout editors) is a **prior opinion to be re-tested**, not a constraint. | Treat as binding | QT_VS_TK_COAS and DESIGN_SYSTEM_CANDIDATE may evaluate all three. |
| DR-A18 | Baseline runs **B1–B5 re-authorized** (the brief had excluded the journey suite for the documentation-only validation). | — | Local host, loopback fakes only; no GPU; no restart of the owner's running application. Serialize with any running gate (see RESEARCH_LOG). B1 done (EV-14). B2–B5 pending. |
| DR-A19 | PySide6 is believed to be installed already; **reuse that harness** (`C:\Users\rob\qual\gui-port740-env`) or reinstall in a local environment if needed. | Fresh install | Verified present and importable (EV-39), PySide6/Qt 6.12.0 on Python 3.14.9. **Research's reading:** gate G3's "install authorized" is treated as satisfied for environment use because the owner allowed reuse or reinstall; the licensing/module review it also requires is **not** done. This does not by itself authorize a prototype; building one is still a separate go (DR-O12). |
| DR-A20 | Independent counter-review by a **sub-agent is authorized.** | — | Run once the owner-answers fold-in is committed (RESEARCH_LOG). A sub-agent is still the same model family; it is *more independent* than the authoring pass, not fully independent. |
| DR-A21 | Task scripts **T1–T9 approved** as written (VALIDATION §4). | — | Scripts are fixed; changes now need an explicit amendment. |

## Assessment verdicts (not owner decisions)

| ID | Verdict | Source | Status |
|---|---|---|---|
| AV-1 | GUI-QT-001: NO-GO/DEFER production migration | 2026-10-25 | Recommendation; owner selection (A or B) not recorded in repository |
| AV-2 | GUI-PORT-740: CONDITIONAL GO for a separately approved bounded Qt package | 2026-10-30 | No record of a separate approval was found (742 followed) |
| AV-3 | GUI-PORT-742: NO-GO for production Qt migration *on current evidence*; reopen by product decision on accessibility/per-monitor scaling | 2026-10-31 | Recommendation |
| AV-4 | GUI-SEAM-743: NO-GO on tuning the Tk pump | 2026-10-31 | Recommendation; says nothing about Q-C (QT_VS_TK_COAS §1) |

## Proposed (NOT accepted)

| ID | Proposal | Evidence | Alternatives | Rationale / unresolved |
|---|---|---|---|---|
| DR-P1 | Organize by operator intent: Create · Edit/Improve · Animate · Experiment · Library/History | EV-30; EV-15 | keep current groups; add only Library | Test by card sort and first-click (VALIDATION T4) before adopting |
| DR-P2 | One anchored primary-action bar per task state | EV-14, EV-17 | fixed strips only where needed (existing pattern) | Needs a measured below-fold problem on `main` |
| DR-P3 | At most two disclosure levels; no admission-required control hidden | EV-19 | status quo | Unknown whether any required control is hidden today |
| DR-P4 | Promote Library/History to a destination | EV-30, library workflow | keep inside Pipeline | Usage data absent |
| DR-P5 | Collapse Operator Log into a status drawer | EV-14 | shrink fonts/rows at small heights | Needs chrome-ratio baseline |
| DR-P6 | Three AI tiers with deterministic validation and per-step approval | EV-35..37 | deterministic-only | Contracts only; no model qualified |
| DR-P7 | Opt-in, local, content-free improvement signals | AI_GUIDED §6 | none (offline comparator only) | Privacy requirements pre-conditions |
| DR-P8 | Chrome budget ≤ 20% of the 680 px **client** height | EV-14 (pixel-measured: ≈ 33% of client height today) | other numeric target | The 20% target itself is a hypothesis; the measurement is no longer by eye. Re-baseline on `origin/main` layouts for Learning/Review (EV-14 origin note) |
| DR-P9 | Simplify by hiding/relocating, not deleting, expert workflows (Matrix, special studies, Motion Library, Storyboard JSON, experimental workflows) | DR-A4; audit | retire some | Retirement is a separate owner decision |
| DR-P10 | One scroll-page contract for every tab, with nested lists capped below viewport height at small windows (layout recommendation **P1**) | EV-16, EV-38; PR-831 fixes | fix wheel capture per widget | Assistant-authored; strongest evidence; needs the wheel probe on `origin/main` first |
| DR-P11 | Compact chrome at small heights and collapsible Operator Log/Status drawer (**P2, P3, P4**), with the chrome budget re-based on EV-14 (global ≈36%, Learning pane ≈62% below the fold) | EV-14 | raise min height only (DR-A16) | Interacts with DR-P5/P8 |
| DR-P12 | Anchored action bar for tab primary actions (**P5**) and a layout regression lane (**P7**) | EV-17, EV-18 | status quo | P7 extends the 760 reachability tests to Learning, Video and Pipeline |

## Open owner questions

| ID | Question | Why it matters |
|---|---|---|
Answered 2026-11-05 (kept for traceability): **DR-O1 → DR-A8, DR-O2 → DR-A9, DR-O3 → DR-A10, DR-O4 → DR-A11, DR-O5 → DR-A12 (partly; see O5b), DR-O6 → DR-A13 (see O6b), DR-O7 → DR-A14, DR-O8 → DR-A15, DR-O9 → resolved (EV-27)**. Additional owner answers: DR-A16 (minimum height; this was "question 10" in chat), DR-A17 to DR-A21.

| ID | Question | Why it matters |
|---|---|---|
| DR-O5b | Which telemetry signals are wanted (AI_GUIDED §6 lists candidates), and is collection **opt-in** (off until enabled) or on by default for the owner's own installation? Is "view / export / delete all" required? | DR-A12 fixed only locality and 90-day retention. Privacy requirements (no content, no paths) are proposed, not accepted. |
| DR-O6b | For "Send to Preview and queue immediately": (a) is it offered for Tier 3 steps one at a time, or only Tier 2 plans? (b) is it hidden/disabled while any step is `needs operator input` or `incompatible`? (c) which button is the default focus? (d) must the frozen preview be displayed (or acknowledged) before the immediate queue takes effect? (e) AI yields to generation: should the button be disabled, or queue only, while another job is RUNNING? | Approval boundary details; "as if Queue had been clicked" must still pass frozen-plan admission. |
| DR-O11 | `AI_ASSIST.md` and `STATUS.md` hold model qualification on D12b and an ETW canary. DR-A11 wants model-assisted planning before qualification completes. Which wins, and what exactly may be enabled (CPU-only v1 models, which ones, labelled "unqualified", behind which switch)? | This research cannot change a repository hold. A future AI package needs the answer. |
| DR-O12 | Is building the **COA B Qt prototype** and a matching Tk build now authorized, given G3 environment use is satisfied (DR-A19)? The brief's "no prototype" and "stop at research-foundation acceptance" still stand unless you lift them. Also: has anyone reviewed the **PySide6 module set / licensing** (the existing env includes WebEngine and PDF)? | Gate G4. Without a go, the Qt work stays at framing plus the baseline measurements. |
| DR-O13 | What is the target **declared minimum** if compaction fails: a value (760?) or "to be set from measurement"? Is 1280 width fixed? | DR-A16 is conditional; a number is needed before it can be tested. |
| DR-O14 | Which layout proposals (P1–P7) do you pick for implementation? That choice belongs to the layout recommendation's owner session, not this research; recorded here so the research does not select by default. | Packaging (PR-GUI-SCROLL-CONTRACT, PR-GUI-CHROME-COMPACT, PR-GUI-LAYOUT-LANE). |
| DR-O15 | What does "modern appearance" mean for you (pick examples of apps you consider modern) and what packaging constraints apply (installer size, license)? | Q-C cannot be scored without a target; QT_VS_TK_COAS G0 residual. |
