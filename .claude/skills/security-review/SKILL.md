---
name: security-review
description: Review a StableNew change that affects dependencies, processes, filesystem, network, untrusted inputs, credentials, persistence, CI, or release boundaries.
---
Perform a read-only, diff-focused threat review.

Identify trust boundaries and realistic attacker/untrusted-input capabilities.
Check only applicable classes:

- secrets/credential exposure;
- shell/command injection;
- path traversal and unsafe file mutation;
- untrusted deserialization/workflow execution;
- download integrity/provenance;
- network endpoint trust;
- process ownership/adoption/termination;
- database migration/data loss;
- privilege/permission changes;
- dependency/bootstrap supply-chain risk;
- CI/release secret scope and artifact integrity;
- fail-open governance for experimental backends.

For each finding provide severity, precondition, affected path/symbol,
evidence, and the minimal required fix. Separate required fixes from
defense-in-depth suggestions.

Do not claim exploitability without a plausible path.
