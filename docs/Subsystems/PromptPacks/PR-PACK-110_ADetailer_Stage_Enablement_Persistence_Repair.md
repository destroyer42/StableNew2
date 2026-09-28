# PR-PACK-110 — ADetailer Stage-Enablement Persistence Repair

Status: implemented for the confirmed canonical PromptPack case; the
four-file real-data reconciliation originally scoped by this package's owner
prompt was **not performed** because the census evidence contradicted the
prompt's premise about those files' identity (see "Discrepancy found" below).

## Census evidence and root cause

`WP-PACK-AUDIT-100` recorded ten `saved_setting_stage_contradiction` findings
(two per source, five sources) showing `pipeline.adetailer_enabled=true`
persisted alongside `adetailer.enabled=false`. `ConfigManager._merge_config_with_defaults()`
deep-merges an incoming config over defaults with no step reconciling the
three ADetailer enablement representations
(`pipeline.adetailer_enabled`, `adetailer.enabled`,
`adetailer.adetailer_enabled`) with each other, so overriding only one of
them can silently leave the others stale. `save_preset()` persists that
merged/default-filled result, and `save_pack_config()` persists the supplied
`preset_data` directly with no equivalent step at all.

Runtime stage admission was already tolerant of this: `src/pipeline/stage_sequencer.py`
computes `ad_enabled = pipeline_flags.get("adetailer_enabled", False) or
_extract_enabled(config, "adetailer", False)` — an OR, so a stale
`adetailer.enabled=false` never disabled a pack StableNew already treated as
enabled. The defect was persistence-metadata inconsistency, not a stage
behavior bug.

## Persistence authority and synchronization invariant

`pipeline.adetailer_enabled` is the canonical persisted stage-membership
value when explicitly present (matching the existing runtime OR-based
admission above). `adetailer.enabled` and `adetailer.adetailer_enabled` are
compatibility mirrors that must agree with it on persistence.

New `synchronize_adetailer_enablement()` in `src/utils/config.py`:

- precedence when more than one representation is explicitly present:
  `pipeline.adetailer_enabled`, then `adetailer.enabled`, then the legacy
  `adetailer.adetailer_enabled`;
- when none of the three is explicitly present, invents no enablement
  intent;
- once a canonical value is determined, persists that same boolean into all
  three locations;
- returns a new dict; never mutates the caller's `config` object (or its
  nested `pipeline`/`adetailer` sections) in place, since callers may reuse
  what they passed in.

No other stage (img2img, upscale, animatediff, video_workflow) is
synchronized by this helper, and stage sequencer/executor OR-based admission
semantics are unchanged.

## Persistence paths covered

- `ConfigManager._merge_config_with_defaults()` — called after the existing
  `_ensure_refiner_hires_fields()` step, so `save_preset()` and
  `load_pack_config()` both get the invariant for free without a second call.
- `ConfigManager.save_pack_config()` — calls the narrow helper directly on
  the supplied `config` before it becomes `preset_data`, deliberately without
  running the full defaults merge, so no unrelated default field is injected
  into a PromptPack's `preset_data`.
- `get_pack_config()` (raw reader) is unchanged: it continues to expose
  whatever is actually persisted, including historical inconsistency, for
  evidence/audit purposes.

## Discrepancy found — four of the five named sources are not PromptPacks

The owner prompt asserted all five affected stems
(`SDXL_epic_structures_Fantasy`, `Juggernaut_MedievalHeroes_RandomizerAligned_v1b`,
`Photoreal_Character_Juggernaut_SDXL`, `Testing`, `default`) were canonical
per-user PromptPack files "not repository standalone preset files with
coincidentally similar names." Re-checking the actual `source_type` field
recorded by the merged `WP-PACK-AUDIT-100` report shows this premise is
correct for only one of the five:

| Stem | Recorded `source_type` | Actual file |
|---|---|---|
| `SDXL_epic_structures_Fantasy` | `promptpack` | `C:\Users\rob\AppData\Local\StableNew\PromptPacks\SDXL_epic_structures_Fantasy.json` |
| `Juggernaut_MedievalHeroes_RandomizerAligned_v1b` | `standalone_preset` | `C:\Users\rob\projects\StableNew\presets\Juggernaut_MedievalHeroes_RandomizerAligned_v1b.json` |
| `Photoreal_Character_Juggernaut_SDXL` | `standalone_preset` | `C:\Users\rob\projects\StableNew\presets\Photoreal_Character_Juggernaut_SDXL.json` |
| `Testing` | `standalone_preset` | `C:\Users\rob\projects\StableNew\presets\Testing.json` |
| `default` | `standalone_preset` | `C:\Users\rob\projects\StableNew\presets\default.json` |

The other four stems do not exist at all under the canonical PromptPack
directory; they are standalone recipe files in the repository's active
`presets/` directory, which this package's own explicit constraint says not
to modify "unless new evidence separately proves one is part of this exact
five-pack census set" using the file identity the prompt described (a
canonical PromptPack). That proof is unavailable — the census evidence
directly contradicts the premise for four of the five. This matches the
package's own hard-stop condition ("the five real PromptPacks are not the
exact files/source identities described by the census").

Given this, only `SDXL_epic_structures_Fantasy` — the one source
unambiguously matching every stated criterion (canonical PromptPack
directory, valid PromptPack structure, and the exact demonstrated
contradiction) — was backed up and reconciled. The four `presets/*.json`
files were left untouched pending a separate owner decision on whether
standalone-preset reconciliation is authorized as its own follow-on package.

## Backup and reconciliation (one file)

Backup: `C:\Users\rob\AppData\Local\StableNew\Backups\PR-PACK-110\run_20260928_113841\`
(byte-exact copy plus a local manifest with filename, original SHA-256,
original byte size, and backup path; not committed to Git).

Pre-repair evidence for `SDXL_epic_structures_Fantasy.json`
(SHA-256 `835a7b3d...7b73e3`):

```text
pipeline.adetailer_enabled = true
adetailer.enabled           = false
adetailer.adetailer_enabled = true
```

Reconciliation used `synchronize_adetailer_enablement()` against the raw
`preset_data`, with a semantic-diff guard comparing the full proposed
document against the original before writing. The only path that actually
changed was `preset_data.adetailer.enabled: false -> true`
(`adetailer.adetailer_enabled` was already `true`, and `pipeline.adetailer_enabled`
was already `true`, so neither needed to change). The write used atomic
temp-file-then-`os.replace` semantics; after writing, the file was reloaded
through `load_prompt_pack_document()` to prove it is still a valid
PromptPack document, and all three ADetailer values were confirmed equal
(`true`/`true`/`true`). New SHA-256: `637803b7...6dfe268`.

A full fingerprint of all 39 PromptPack files and all 18 examined standalone
presets (plus `.default_preset`) — 59 files total — was captured before and
after this write: exactly one file's fingerprint changed
(`SDXL_epic_structures_Fantasy.json`); all 58 others were confirmed
byte-identical.

## Before/after census verification

Rerunning the unmodified `tools/promptpack_quality_census.py` against the
same canonical sources with an audit-owned cache:

- `saved_setting_stage_contradiction`: 10 -> 8 (exactly the two findings for
  `SDXL_epic_structures_Fantasy` removed by identity comparison; zero new
  findings; every other finding for every other source unchanged)
- total findings: 1,020 -> 1,018

## Tests

New/strengthened coverage in `tests/unit/test_config_presets_v2.py` and
`tests/utils/test_pack_config_flags.py`: defaults-merge synchronization,
explicit-disabled-pipeline-wins precedence, section-flag fallback, legacy-flag
fallback, no-invented-intent-when-nothing-explicit, non-mutation of the
caller's config object, other stages left untouched, a `save_preset()` raw-JSON
round trip, a `save_pack_config()` round trip proving unrelated `pack_data`
(slots/matrix/name/unknown extension fields) is byte-semantically preserved,
and a `build_stage_execution_plan()` proof that ADetailer remains enabled
after the persistence/load round trip.

Review caught one real regression before merge: the synchronizer was
originally wired in *after* `_merge_config_with_defaults()`'s deep merge, so
a config that explicitly set only `adetailer.enabled=true` (no `pipeline`
key at all) would see the default-filled `pipeline.adetailer_enabled=false`
and mistake it for an explicit higher-precedence value, silently disabling
what the caller had just turned on. Fixed by synchronizing the caller's raw
input before it is merged with defaults, so the precedence decision only
ever sees what was actually, explicitly supplied. A regression test
(`test_section_only_config_is_not_downgraded_by_the_defaults_merge`) proves
this exact case now stays enabled; the one real-file reconciliation in this
package was unaffected, since it called the synchronizer directly on raw
`preset_data`, never through the defaults merge.

## Explicit non-scope

No change to `PipelineRunner`, executor, `JobService`, queue/repository, NJR,
compiler, stage ordering, A1111 process ownership, `build_stage_execution_plan()`
OR semantics, PromptPack job-builder stage-selection semantics, GUI
controllers, or the Asset Registry. No other stage's enablement
representations were synchronized. No prompt, slot, matrix, or
asset-reference data changed in the one reconciled file. The 24
missing-asset findings, the naming-hygiene debt, the literal `"None"`
refiner placeholder, and every other census finding class remain untouched
observational debt. The four `presets/*.json` standalone-preset
contradictions remain open, unaddressed findings pending a separate owner
decision.
