# Model / usage

Codex Desktop; actual model `gpt-6.1-sol`; High effort; 0 source/review repair passes; research artifacts delivered with PARTIAL assessment coverage.

Measured by `tools/usage_report.py`, exact session `codex:01a1b931-9a47-7ca0-a697-10cb2c738820`, window `2026-11-08T03:26:38.258000+00:00` to `2026-11-08T03:41:14.147307+00:00`.

| Category | Measured tokens |
|---|---:|
| Fresh input | 146,227 |
| Cache read | 4,035,328 |
| Cache write | 0 |
| Output | 32,516 |
| Reasoning, already within output | 4,406 |

34 token events; they are not response counts. No monetary conversion. One session, no delegated work. The start is host session metadata, which predates the manual timestamp and repository discovery. This measurement includes recorded preflight/discovery in that session. Live logging and final response/closeout after the window are excluded; this is a measured through-window total, not a claim that unlogged closeout tokens are zero.

Initial-context planning assumptions: 3,000,000 cache-read and 40,000 output tokens. Current ratios: 1.35x cache-read and 0.81x output. Neither crosses the 3x / one-third calibration trigger. Fresh-input/cache-write were not estimated, so no ratio is invented. The estimate was established after initial context, not falsely reconstructed as a pre-discovery prediction.

Validation incidents: one test-directory setup error and one Tk/Windows exception attempt, followed by a successful explicitly non-GUI validation set. No production repair was attempted.
