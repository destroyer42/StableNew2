# Comprehensive assessment v0 and independent critique — audit trail

Source baseline: remote main `d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e`, checked October 15 2026 America/New_York. This record preserves the **first pass before methodological correction**; it is not the final ranking.

> Historical audit trail: v1.1 prioritization is superseded by the October 16
> v1.2 adjudication. Its governance claim is further superseded by the dated
> report's [integration correction](COMPREHENSIVE_ASSESSMENT_2026-10-15.md#2026-10-16-integration-verification-and-governance-correction):
> branch metadata confirms protected `main` and `required` for non-admins;
> privileged bypass remains unverified. No ranking here authorizes work.

## Initial pass (v0, broad scan)

Evidence: `AGENTS.md`, `STATUS.md`, `CODEX_MAP.md`, architecture/roadmap/testing, repository tree (2,042 blobs; 598 src, 946 tests, 137 docs), recent PR index and selected subsystem acceptance reports. First-pass prioritization using risk > user value > enablement > effort:

1. GPU loss containment/recovery: October 12 14-job cascade, known residual same-host post-release failure; very high potential loss.
2. Directed person/video motion: accepted control experiments fail to meet locomotion objective, 196 guides source but no quality evidence.
3. Model-family compatibility: cross-workflow failures historically blocked Z-Image and Klein.
4. GUI usability: viewport and reachability, many controls and long forms.
5. Test/CI developer experience: prior Phase B slow test examples; test count and operator journey.
6. Photo Optimize workflow: baseline promotion/legacy migration and repeated edits.
7. Architecture hotspots: large AppController, pipeline Executor and learning controller.
8. Security/asset provenance: untrusted user images, paths, process identity.
9. Model output quality/refinement; 10. observability, 11. performance/resource cost, 12. documentation drift.

This was **not yet a valid final recommendation**: it overweighted historic issue narratives and module sizes and did not distinguish documented risk from demonstrated current failures.

## Independent adversarial critique

| Challenge | Verdict | Evidence | Correction |
|---|---|---|---|
| "Z-Image generic incompatibility is still a top unresolved feature" | **Confirmed flaw** | PRs 158/159/160 merged in main, including global positive parity; residual inline LoRA/physical qualification only | Mark resolved baseline; gate new work on fresh reproductions |
| "GUI-100 cramped viewport is current unresolved" | **Confirmed flaw** | GUI-100 explicitly notes GUI-110 fixed those constraints; both merged | Require post-fix Windows viewport reproduction |
| "Test B1 100-second saving is a new opportunity" | **Confirmed flaw** | B1 report has post-fix measurements; B2A 5,068-test collection and current CI | Rank only current measured slowdown or fragile selection, not old fixes |
| "GPU failure is a software root cause needing recovery refactor" | **Partly confirmed** | GPU-180 merged; source report admits suspected loss and probation gaps, but root device/hardware cause and frequency not proven | Split owner/hardware readiness gate from separate conditional queue policy change |
| "Passing unit tests proves usable motion" | **Confirmed flaw** | VID-196 explicitly has no physical generation; VID-192 one-seed experiment failed locomotion, owner quality ratings outstanding | Product-quality label remains unverified; physical experiment after owner clearance |
| "Largest files are objectively top hotspots" | **Confirmed flaw** | Tree shows very large modules but no comparable history-adjusted churn, complexity or regression rates were measured | Size is a watchlist only, recommend incremental extraction tied to adjacent change |
| "STATUS is truth about PR open state" | **Confirmed flaw** | STATUS still labels VID-196 open/PHOTO-223 local; GitHub confirms PR #104 and #106 merged | Distinguish current source and PR API from stale textual staging fields |
| "Current CI is green" | **Confirmed flaw if asserted** | Last checked main push run in listing predates latest main HEAD; PR logs are head-specific | Require exact-SHA CI before claiming current CI; report unknown |
| "Risk/impact numerical score will settle order" | **Confirmed flaw** | No frequency/denominator of actual failures, GPU capacity, motion usefulness or product-user priority metrics | Use gates and ordinal rankings; show sensitivity and conditional tracks |
| "Security review is unnecessary for a local app" | **Refuted** | GPU qualification notes `shutil.which`/cwd trust, video untrusted FFmpeg, photo path/sidecars | Review relevant attack surfaces proportionately; do not promote low evidence to exploit claim |
| "All 2,042 files were deeply inspected" | **Confirmed flaw if asserted** | Repository tree + sampled source/docs only; no local clone, profiling, or runtime | Report as broad-coverage remote desk assessment with bounded technical dives, not complete audited codebase |

## Framework corrections (v1.0 → v1.1)

1. Introduce evidence classes V/D/H/R/U and explicit staleness checking against live PR merged state and source SHA.
2. Separate safety risk gates from discretionary economic ranking. Hardware fault does not imply code defect.
3. Require recent **underlying code + test** for top decisions where access allows, and state missing source evidence otherwise.
4. Force coverage of 12 categories and product journeys, even when no issue is found; record negative findings as "not established", not "clean".
5. Use product quality/physical and Windows evidence tier; don't call deterministic tests an image/video/GPU acceptance result.
6. Introduce both problem and intervention confidence, falsification tests and no-action alternatives.
7. Prevent double-counted enabling benefits and contingent fixes; compare currently merged features first.
8. Require exact-SHA CI links, scope and limitations; collection count is not elapsed test performance.
9. Introduce explicit adversarial critique and a second rankings pass with changed-vs-unchanged dispositions.
10. Keep docs-only research distinct from repository publication and hardware/runtime authorizations.

The final dated assessment applies **v1.1**, not the initial ranking above.


## 2026-10-16 second independent critique: major blind spots in v1.1

A separate repository audit supplied by the owner traced production wiring, GitHub administration/Actions, Windows job-object ownership, file stores, UI bindings and test economics. A subsequent source check on `d43fdc39` reported significant code/configuration gaps that the initial assessment had not sought: an unprotected-`main` claim (**subsequently refuted by the integration correction above**), masked failing full-suite jobs, privileged untrusted AutoFix workflow, fixed named Windows job object, bypassed startup gate and relaxed NJR strictness, direct Learning JSON writes, undefined state override helper, worker-thread scan completion fallback and limited History/Learning reachability. A safe local two-process reproduction and real-operator incident attributions were **not** produced. The external audit's measured local statistics and proposed 10-week plan were **not** accepted as independently validated.

| Failure in v1.1 method | Why it missed the issue | v1.2 permanent correction |
|---|---|---|
| PR acceptance treated as system proof | did not inspect real `main` construction and disabled defaults | require entrypoint-to-enforcement trace plus negative path |
| CI workflow green treated as suite green | no comparison of per-job failures or effective branch rules | require job conclusions and rulesets/protection, not badge only |
| Security considered mostly source-file content | ignored event-triggered privileged automation and Windows handle identity | explicit trust-boundary/process ownership gate |
| SQLite evaluated but file stores omitted | Learning JSON/UI/LoRA stores outside lifecycle DB | enumerate *every* durable store and partial-write behavior |
| GUI assessed for viewport only | not whether promised features actually had an event binding | existence/reachability/correctness/use/usefulness/sustainability matrix |
| Large code ranked only as debt | didn't look for undefined calls inside swallowed fallbacks | AST/call-path negative probes before broad refactor recommendation |
| Independent critique too similar | challenged own conclusions rather than using new collection methods | independent **method diversity** mandatory for Comprehensive |

**Change in prioritization:** verified shared-state/security/enforcement risks take precedence over GPU-180's documented but not presently reproduced release-probation gap. See the dated Comprehensive report's 2026-10-16 addendum. Critical-control gates remain risk dispositions; they are not a grant of GitHub admin, branch publication, production operation or data mutation authority.
