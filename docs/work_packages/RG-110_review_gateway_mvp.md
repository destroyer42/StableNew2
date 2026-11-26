# RG-110 — Review gateway MVP

Status: implemented and tested hermetically; not deployed, not qualified.

Contract: [RG-100](RG-100_phone_review_gateway.md) (decisions D1–D9, invariants, controls S1–S11, RG-110 slice) and
[`stablenew.review-gateway-sync.v1`](../schemas/stablenew.review-gateway-sync.v1.json). **No schema change.**

## Start state

- Task start: 2026-11-25T21:19:13-05:00. Session `claude:d17841ef-48e7-487d-bf6f-4c302f02d025`.
- Branch `claude/rg-110-review-gateway-91957a`, stacked on `docs/rg-100-phone-review-gateway` at `8bfbc7ea`.
- Parallel: RG-120 (PC sync worker) against the same schema.

## Execution class and models

- Execution class: Standard within a known design (new deployable and network boundary already approved in RG-100).
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.
- Controller surface: none. No file under `src/` changes.

## Scope

In: `services/review_gateway/`, `tests/review_gateway_service/`, four test pins in `requirements-dev.txt`, documentation.
Out: Immich (RG-130), action requests (D6, RG-140), PC sync worker and desktop pairing (RG-120), deployment.

## Departures from, and additions to, the contract

RG-120 must match items 1–3 (full rules: [living document](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md) section 2).

1. The HTTP routes, manifest-before-media order and pairing-code hashing, which the schema leaves open.
2. `item.sha256` must equal `media.original.sha256`.
3. `enrolled_devices` lists all active devices, not only those new since the last acknowledgement.
4. `install.sh` and a systemd unit replace the RG-100 table's "container build (pinned)": the target is a Debian LXC.
5. Beyond S2, the service refuses to bind the sync API to every interface or to a tailnet address, and the phone app to
   anything but loopback.
6. The sync port uses TLS with an install-time certificate the PC pins (asked for by RG-120, accepted here). RG-100 names
   only the sync secret; without TLS the secret and media would cross the LAN readable. The owner may reverse this.

## Open for the owner

- **TLS on the sync port** (item 6): confirm, since it adds a fingerprint to the desktop pairing step.
- **Cache growth:** undecided items are never purged.
- **Refused items** show as "to review" yet are purged 14 days after the refusal and cannot be re-published.

## Validation plan

Focused gateway tests; the gateway tests again under Python 3.11 and 3.13; `ruff check`; `python tools/ci/run_pr_gate.py`;
the `tests/tools` suites that guard baselines and the code map; hosted CI as the integration verdict.

## Review

One independent read-only security review (fresh subagent). No authentication bypass, traversal, injection or XSS path
found. Its required findings were fixed: unsent decisions lost between tabs, rejected decisions dropped quietly, the
pairing form rebuilt while typing, the root installer following service-replaceable links, and an upgrade that removed
the running version before building the new one. Also fixed: deciding before an item loaded, a revocation racing an
in-flight decision, an item left hidden after an interrupted upload, a withdrawn record reported as applied, and no free
space reserve. The front-end fixes are checked in a browser, not by repository tests (there is no JavaScript runner).

## Acceptance and evidence

Evidence mode: deterministic tests plus a local run. No qualification claim.

- Demonstrated: hermetic tests for enrollment and scopes, refusal of sync routes on the phone app, outbox durability and
  idempotence, digest verification, retention, CSP, and schema validation of every payload kind; a mutation check that
  breaking each main safety control fails a test; a local two-listener run with a synthetic PC and the built-in browser
  at phone size (pairing, inbox, swipe and button decisions, video playback, receipts, resend after a stopped server).
- Unverified: `install.sh` and the systemd unit on Debian; a real phone over Tailscale; the RG-100 timing targets (first
  thumbnails under 1.5 s, image under 1 s) with real batch sizes; interworking with RG-120.
