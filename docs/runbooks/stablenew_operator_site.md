# StableNew Operator Site

The private [Operator Site](https://stablenew-b11960-review.stillbeacon3.chatgpt.site/#connect) uses your
Windows StableNew installation for preview, queue admission, and local output. On the updated Windows build, **Operator
Site** is in the top toolbar beside **Readiness**.

## Pair on the StableNew PC

1. Click **Operator Site** and keep the pairing window open. On the same PC, open **Connect StableNew**, paste
   the Windows pairing code and allow browser access to the local listener if prompted.
2. Pairing grants the Site access to visible PromptPacks and allows it to prepare and submit its own reviewed
   Previews until the session closes. For eval or result media, select **Share eval output…** and choose a folder.
3. To work from another device, click **Start remote session** in the paired PC browser. Keep that tab, the StableNew
   window and the PC online. Sign in to the same private Site on the other device and enter the separate remote code.
   Hosted requests are handled by the paired browser on the PC. The local StableNew pairing code stays on the PC.
4. Active use in the Windows Site tab renews its desktop pairing. An idle desktop pairing expires about 15 minutes
   after its final renewal. Brief loopback interruptions can recover while that pairing is still valid. Choose
   **Reconnect StableNew** after the grant expires, StableNew restarts, or you disconnect from the desktop app.
   A hosted remote session lasts up to 15 minutes. Stop it from its Windows browser tab. A host without a heartbeat
   for 80 seconds stops accepting new remote requests.

## Pair a phone for browserless review

The private Site must have the guarded connector Worker deployed and the
browserless hosted canary accepted before you install a Site service credential.
On the paired PC, StableNew needs to be running. The phone can connect over
Wi-Fi or cellular while the PC's browser is closed.

1. Sign in to the private Site on the phone. In **Connect StableNew**, enter a
   name under **Phone review** and request a pairing code. The code expires
   after five minutes.
2. On Windows, open **Operator Site → Phone review**. Enter the Site service
   credential and the phone code. Check the displayed phone name, choose the
   exact Output folder, and approve browse access. Choose **Also allow saving
   ratings** to grant writes to the native video ratings CSV and gallery
   rating records. Create, queue submission and album edits use the existing
   browser workflow.
3. Use **Output Library** or **Video Review** on the phone. After a lock or
   network switch, the Site resumes the paired browser. A 15-minute browser
   lease renews while the same pairing and Sites sign-in are valid. Pair
   again after 30 days. Restarting StableNew allocates a new presence lease
   under the same grant. Reopen a result or clip whose old link expired.
4. Choose **Revoke phone** in StableNew to stop new native work for this device
   immediately. StableNew saves the revocation locally and confirms it with
   the Site when reachable. On a disconnect, the hosted presence and result
   access expire within 30 seconds. Pending phone ratings can check their
   native receipt when an authorized pairing is available again. A browser that lost its
   device cookie or a replacement PC must pair again after revoking the old
   grant on the original phone or PC.

Windows protects the credentials and exact folder identity with current-user
DPAPI under local application data. Use **Update credential** if the owner
replaces the Site service credential. The credential belongs to the whole
Site. Keep it in the Windows control and provision it only after the guarded
Worker is live. During rollout, the separate **Connect via PC browser tab**
flow remains available.

## Save ratings from a phone

With the matching Site and desktop builds, **Save & next** saves a gallery score or video judgment to
phone storage before moving on. An image or verified clip already open can be rated through a connection
loss. Opening another item requires a connection. **Review** shows **Saved on phone**, **Synced**, and
**Needs review**. The Site syncs when the phone reconnects or returns to the foreground. Use **Sync now**
to retry, or **Export unsynced ratings** to save the pending judgments to a JSON file.

StableNew resolves each pending rating under the current grant and checks the original media digest
and, for video, the source digest. If the same field changed on the PC, Review shows both values.
Independent changes can sync together. Gallery ratings belong to Output Library. To compare a
source with its finished Review results, open the source from the phone Library and select
**Find returned results**. Only verified results inside shared Output appear.

## Browse evals and submit PromptPacks

- Under **Evaluate runs**, select **Find shared runs**, choose a report, then browse its clips and source images. Build the eval report in
  StableNew first if the run is missing. The separate **Video review** screen takes local ratings.
- Under **Create**, choose a saved pack and select its slots. Leave fields inherited or override txt2img model, VAE,
  sampler, scheduler, steps, CFG, width, height, seed, sub-seed, strength and batch runs. Batch runs use the existing
  pipeline loop count. Use **Build Preview** to see the effective values and expansion before authorizing the batch.
- After reviewing the frozen jobs, select **Submit to queue** on the Site. Pairing authorizes this action for the Site's
  own PromptPack draft. A Preview prepared separately on the desktop retains native confirmation. The existing dispatch
  policy applies. Use the receipt to refresh job status and load available results from the shared folder.
- Editing a selection or setting requires a fresh Preview. The Site can rebuild the draft it prepared during this
  pairing. A desktop draft or an independently changed draft requires attention on the PC.
- If the Preview changes or an admission cannot be verified, inspect the Windows draft or queue. A timed-out remote
  request is never resubmitted automatically.

## Ownership and access

The native listener binds only IPv4 loopback port 49381 and requires the precise Site origin and an in-memory bearer.
The owner-private hosted relay binds its short-lived remote code to the signed-in owner. It claims each relay request
once and forwards a closed list of operations. Response data passes through private hosted storage and is removed after
retrieval or by cleanup on subsequent relay activity. Responses expire for retrieval after 75 seconds. The relay allows
32 MiB per transferred file. Output folder grants are read-only. Eval media must resolve under the granted folder and
match the saved SHA-256. Job results are limited to jobs recorded in this session and to media in the granted folder.

PromptPack requests resolve an opaque selection, validate typed overrides against the shared catalogs, require the saved
pack digest and bind the selected slots to a native draft revision. Replacement requires the exact Site-owned entries
from the current pairing. Both clients use the same Add to Job, immutable Preview, and normal queue
admission. The paired session stores only preparation and delivery state. The existing queue and repository own execution
and persistence.

## Execution profile and validation

Architectural Windows and hosted Site integration. Claude Code Opus 5.5 High or Codex GPT-6 Astra High. Prefer local
Windows for the host adapter and mock queue, with the current session for Sites publication. Expected usage is about
10M–30M cache-read and 100k output tokens. A single higher-tier session reduces retries across pairing authorization,
model-policy overrides and the asynchronous native draft lifecycle.

Controller Surface Assessment. Reuse the existing Add to Job service and immutable Preview submission seam. The
AppController ceiling is unchanged. The relay has no second compiler, queue, runner or history store.

Token-Efficient Validation Plan. Run the focused startup, bridge, PromptPack draft and queue tests on Python 3.14.
Use synthetic media and an isolated queue. Verify settings in the compiled records, that a stale Preview is refused, and
that pairing removes both desktop prompts for a Site-owned draft. Exercise both browser workspaces and the hosted relay
with an in-memory SQLite database and temporary media storage. Run the local PR gate once near closeout. At authorized publication verify `required`, `full-suite`
and `windows` at the PR head. Live generation is outside deterministic validation.
