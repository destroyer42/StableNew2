# Cross-workflow qualification campaign (PR-QUAL-SYSTEM-840)

Operator-only tooling in `tools/qualification/system840/`. It builds the qualification ledger, freezes per-arm physical
plans, gates every physical arm on an exact owner authorization plus a typed launch, archives attempts immutably and
compares accepted evidence read-only. It adds no queue, runner, cancellation manager, runtime owner or History store,
changes no production behavior and promotes nothing. A successful test is evidence, never an authorization to promote a
model, change runtime governance or enable a feature. Pytest and CI never reach a GPU, runtime, model download or
physical arm.

## 1. The ledger

`tools/qualification/system840/ledger.v1.json` is the machine-readable record of every capability: identity,
reachability, evidence (each item cites its source file, date, exact source and the identity it applies to), the
resource / quality / integration qualification, governance, holds, the next smallest admissible test and confidence.

```text
python -m tools.qualification.system840 ledger --check --live      # validate + reconcile with live catalog/registry
python -m tools.qualification.system840 ledger --json              # full machine-readable dump with definitions
python -m tools.qualification.system840 ledger --model-root D:\models [--hash]   # read-only installed-asset inventory
```

Statuses (`statuses.py` holds the definitions): QUALIFIED, PARTIALLY QUALIFIED, FEASIBLE, INCONCLUSIVE, NOT TESTED, HOLD,
NO-GO, UNSUPPORTED. The validator enforces what the campaign forbids:

- A status is **derived** from applicable physical evidence; merged source, green CI, a decodable artifact or an old result
  for a different model/workflow/runtime revision never supports one (`applies_to` must equal the entry's identity).
- Physical evidence must record its exact source; `unverified:` sources can never support QUALIFIED.
- QUALIFIED additionally needs production-workflow evidence taken **through the operator GUI**; a driver-path run reaches
  PARTIALLY QUALIFIED at most. A standalone feasibility PASS is evidence of the model, not of StableNew's GUI, queue or adapter.
- HOLD names standing holds; a held, NO-GO or UNSUPPORTED capability has no authorizable next test.
- `--live` compares recorded governance and AI registry claims with live code. Live state wins: drift is reported, never
  silently adopted.

Changing a status is an owner-accepted edit of the JSON in a reviewed commit. No command here edits it.

## 2. Arms, plans and approval

Arms: `IMG-Q0..Q4`, `VID-Q0..Q5`, `AI-Q0..Q3` (`arms.py`). Each stage is `canary` (smallest meaningful eligible workload,
one dispatch, full telemetry and teardown proof; inspect before expanding) then `coverage` (only after a canary PASS and any
separate owner approval). GPU arms never run concurrently; GPU and CPU inference (AI Assist, Smart Review) never share a
session, and CPU inference yields to any GPU generation.

`plan` freezes one arm stage: exact Git SHA and working-tree diff digest, backend, workflow id/version, model path, size and
SHA-256, runtime identity and ownership (managed or external), source assets with SHA-256, prompts, seeds, settings,
geometry/frames/fps, jobs and artifacts, RAM/commit/VRAM/disk/duration limits, telemetry cadence, the stop policy
(`retry: never`, `downgrade_after_resource_failure: never`) and the evidence directory. The digest covers everything except
`digest`, `generated_at` and `authorization`; any change needs a new digest and a new approval. Targets whose ledger status
is HOLD/NO-GO/UNSUPPORTED, offline arms and structurally held targets (Z-Image, Wan A14B, Comfy still images) are refused.
AI plans additionally freeze `cpu_only`, `network: denied`, the protected-interpreter attestation and the exact offline
command (checked against the production closed flag vocabulary and `--offline -ngl 0`); each approval names exactly one
candidate model, so a Qwen grant never launches LFM3 and vice versa.

Three separate acts precede any physical dispatch:

1. **Plan** — `python -m tools.qualification.system840 plan --arm ... --stage ... --targets targets.json --out plan.json`
   (writes outside the repository; runs nothing).
2. **Owner approval** — `python -m tools.qualification.system840 authorize --plan plan.json --out auth.json --approved-by NAME`
   is interactive only (refused in CI, under pytest and without a terminal) and needs the exact `APPROVE <arm> <digest12>`
   phrase. An authorization file is a record, not proof of who typed it; the controls are procedural, and **an agent never
   issues an authorization** (`AGENTS.md` section 5).
3. **Typed launch** — `RUN <digest12>` at launch time, accepted only after the approval and never satisfied by the approval phrase.

## 3. Readiness, safety and stops

`readiness --plan plan.json [--authorization auth.json]` evaluates the pre-dispatch gates: endpoint readiness and ownership
(an external runtime is observed through its API only; StableNew never starts, stops, adopts or restarts it), no active
generation, frozen identities (repository, model, sources, launch flags), host RAM/commit, GPU memory, disk, telemetry and
fault collection, no unresolved prior safety stop, the authorization, and plan validity. AI lanes additionally require an
ACTIVE capture from a protected interpreter with a passing canary under 24 h old; a missing protected capture or
incompatible runtime is HOLD, never a reason to disable the guard.

Stop classes: device loss, allocation/OOM, host commit pressure, low RAM, identity mismatch, timeout, unsafe teardown,
telemetry gap, operator cancel, ambiguous dispatch. A stop halts the arm and its dependents; a safety stop also halts every
later GPU arm of the session. Nothing is retried, an ambiguous dispatched POST is never replayed, and settings are never
lowered or models substituted after a resource failure. Unrelated accepted evidence is untouched.

## 4. Evidence and verdicts

Evidence root (outside Git): `%USERPROFILE%\Videos\StableNewAcceptance\QUAL-840\` (override `STABLENEW_QUAL840_ROOT`).
Every attempt is a new `<arm>_<UTC>_<digest12>_<random>` directory: it is created as `.partial` with the frozen plan saved
first, grows by copy-only additions, and is sealed once (atomic manifest, `COMPLETE` marker, rename). `verify <dir>` checks
sizes and SHA-256; an unsealed, truncated or tampered archive is INCONCLUSIVE, never PASS. Computed verdicts are written
beside the attempt (`<attempt>.verdict.json`), never inside it.

Six dimensions: functional correctness, runtime/resource safety, artifact/media integrity, reproducibility/provenance,
visual or suggestion quality, operator usability. Automated measures decide only the first four; quality and usability
stay `PENDING_OPERATOR_REVIEW` until a signed human rating exists. A status proposal (`verdict.propose_status`) never
changes the ledger and always reads `promotion: NOT AUTHORIZED`.

## 5. Comparator

`compare BEFORE AFTER [--out comparison.json]` is read-only. Attempts align only on arm, stage, benchmark version and every
case's model/workflow, prompts, source hashes, seeds, settings and geometry; otherwise it is not comparable (exit 5).
Hardware/runtime differences make timing and resource metrics inconclusive; a single stochastic quality sample is never an
improvement; the output never claims significance and is written apart from the raw evidence (never inside either
archive, never over a file). Exit 0 no degradation, 1 degradation, 5 not comparable.

## 6. What this PR does not do

`run` dispatches through an adapter. Only `SimulatedAdapter` (dry run, tests) and `UnwiredAdapter` (refuses) ship: each
retained harness keeps its own authorization gates and is run by the operator (the ledger's `next_test.harness`). Wiring a
physical adapter per arm is a follow-on that needs its own authorization and physical verification. `dry-run` validates
the whole coordinator on synthetic assets with a simulated adapter and approvals valid only for its temporary plans.

Physical generation, protected AI inference, model acquisition, Z-Image, Wan A14B, Character Training, retired
AnimateDiff/LTX execution and every production promotion each require their own current owner authorization.
