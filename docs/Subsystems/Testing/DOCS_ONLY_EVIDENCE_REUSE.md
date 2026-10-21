# Documentation-only CI and evidence reuse

Standard CI policy repair requested by the owner. Model recommendation: Claude
Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh. Expected usage: about 6M cache-read
and 20k output tokens. Trust and integration boundaries warrant careful reasoning.
Controller Surface Assessment: none; no application or runtime ownership changes.

## Contract

Documentation-only PRs and pushes to main run cheap repository/documentation
checks. They do not install the application environment, collect tests, or run
the census/Windows lanes. Schedule and manual dispatch remain full validation.

A documentation-only follow-up on an executable PR may reuse its previous
successful required, full-suite and Windows evidence. Reuse requires the current
base to be contained in the validated head or to differ from its common ancestor
only in documentation. A source, configuration, test or workflow change in either
the follow-up or the base advance refuses reuse. Missing/failed/in-flight evidence,
unknown Git refs and API errors fail closed. Branch-protection check names remain.

The cheap path verifies the actual before-to-head delta, including deletions.
No blanket path filter removes required check runs. No permission increase,
write token, workflow trigger that runs fork code with secrets, or local runtime
operation is introduced.

## Token-Efficient Validation Plan

Focused pure-policy and real temporary-Git tests cover docs-only push, initial
push/missing history, scheduled/manual census, repeated docs follow-ups, docs-only
merge conflict resolution, code/config changes, failed/missing Windows evidence,
and untrusted/older check runs. Inspect YAML conditions and run CI truth checks.
Run the canonical gate once for this executable CI change, then one security
review and hosted CI. Reuse exact accepted application evidence; do not run the
whole suite for a documentation-only follow-up.
