# IMG-MODEL-EVIDENCE-760 — Model evidence and qualification proposals

Execution profile: Architectural integration, Local/Desktop. Model recommendation:
Claude Code Opus 5.5 High / Codex GPT-6 Astra High; cross-subsystem identity,
untrusted research, immutable provenance and Learning admission favor reliability
over nominal model cost. Expected usage: about 30M cache-read / 150k output.

Start: 2026-10-27T06:20:15.401-04:00 (platform session timestamp, recovered from
the session metadata; covers discovery). Primary Codex session:
01a17cdf-f84a-72b1-8256-da7a55026495. Parent: 99372c89b39509a293cb1c33a505b5e82983def6.
Dedicated branch: `codex/img-model-evidence-760`. Existing main checkout and its
two untracked assessment documents are preserved. Feature publication and PR
creation are authorized; integration and physical execution are excluded.
Actual primary/reviewer model: GPT-6.1 Sol High (inherited session setting).
Isolated security session: 01a17ce5-2341-7e61-b323-7604b3bb069f.
Automatic approval-review telemetry: 01a17ce0-5893-7aa2-97e6-679650c5fd97.

## Approved architecture decision

The owner request authorizes an evidence catalog behind Research and saved
qualification drafts in the existing Experiment Library. AssetRegistry remains
the only discovery/hash authority; observation is provisional. Versioned claims
retain source, scope, confidence, reviewed date and translation caveats. Catalog
refresh does not apply profiles, enqueue work, publish Learning or change runtime
support. Existing immutable executable profiles own Klein and Z-Image recipes.

Catalog and network boundary live in `src/assets/` and `src/generation_profiles/`;
pure gap planning and proposal serialization live in `src/learning/`. Tk only
presents projections and starts cancellable workers. Proposed experiments use the
existing Learning baseline, Preview, execution, JobService, SQLite and ratings.
No new SourceKind, queue, profile kind, runner or rating store is introduced.

Controller Surface Assessment: AppController and the Learning controller must
not gain inline catalog/planner responsibilities. A small view entry point opens
a separate catalog window. Ordinary snapshot provenance and strict compile checks
carry frozen proposal facts through the existing path. Ratchets cannot be raised.

## Token-Efficient Validation Plan

1. Hermetic Python 3.14 fixtures for identity, claims, bounded network failures,
   deterministic proposals, restart, compiler parity and fake queue admission.
2. Reuse existing profile, Learning, rating/publication and registry tests where
   their implementation remains unchanged; add regressions for integration seams.
3. At source freeze run the canonical PR gate once, aggregate review and security
   review; batch confirmed in-scope repairs and rerun affected tests.
4. Check final diff/ref/worktree, required hosted `required`, `full-suite` and
   `windows` checks. Report missing evidence without claiming qualification.

No GPU, model load/download, process lifecycle change or real generation is
authorized. Research coverage is not executable qualification. Missing historical
provenance remains missing. Geometry findings stay outside Learning publication.
