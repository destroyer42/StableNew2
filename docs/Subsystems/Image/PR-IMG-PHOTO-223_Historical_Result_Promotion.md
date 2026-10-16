# PR-IMG-PHOTO-223 — Historical result selection and working baseline promotion

Execution Profile + Model/Reasoning Recommendation: Standard with bounded persistence/lineage risk.
Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High; Local/Desktop for Windows paths and real Tk
acceptance. High effort fits expected successful-work cost across lineage, legacy evidence, geometry
and GUI worker boundaries. No ownership, queue or migration architecture change is required.

Controller Surface Assessment: completion forwards the already-frozen per-photo geometry policy
to the existing store; bounded output iteration preserves its association semantics. AppController
decreases from 7414 to 7413 physical lines and its ratchet is lowered. No new controller authority.
The photo tab decreases from 1201 to 1114 lines by moving result presentation to a 196-line mixin;
the read-only result projection/validation module is 275 lines. Store sidecars remain authoritative.

Token-Efficient Validation Plan: failing-before store and real Tk regressions, focused existing
photo/controller/reprocess coverage with disposable images, fake JobService and injected faults,
then one final canonical PR gate. Reuse unchanged PHOTO-222 evidence where applicable. Security
Review covers path boundaries, untrusted historical metadata and atomic promotion. Inspect the
aggregate scoped diff and whitespace. No operator data, runtime or physical generation tests.

## Browser and operator choices

Single Photo lists the imported original, current working baseline and every recorded output
individually, including several outputs within one run. Rows retain run identity and output ordinal;
the latest run is labeled without treating its final output as a quality winner. Empty history entries
remain visible with an ineligibility reason. Current working image and selected candidate are labeled
separately. Clicking only previews; active-photo and batch-selection authorities remain unchanged.

Use Selected Result as Working Baseline has two explicit modes: **Image + recorded prompt/settings**
and **Image only + retain current prompt/settings**. A scrollable confirmation includes asset, run,
output/path, checksum, mode, complete before/after baseline and limitations. Cancel writes nothing.
Image-only retains prompts, model/VAE, stages and settings; Auto geometry follows the chosen decoded
image, while Custom dimensions persist. Recorded mode uses the stored effective prompts, model/VAE,
stage list and config. Known historical geometry policy is restored; when it was not recorded, retain
current Auto/Custom policy and current Custom dimensions with an explicit warning.

New imports retain their original baseline and image hash as optional sidecar fields; new history
retains copied-output hashes and frozen geometry policy. These are additions to existing schema1.0
records, not a migration or second store. Older original settings are not invented. Missing required
historical model/VAE/stage/config metadata refuses recorded-settings mode and identifies image-only
retention as the alternative. Empty VAE remains Automatic.

## Validation and persistence

Each candidate freezes asset ID, kind, recorded path, history index, run ID and output index. Recheck
exact membership and refuse duplicate/ambiguous history references. Require an absolute path with no
parent traversal and containment within the selected managed asset; reject links/junctions and invalid,
missing or undecodable images. An external legacy path is eligible only through the existing migration
marker's lexical source-relative identity and matching copied-file hash. Never resolve a changed legacy
link to choose a different copied artifact. Unverified external paths remain ineligible and untouched.

Check available recorded original/output or migration hashes. Without a legacy image hash, report that
readability/current bytes are verified but historical byte identity is unproved. Preparation reads only;
the confirmed plan freezes sidecar and image hashes, and application validates again before writing.
Changes since review refuse promotion. Original, outputs, manifests and historical paths are never
overwritten or moved. Typed history and existing snapshots are retained. The previous baseline snapshot
and replacement baseline enter the existing `save_asset` path together, using one atomic sidecar
replacement; failure before replacement leaves both unchanged. Already-current image/settings cause
no write or duplicate snapshot. Restore Previous Baseline still uses the existing snapshot stack.

The obsolete snapshot-first promotion write is removed. The existing latest-output store convenience
method delegates to the same validated preparation/application path; the GUI always requires explicit
candidate selection. Queue submission continues through prepare_photo_plan, ReprocessJobBuilder,
JobService and the canonical NJR path. Preexisting NJRs and their artifact inputs are not rewritten.

## Preview safety

Decode/hash work and thumbnails run in a bounded read-only GUI worker. Request tokens cancel or
ignore superseded work so an old selection/content mode cannot repaint the current candidate. Hide
previews clears images while keeping metadata and history. Classification includes the persistent
imported filename plus current/original settings and the selected history evidence. Working-image
classification conservatively includes retained history when legacy identities differ. It remains
text classification, not image recognition, and may hide more than the exact selected image.

## Evidence and limits

Base/main: `d025d82a49fdbb2e477a2a4dfcdf1ee7a30921a9`, with PHOTO-222 integrated. Before the
implementation, 12 new store cases and two real Tk cases failed. Security review identified and
reproduced two additional cases: resolving a legacy link could select the wrong copied artifact, and
omitting the imported filename could bypass the prior preview gate. Both regressions now pass and
security re-review is PASS on the final production blobs.

Focused acceptance: **136 passed**. Covers older/multiple outputs, original return, recorded/image-only
choices, explicit/legacy geometry, snapshot/revert, missing/corrupt/tampered images, membership/path
tampering, injected links/junctions, stale reviews/bytes, actual atomic-replace denial, restart, preview
content/visibility, confirmed fake queue submission from the new working image, and unchanged hashes
for historical images/manifests plus serialized preexisting NJRs. Existing latest-promotion fixtures
now supply explicit model/VAE evidence; prior preview tests assert validated image pixels asynchronously.
Logs: `C:/Users/rob/qual/photo223-{before,gui-before,security-before,focused}.log`.
Final canonical PR gate: PASS (repository completeness, lowered controller ratchet, Ruff, ten-file
mypy smoke, 9725-test collection and 386 required smoke/contract tests). Log:
`C:/Users/rob/qual/photo223-pr-gate.log`. Aggregate diff and whitespace checks passed. The final
evidence-only documentation update reuses unchanged source/test results. No remote PR was opened.

Integrity evidence is not authenticated against an actor who can rewrite both images and sidecars.
Workspace ancestors are trusted; fingerprints do not lock concurrent external filesystem writers.
Older missing metadata/hash evidence cannot be reconstructed from names. No physical image quality,
runtime readiness or hosted CI claim follows from these local tests. Empty staging directories left
by canceled queue preparation remain the existing PHOTO-222 output-allocation debt. No further
product decision is required for these bounded eligibility rules. Publication needs owner authorization.
