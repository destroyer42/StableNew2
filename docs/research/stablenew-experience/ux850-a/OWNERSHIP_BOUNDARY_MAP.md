# Ownership and architectural boundaries

**No architecture change.** Baseline sources E01–E84 resolve in [SOURCE_INDEX.md](SOURCE_INDEX.md). Current AGENTS/STATUS override older design prose. The outer path remains:

`Intent → Compiler → immutable NJR → JobService.submit_njrs → SQLite Queue/Repository → PipelineRunner.run_njr → Handler → Artifacts/History`

Production construction is launcher E63 → factory E26 (one root dispatcher) → AppController service construction E27 (repository-backed queue, `require_normalized_records=True`) → submission E25 → runner E61. Preview admission E42 preserves the frozen envelope. GUI records intent/projects state; controllers coordinate services; adapters own backend details. This is a static trace, not full negative-path execution.

## Boundary and negative-case map

| Boundary | Existing owner / current evidence | Redesign constraint and negative case |
|---|---|---|
| Compile/admission | PromptPack builder E41; Pipeline preview E42; masked E10; sequence E14; movie E49; JobService E25 | One canonical submission boundary; invalid type/duplicate IDs refuse before batch commit. No GUI payload builder or direct runner |
| Mutable lifecycle | JobRepository E62; JobQueue/history are projections E27 | New campaign/Library status is derived, not another lifecycle. Readiness/admission labels do not become new persisted job states |
| Execution and replay | PipelineRunner E61; strict sequence resume E16/E80 | Replay gets new identity/lineage. Changed shots cannot silently reuse a checkpoint for another plan |
| Cancellation / retry | JobService E71; client ambiguous generation handling E58 | Cancellation signals existing owner; return-to-queue requires positive no-dispatch evidence. Lost generation response does not authorize automatic POST replay |
| Process ownership | WebUI stop E59 checks owns_process; Comfy restart E60 refuses unowned process | Playbooks may observe/interrupt through supported API, never adopt or restart arbitrary external processes. No OS action taken in this assessment |
| Navigation / UI thread | MainWindow notebook/select_tab E68; factory dispatcher E26; AppController movie handoff E76 injects tracked worker/GUI callback | Reuse tab identity/one dispatcher and asynchronous work. A hidden panel must not start a competing hot-state reconciliation loop |
| AI / qualification | Assist production policy E23; availability E74; controlled publication E18/E54 | Operator acceptance of a proposal is not qualification or blanket execution authorization. Candidate inference remains disabled in production composition |
| Model/resource identity | AssetRegistry E69; readiness report E70; current model policy | A friendly model recommendation must preserve executable restrictions, exact resource identities and unsupported-versus-untested distinction |

## Design-relevant durable stores and ephemeral state

This is an expanded **design-relevant inventory**, not an exhaustive “every store” atomicity/concurrency audit. No operator stores were opened. Paths below are repository-defined logical stores; do not copy user data into research reports.

| Store/state | Owner and existing integrity basis | Extension boundary / evidence gap |
|---|---|---|
| Job NJR/lifecycle/order/lineage | SQLite JobRepository E62; admission E25 | Canonical executable/history authority; no copied common Library job store |
| PromptPack JSON/settings | PromptWorkspaceState E08, ConfigManager E09, native storage documented E39 | Explicit self-contained/shared/temporary save scope; preserve slots/unknown fields; recovery is separate from overwriting saved packs |
| Working config / selection | AppStateV2 / existing GUI projections, profile application E06 | Ephemeral intent; scoped locks/provenance must not mutate admitted NJRs or override hard policy |
| Profiles, favorites, startup document | GenerationProfileStore E07; publication E18 | Immutable Learning revisions; explicit later select/favorite/apply; rollback UX needs approval without rewriting evidence |
| UI geometry/tab/Learning resume | UIStateStore E24 | Atomic file helper is present; saved-ID fallback and error visibility require preservation; no general crash-recovery claim |
| Photo originals, sidecars, candidates, staging/manifests | PhotoOptimizeStore E12/E45, per-asset locks | Working Baseline is not a universal Final/favorite; archive/restore not permanent media deletion |
| Storyboard documents and lock files | StoryboardStore E13; authoring E37 | Versioned saves/root checks/stale-write refusal; continuous autosave and portable embedded media not implied |
| Sequence checkpoint ledger/media evidence | E80 writes ledger; E16 verifies identity/files for new resume NJR | Not canonical job lifecycle; never rewrite original checkpoint as a changed plan |
| Motion manifest, managed copies, thumbnails | MotionLibraryStore E50; E28 documents partial/orphan and alias rules | Source originals read-only; unknown/new manifest versions refused; Library collection deletion is separate policy |
| Learning session/meta/index and batch admission | ExperimentStore E55; batch E73 | Saved exact IDs/revisions/approval fingerprints must reconcile canonical jobs before continuation |
| Append-only evidence/rating records | LearningRecordWriter E56; current revisions E22 | Preserve original records; current ratings count once. fsync/append still has hard-reset tail/concurrency limits documented in E30 |
| Discovered groups, review/selection events, scan index | E82/E83/E84; living Learning persistence table E30 | Supplemental observational evidence, not controlled/independently qualified trials |
| Run/artifact metadata, manifests and review stamps | Existing artifact/result contracts, E30 and Review living doc E29 | Preserve source/provenance and missing states; derived presentation cannot invent parent identity |
| Model/LoRA/embedding registry snapshot and hash cache | AssetRegistry E69 | Separate resource identity from generated assets; installing/refreshing resources is outside this package |
| Runtime defaults, prompt catalogs/style metadata, model evidence sidecars, diagnostic exports | Existing config/resource/report owners, E09/E64/E69/E30 | Additional stores screened by docs/map only; full corrupt-write/concurrent-restore/secret-boundary audit incomplete |

No user migration, cleanup, schema change, runtime restart or data deletion is proposed. Future imported research must preserve external provenance and independent sample identity without forging local jobs or qualification. New archival/deletion policy must resolve dependencies among jobs, evidence, managed copies, linked originals, profiles and Storyboards before any destructive action.

## Decisions retained for later contracts

UX-DEC-004 versus prior DR-A24 confirmation direction; production navigation/stable-ID transition; lock precedence/schema and fallback; campaign approval scope/expiry/continuation; evidence comparability/072 sufficiency; evaluator validation; archive/delete/import trust and portable verification. These choices do not prevent an honest current baseline. A toolkit migration or ownership change requires a separately approved Architectural package; the research provides no authority to start one.
