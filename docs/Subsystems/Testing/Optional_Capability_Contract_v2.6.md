# CI optional-capability contract

Execution Profile + Model/Reasoning Recommendation: Narrow test isolation and
documentation; Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High. Local/Desktop
retains the shell reproduction. Controller Surface Assessment: none; production,
installer and runtime pins are unchanged. Token-Efficient Validation Plan:
focused reproductions, contaminated-shell and temporary-video tests, surrounding
and CI truth tests, scoped static checks, then the required gate and aggregate
CI-change census. Reuse accepted source evidence; no environment provisioning.

## Profiles and obligations

Base Linux CI is not optional video or Windows integration qualification. A full
census selects every active test; capability omissions remain visible in pytest
skip reasons and JUnit. Migration may not remove a capability to conceal failure.

| Profile | Declaration / preparation | Required evidence | Unsupported state |
|---|---|---|---|
| Base Linux | Standard-GIL Python 3.14, `requirements.txt`, workflow test/lint tools, Tk/Xvfb | Required gate, affected selection when routed, complete three-shard census when routed; versions and skips | Missing required tooling blocks runner qualification. Base does not imply optional profiles passed. |
| OpenCV / NumPy / video I/O | `svd` extra or `requirements-svd.txt` declares OpenCV; NumPy is transitive and explicitly pinned in Windows ML constraints | Both versions; Haar cascade API/data; temporary mp4v source/output encoding and decoding; detector and video-tool tests | Absence is legitimate only for a declared base-only run. Importable but missing API/codec: optional qualification FAIL, not a new skip. |
| PowerShell on Linux | Separately provisioned `pwsh`; no Python requirement or current ordinary-workflow installation | Executable/version, bundled modules, `Get-FileHash`; installer success, exact-hash and conflict refusals, idempotence, atomic staging, check-only and contaminated-path tests | No shell: existing availability skips mean NOT QUALIFIED. Installed but failing required cmdlets/tests blocks this profile. Linux execution must be verified there. |
| Windows integration | Separate Windows host, supported Python and qualified PowerShell; explicit Windows predicates and ownership fixtures | Report Windows-only omissions on Linux; execute separately on Windows; preserve Windows shutdown-leak runner routing | Linux cannot establish Windows PASS. Neither runner labels nor missing capabilities replace that evidence. |

Every qualification report states exact SHA/platform, requested profiles,
executable/package versions, skip counts/reasons, and PASS / FAIL / NOT QUALIFIED
for every profile. Provisioning is separately authorized infrastructure work.
Tests must not install packages, silently change pins, or select fallback runners.

Existing absence predicates remain: `tests/helpers/optional_deps.py`, detector
`importorskip`, and installer shell availability. An optional-enabled qualification
must verify relevant tests actually executed, rather than treating skips as PASS.

## Hermetic inputs

VID-175 tests supply a temporary 49-frame, 480x832 source to the actual
decoder/adapter/encoder. Missing or unrelated personal pose files cannot affect
the result. Tests retain native geometry and temporal-index assertions, decode
13 output frames, compare image content and verify unchanged source bytes.
Real qualification clips remain operator assets, outside CI fixtures.

Installer tests use the unchanged script with tiny temporary assets/manifests.
Child processes receive only the selected shell's bundled module path; parent
environment is untouched. Linux pwsh symlinks are resolved before finding modules.
Missing bundled modules fail explicitly. Hash/refusal behavior is not mocked.

## Separate OpenCV qualification blocker

The existing Windows ML constraint pins `opencv-python==5.0.0.93`. The observed
installation imports but lacks `cv2.CascadeClassifier`, preventing the unchanged
detector from constructing. Two tests fail before behavior assertions. This
predates PR #72 and is not fixed by these fixtures or Linux migration. Keep pins
unchanged; separately qualify a compatible dependency build before claiming the
optional detector profile supported. Base Linux qualification cannot erase this
Windows blocker.
