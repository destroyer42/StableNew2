# Qualification and acceptance harnesses

Offline-by-default, operator-only tooling that produced the qualification verdicts recorded under `docs/Subsystems/`.
It is never part of the production path and never runs in CI against a GPU, Forge, Comfy or SVD. Physical runs are
on HOLD (`STATUS.md` Holds). This file covers `tools/qualification/` and `tools/acceptance/`.

## Retention rule

A harness stays only while it has a named reason. Valid reasons: (1) retained code or a supported test imports it,
(2) it serves a named unresolved qualification, (3) it is the documented offline check for a supported feature,
(4) the owner has decided to keep it. When the reason ends the harness is removed in a PR that keeps the verdict record
under `docs/Subsystems/`, deletes the harness-specific tests, and lowers the ruff ratchet baseline with
`python tools/ci/run_ruff_ratchets.py --update`. Git history preserves the source; no tags. Extract a shared primitive
only when doing so lets an origin harness be deleted.

Before deleting, find importers of every form, not only `from tools.qualification.X import`: also
`from tools.qualification import X`, `from tools.acceptance import X`, `python -m` invocations and string paths.

## Retained inventory (reason -> retirement condition)

| Harness | Reason retained | Retire when |
|---|---|---|
| `qualification/wan321f` | Offline A14B feasibility proposal and deterministic safety/evidence controls; no physical CLI | WAN-321F is accepted or rejected and no test or follow-up qualification needs these controls; preserve its verdict note |
| `qualification/vid110` | Shared monitor, Comfy client and metrics for the video and acceptance harnesses; `build_lane_a` parity test in `tests/video/test_wan22_experimental_workflow.py` | Its dependents retire; then move the parity graph into a test fixture |
| `qualification/vid150`, `acceptance/vid130_wan_acceptance` | Wan2.2 TI2V-5B is experimental; promotion (roadmap P5-7) re-runs this acceptance; `vid150` imports `vid130` | Wan2.2 is promoted or rejected |
| `acceptance/vid190_queue_recycling_acceptance` | Comfy runtime recycling acceptance, to re-run after P3-3/P3-4 change the managed Comfy process | P3-3 and P3-4 are accepted |
| `qualification/vid160b`, `vid160c` | `win_memory` and telemetry imported by `img154`, `img154b`, `vid170`, `vid181`, `vid184r` | Those retire |
| `qualification/vid170`, `vid181`, `vid184`, `vid184r`, `vid184s`, `vid192` | Wan-Animate-2 is experimental and not promotion-ready (PR-VID-185); `vid184s` imports `vid184` and `vid184r`; `vid181` and its tests are live (its frozen 480x832 envelope is asserted as a literal) | Wan-Animate-2 is promoted or rejected |
| `qualification/img110r` | Imported by `img115` and `acceptance/img_116_klein_acceptance` | Those stop importing it, or the Diffusers slice (PR-IMG-120) is decided |
| `qualification/img115` | Frozen Klein spec and owned-Forge driver imported by `img154b`, `img_backend_qual_100`, `img_116` | Z-Image and Comfy still-image qualification close |
| `qualification/img151`, `img153` | Feasibility gates (`img153` and `img154` import `img151`); Z-Image physical qualification is inconclusive | Z-Image qualification closes |
| `qualification/img154`, `img154b`, `acceptance/img_156_zimage_acceptance`, `acceptance/img_116_klein_acceptance` | Z-Image safety, fence and acceptance; `img_156` imports `img_116` | Z-Image qualification closes |
| `qualification/img_backend_qual_100` | Forge-vs-Comfy still-image qualification is CONDITIONAL / INCONCLUSIVE | A Comfy image slice is decided |
| `qualification/img_forge_100`, `acceptance/img_forge_100_acceptance` | `tests/integration/test_pr_img_155_*` and `_159_*` import `build_stack` / `_await_terminal` | Those tests get their own helper |
| `acceptance/img_forge_120_default_acceptance` | Owner decision to keep (wave 1 exclusion); `tests/tools/test_img_forge_100_acceptance_driver.py` imports it | Owner decides, then retire it with that test |
| `qualification/refine150` | Documented offline YuNet check (`docs/StableNew_Coding_and_Testing_v2.6.md`) | The testing guide stops naming it |

## Retired (audit P2-6, wave 1)

Source remains in Git at commit `bfdeb493` (last commit containing it): `qualification/gui110`, `img110`, `vid175`,
`vid180`, `vid183`, `acceptance/img_117_klein_lora_acceptance.py` and `tools/archive_reference`. Verdicts are in the
matching `PR-*` records under `docs/Subsystems/`, each of which carries a retirement note.
