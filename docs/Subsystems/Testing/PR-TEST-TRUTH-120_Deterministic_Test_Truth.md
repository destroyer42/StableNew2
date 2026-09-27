# PR-TEST-TRUTH-120: Deterministic Test Truth

Status: PR-ready evidence record
Updated: 2026-09-27

## Scope and result

This package removes two duplicate, unreferenced manual timing probes that
defaulted to `http://127.0.0.1:7860`. Their requests were confined to their
`main()` functions, so they were not the pytest execution leak.

The actual implicated path was the NJR diagnostics test: its default image
backend selected A1111, whose runtime-transition preparation observes
configured A1111/Comfy endpoints before stage dispatch. The test now uses the
existing typed image-backend registry injection seam with a test-local fake
backend, and patches the concrete configured-endpoint probes to record calls.
Its durable assertion requires that fake diagnostic execution make no such
probe. Production runtime-transition behavior is unchanged.

The Windows batch-launch unit test now replaces the process-manager module's
`os` dependency with a test-local stub. The stub exposes `name="nt"` and the
real environment mapping, exercising the Windows command construction without
mutating the shared process-wide `os.name` object. Production code and runtime
ownership boundaries are unchanged.

## Validation evidence

The package requires focused process-manager and diagnostics tests, including
the fake-backend no-probe assertion, then a direct execution census. The full
local PR gate is run once when its pinned tooling is available; a missing
prescribed tool is reported as a tooling blocker and is not installed by this
package.

## Execution profile

- Model/reasoning recommendation: Terra / Medium for bounded implementation.
- Controller Surface Assessment: N/A; no controller or coordinator code changes.
- Token-Efficient Validation Plan: run the focused unit test first, then
  collection and endpoint/discovery checks, followed by one full local PR gate
  attempt; reuse unchanged-source evidence rather than rerunning broad checks.
