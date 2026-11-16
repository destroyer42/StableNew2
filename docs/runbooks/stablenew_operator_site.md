# Operator Site image queue connection

Use the private [StableNew Operator Site](https://stablenew-b11960-review.stillbeacon3.chatgpt.site/#connect) from the
same Windows computer as StableNew. The first supported scope is the accepted image Preview in the native app.

1. Open the image draft in StableNew and review its Preview. Use the native Preview for prompts, models, and settings.
2. Select **Operator Site → Connect Operator Site** in StableNew. Keep the pairing window open.
3. In the Site's **Connect StableNew** view, paste the pairing code and connect. A browser that prompts for loopback
   access needs that permission before it can read the Preview.
4. Compare the job list in the Site with the accepted Preview, then select **Request queue submission**.
5. Confirm the request in the StableNew window. The Site shows the receipt with the job IDs after the normal queue
   records the batch. Manage the jobs from the native queue. The existing queue's dispatch policy applies.
6. Close the StableNew pairing window to revoke access. Codes are operation-session credentials and expire after
   15 minutes. Use a new connection if the code expired.

If the Preview changes, the request refuses instead of recompiling. Refresh and review the latest Preview.
If a submission cannot be verified, inspect the native queue before making another request. The Site does not resend a
submission automatically.

## Ownership and scope

The listener opens only from the native menu. It binds IPv4 loopback port 49381, accepts the exact private Site origin,
and uses a short-lived bearer code held in memory. Preview projection contains only job IDs and stage labels. The sole
write request carries an opaque Preview identifier. The browser has no input for prompts, asset paths, raw NJRs,
backend selection, or queue management on this route.

StableNew binds an accepted Preview revision to its exact immutable records, checks again after native confirmation,
and uses the existing Add-to-Queue worker and admission. The bridge tracks only the current command and receipt in
memory. The existing queue and repository own execution, status and persistence.

## Execution profile and validation

Architectural, bounded Windows integration. Claude Code Opus 5.5 High or Codex GPT-6 Astra High for the cross-origin,
UI lifecycle, and exact-Preview review. Either host on Local Windows. Expected implementation and review usage is
about 10M cache-read and 80k output tokens. The security and concurrency boundary makes a single broader review less
costly than repeated lower-effort repair.

Controller Surface Assessment. Extract the existing Add-to-Queue launch coordination into the existing submission
service. The smaller AppController delegates both cases to that service and lowers its recorded ceiling. Neither bridge
module owns a compiler, queue, runner, SQLite write or backend.

Token-Efficient Validation Plan. Run the Site bridge, Add-to-Queue and controller-surface tests on Python 3.14 first.
These use fake work and exercise exact Preview reference, permission failures, repeat requests, stale drafts, receipts
and native admission. Then run the local PR gate once and verify `required`, `full-suite` and `windows` at the published
head when publication is authorized. Use simulated jobs for integration verification. Actual generation requires a
separate owner decision.
