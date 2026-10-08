# PR-LEARN-142 — Model Comparison Evidence Readiness

## Execution Profile + Model/Reasoning Recommendation

Standard, difficult bounded evidence/lifecycle work. Recommended Codex:
GPT-6.1 Sol High; Claude Code: Sonnet 5.5 High. Prefer the current Local/Desktop
host for Tk and repository continuity, with an isolated checkout for validation.
The interacting identity, cache transaction, cancellation and frozen evidence
contracts justify this tier by total successful-work cost, including retries.
An evidence-policy or identity-authority change requires owner review.

## Controller Surface Assessment

LearningController only delegates readiness and forwards its returned
CompileEvidence into existing comparison planning. Candidate path binding and
readiness live in `src/learning/model_evidence_readiness.py`; AssetRegistry owns
file identity, fingerprints, hashing, metadata classification and persistence.
`ComparisonEvidenceTask` owns one worker mailbox; ExperimentDesignPanel polls it
on Tk and validates current selections before publishing Preview. No ratcheted
`src/controller/*` source or ceiling changes.

## Defect and operator trigger

Resource discovery supplies WebUI runtime names, display titles and exact
filenames to AppState. The checklist retains runtime names. Previously Preview
read only persisted checkpoint family evidence; existing ordinary scanners
refresh LoRAs and embeddings, not checkpoints. A cold checkpoint cache therefore
blocked supported targets. Basename-only lookup could also borrow warm evidence
from an inaccessible served file's local namesake.

Build Preview explicitly starts evidence readiness for the selected candidates.
It does not refresh the registry at startup or scan checkpoint directories.
First-use SHA-256 must read each selected non-profile checkpoint in full:
multi-GB files can take minutes, depending on storage. Status reports selected
checkpoint name, evidence provenance and percentage, with Cancel Evidence
available (asset names hidden in SFW mode). Warm selected files
and sidecars use size/mtime fingerprints; no redundant refresh or hashing occurs.
An exact qualified profile retains its canonical identity/policy authority and
does not require a redundant checkpoint hash.

## Identity and classification

API `filename` or filesystem-discovery `path` must be absolute and accessible.
The selected runtime name must agree with that exact file. WebUI's flattened
subdirectory names are accepted only when its title is an exact suffix of the
served path. Missing filenames, duplicate runtime identities, name/path mismatch,
inaccessible external files and explicit SHA-256 disagreement are blocked with
arm-specific guidance. Legacy WebUI `hash` is not treated as SHA-256.

Before hashing, the registry inspects selected stale safetensors headers and
sidecars. Family classification reads only the bounded header, never model
weights or a full-file hash. Rejected/unrecognized candidates need no byte hash.
Eligible cold candidates still require the existing full SHA-256 identity before
Preview; the server's supplied hash does not substitute for registry identity.
An unchanged older cache can acquire structural evidence using header reads
while preserving its existing fingerprint-bound byte hash. Warm current
evidence reads neither headers nor model bytes.

An accessible served filename can be outside the default configured WebUI root,
including managed Forge's separate data directory or referenced model home.
AssetRegistry refreshes that exact file; no Settings changes, basename fallback,
new scanner or external runtime adoption occurs. A filename alone supplies no
family evidence. Registry classification jointly considers explicit metadata
and structural evidence, ahead of filename hints. Unknown descriptive metadata
does not suppress a distinctive structure; contradictory recognized family or
base/refiner claims fail closed. Comparison admission requires explicit metadata
or structural evidence; a filename hint alone is insufficient. ModelPolicy
still admits only evidenced SDXL base envelopes or exact qualified profiles.

`src/assets/checkpoint_structure.py` is a read-only registry helper, not another
model detector/qualification authority. `checkpoint_structure/1` recognizes
the standard LDM SDXL base tensor layout using input `[320,4,3,3]`, conditioning
`[1280,2816]`, context projections `[640,2048]` and `[1280,2048]` including the
deep transformer block, and output `[4,320,3,3]`. Refiner/inpaint and narrow
SD1/SD2 signatures provide exclusion/conflict evidence without qualification.
Partial SDXL signatures do not become base evidence through a metadata override.
Other layouts/formats remain structurally unrecognized. Existing explicit
metadata admission remains available for otherwise valid supported safetensors.

Reference investigation used ComfyUI's
[architecture dimensions](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/supported_models.py)
and [shape inspection](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_detection.py),
corroborated against bounded installed headers. No ComfyUI import, state-dict
loading, model-family resolver or competing scanner is used in StableNew.
Headers are capped at 64 MiB; duplicate keys, malformed descriptors, unknown
dtypes, invalid shapes/offsets, gaps/overlaps and truncated payload extents
refuse admission. No tensor values are read or executed.

## Transactions and lifecycle

AssetRegistry hashes outside the shared writer lock, then holds a cache-path OS
file lock for the brief commit, reloads the latest persisted entries and atomically
merges its result. Existing picker callbacks cannot wait behind multi-GB
checkpoint hashing. No new synchronous refresh is introduced on Tk.
Targeted checkpoint refresh preserves other locations/kinds; concurrent LoRA
and embedding refreshes cannot overwrite checkpoint updates from stale instances.
Cancelled/failed transactions publish no partial cache. Hashing checks cancellation
per 1 MiB chunk and refuses a file whose fingerprint changes during hashing.
Checkpoint bytes are never written.

Readiness is off Tk, single-flight per panel, with a 20-minute cooperative
deadline including lock wait. Worker progress is throttled. Tk only polls the
mailbox; workers never call widgets or `after`. Selection/resource/mode changes,
explicit cancellation and panel destruction cancel the task. No stale result
may build a plan. Native filesystem reads already in progress complete before
cooperative cancellation; no process is killed to interrupt them.

## Freeze and unchanged execution

Readiness returns one cache-backed CompileEvidence with exact path bindings,
one canonical policy per candidate and the existing cached LoRA evidence context.
Preview freezes path-free checkpoint SHA-256 or exact profile reference in each
arm's `checkpoint_evidence`, with structural contract/architecture and path-free
family-evidence provenance, covered by its arm digest. Old arms without this
additive evidence retain their original semantics.

Run validates frozen identity evidence and arm contracts without reopening the
PromptPack, scanning the registry, rehashing or rerunning adaptation. Source
intent, global prompt ownership, Klein backend/geometry qualification, adaptation
completeness, noncausal ratings and one atomic JobService admission remain as
PR-LEARN-140/141 define. Generic PromptPack compilation and ordinary Controlled
Variable planning do not use this readiness step.

## Token-Efficient Validation Plan

First reproduce cold and wrong-file behavior through actual resource discovery,
AppState, checklist selection and Preview, using tiny temporary safetensors
fixtures and no injected family policies. Cover warm/stale cache, metadata and
metadata-free structural signatures, base/refiner/non-SDXL distinctions,
malformed/truncated headers and payload extents, conflicting metadata,
header-only old-cache enrichment, hidden-name feedback, and no-live-header Run.
Cover
identity failures, worker cancellation, overlapping writers and a cross-process
lock; exercise frozen Run through one actual LearningExecutionController batch
submission to a recording JobService double. Then run affected Learning,
ModelPolicy, prompt adaptation/global/Matrix, Klein, replay and import-safety
regressions. Reuse unchanged evidence; kill ignored-structure, malformed-header
fail-open, refiner-as-base and cache-reload mutations,
restore exact bytes and prove restored source green. Finish scoped Ruff/mypy,
controller ratchet, diff checks and one prescribed isolated PR gate.

No personal checkpoint scan, physical generation, runtime configuration change
or backend request is needed for coding validation. Operator validation should
exercise cold/warm Preview on installed accessible candidates after owner review;
unsupported formats or unrecognizable layouts remain unverified.

Authorized read-only installed checks established Preview for two metadata-free
SDXL base files (`albedobaseXL_v31Large`, `realvisxlV50_v50Bakedvae`) and SDXL plus
exact Klein on Forge at shared 768x1024. Bounded selected header/sidecar checks
took 4.8–6.4 ms for the tested base files. Cold pair Preview took 11.83 s,
including 11.77 s for both 6.94 GB byte identities; warm Preview took 69 ms,
SDXL/Klein 76 ms without further hashing. These are local observations, not
throughput guarantees. Temporary PromptPack/cache/state were used; installed
checkpoint fingerprints and the active application's registry stayed unchanged.
