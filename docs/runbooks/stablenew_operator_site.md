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
4. With matching Site and Windows builds, the desktop authorization expires after eight hours without
   authenticated activity. Active use renews it. Unclaimed pairing codes still expire after about 15 minutes,
   and the one-time connection ticket has its own shorter lifetime. The connection status shows the type and
   expiry. Brief loopback interruptions can recover while the authorization is valid. Choose **Reconnect
   StableNew** after expiry, a StableNew restart, or a disconnect.
5. A hosted remote session has an absolute eight-hour limit. A host without a heartbeat for 80 seconds stops
   accepting new remote requests. The same authorized host can return after a temporary outage. Keep its
   Windows Site tab open because the hosted credentials are held in that tab. The host shows an expiry
   warning and lets you **Reauthorize remote session** on the StableNew PC. Choose **Stop remote session**
   from that tab to revoke it. When a submission response is lost, check the native receipt or queue before
   committing work again. Automatic recovery checks status and receipts without repeating submissions.

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
   exact Output folder, and approve browse access. Choose **Allow ratings and eval report refresh**
   to grant writes to the native video ratings CSV and gallery
   rating records and to let the phone refresh native eval reports in shared Output.
   **Allow writing native Review evidence** is selected for a new enrollment.
   The final Windows confirmation lists each selected permission. Clear the checkbox to grant
   browse access without native Review writes. An existing phone can receive this scope by
   revoking its current grant and approving a new pairing on Windows. **Allow phone Preview and queue submission** is
   a separate, unchecked permission. Select it and confirm the new pairing on Windows to grant it. Album edits use
   the browser workflow.
3. Use **Output Library** or **Video Review** on the phone. After a lock or network switch, the Site can resume
   the same desktop process while the browser lease, device enrollment and Sites sign-in are valid. The browser
   lease expires after eight hours without authorized activity. Passive status checks do not reset the timer.
   Use **Reconnect phone** after expiry or a StableNew restart to authorize a fresh browser lease under the
   same active enrollment and permissions. Pair again when the 30-day enrollment expires. Open a result or clip
   again if its individual media link expired.
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

With the native Review permission, an open image also has a **Native Review** panel. Its rating
and **Retain** action write Review evidence that Learning can use. **Mark for rework** records
the decision for later follow-up. The same phone storage and sync controls cover these judgments.
Use the native Windows Review workspace to archive or restore images.

## Preview and submit from the phone

- Open **Queue** and choose a saved PromptPack and up to 16 slots. **Build PromptPack Preview** compiles the selected
  slots using the saved pack and the native pipeline settings. The phone and Windows desktop drafts can be open at the
  same time.
- To rework an image, sync **Mark for rework** or mark it in Windows Review. Open the exact image from the phone
  Library, choose **Preview marked rework**, and select a stage. StableNew checks the saved decision and the source
  digest before building the Preview and again before admission.
- Review the job count and effective settings, confirm the displayed jobs, then select **Submit reviewed Preview**.
  Source or setting changes require a fresh Preview. The normal queue dispatch policy applies.
- **Queue** shows jobs and receipts for the current phone pairing. A pending receipt survives a browser reopen.
  After a disconnect, refresh Queue or select **Check receipt**. An unconfirmed receipt blocks another phone
  submission. Check the exact receipt and the native queue on Windows. Completed Queue jobs can open results in
  shared Output. To compare a rework result with its source, open the source in Library and choose **Find returned
  results**.

## Browse evals and submit PromptPacks

With matching Site and desktop builds, open a verified Library image or album and choose **Make Video or evaluate**.
Select up to 16 images. **Make Video** uses one compatible image-to-video workflow. **Controlled evaluation** uses
one baseline and up to three candidates on the same images, motion prompt, seed and frame count. Enter a shared
negative prompt if the selected workflows have different defaults. Each experimental arm needs its own opt-in.
Review the exact count, generation dimensions, catalog model files, graph revision, frame count and FPS before
queueing. The phone uses the same queue receipt for these jobs. Prepared sources and run manifests live in shared
Output. Workflow dependencies and runtime readiness are checked through the normal Windows execution path.

Open **Compare evaluation pairs** from Video Review or follow **Review evaluation** from an admitted receipt.
Choose **Refresh report on Windows** to build an unbuilt report or refresh outdated evidence after ratings sync.
Use **Review next incomplete verified pair** to open matching A/B clips with shared playback controls. The
pair view reveals arm identity after both judgments are saved to the phone. Individual clip Review can reopen
a judgment bound to an older artifact. The report's comparisons and readiness follow the ratings revision
used by the Windows builder. Playback uses the recorded clip stream, with the display sized for the screen.

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

## Plan a follow-up from Review

With phone Preview and queue permission, choose **Plan a follow-up** from a synced Native Review image rating,
a verified returned rework comparison, or a matched video evaluation pair with both ratings synced. Image
follow-ups also require Native Review permission. Video follow-ups require ratings permission.

The image template compares two sampling-step counts on the original, verified single-image text-to-image
recipe. A returned rework can motivate that test, while its result remains observational evidence. The video
template compares two legal frame counts on the recorded baseline's approved workflow. When the earlier pair
changed workflow version and generation resolution together, the plan calls out both changes and tests frame
count with a single workflow, graph, and generation size.

Load the plan in **Queue** to see the objective, fixed controls, two-job count, and evidence to collect. Choose a
test value and review the plan before building Preview. Review the exact jobs, then explicitly submit if desired.
StableNew checks the original evidence again before admission. If it changed, return to the current evidence and
load a fresh plan. The templates run on Windows using the native evidence, model policy, and workflow catalog.

## Ownership and access

The native listener binds only IPv4 loopback port 49381 and requires the precise Site origin and an in-memory bearer.
The owner-private hosted relay binds its short-lived remote code to the signed-in owner. It claims each relay request
once and forwards a closed list of operations. Response data passes through private hosted storage and is removed after
retrieval or by cleanup on subsequent relay activity. Responses expire for retrieval after 75 seconds. The relay allows
32 MiB per transferred file. Phone mutations require the approved ratings, native Review, or queue permission.
Eval report refresh uses the ratings permission and can only open files in shared Output. Eval media must resolve under the granted folder and
match the saved SHA-256. Job results are limited to jobs recorded in this session and to media in the granted folder.

PromptPack requests resolve an opaque selection, validate typed overrides against the shared catalogs, require the saved
pack digest and bind the selected slots to a native draft revision. Replacement requires the exact Site-owned entries
from the current pairing. Both clients use the same Add to Job, immutable Preview, and normal queue
admission. The paired session stores only preparation and delivery state. The existing queue and repository own execution
and persistence.

## Connection protocol and release

The Windows phone connector requires protocol 2 with enrollment, presence and browser lease
capabilities. The private Site authenticates its capability probe with the existing service
credential. Windows checks before inspecting or saving a new pairing, when restoring or recovering
presence, and before saving a replacement credential. Each connector operation uses a versioned
route and header. The v25 Worker rejects those routes before handling enrollment or presence, even
if a version switch happens after the probe. Windows retains existing saved grants during an outage
or mismatch. From the Windows Phone review dialog, update the Site and StableNew to matching
versions before retrying. Confirmed expiration or revocation requires pairing again.

Browser status, expiration, pending requests and timers belong to the desktop, hosted viewer or
phone authorization that started them. Switching increments the browser's connection generation.
Phone grant and browser lease changes have their own identity. An uncertain submit keeps its exact
receipt reference. Restore the original authorization or check the native queue if a different
connection is selected. Phone Queue persists its pending receipt by grant and exact ID across page
reload. Recovery only reads the receipt. Native JobService and the repository own admission and the
committed jobs.

| Windows phone connector | Site Worker | Supported behavior |
| --- | --- | --- |
| Existing | v25 | Legacy phone enrollment and presence, with the v25 lease policy. |
| Updated | v25 | Compatibility probe and versioned mutation routes are refused. Existing Windows grants are retained. |
| Existing | v2 | Legacy connector routes are refused before state changes. |
| Updated | v2 | Authenticated enrollment, eight-hour phone inactivity lease, and same-device reconnect with the stored scopes. |

Stage both reviewed versions first. The mixed versions refuse phone operations, so schedule the
cutover while the paired PC and Site workflows are idle. If that would interrupt active use, get an
owner decision on the maintenance window before proceeding. Only after authorization, deploy the
v2 Site with its additive migration, verify the migration and the v2 capability response, and then
start the updated Windows build. A v25 presence can hold the old process slot for up to 30 seconds.
The v2 browser requires v2 presence and an explicit reconnect for a migrated grant. Start a new
desktop pairing or hosted browser session when needed. Live gateway, real-phone recovery and
eight-hour operation require a separate authorized acceptance run.

The migration keeps phone grants, permission flags and existing relay records. Legacy browser
leases start unbound. Sites applies the journal before uploading the Worker. Verify the completed
journal and all three columns before enabling the connector. A missing column blocks the v2
capability response. A partial or uncertain migration requires inspecting the actual schema and
journal before retrying. The raw ALTER statements are one-time steps.

For rollback, stop the v2 connector and drain its presence before returning to both v25 and the
existing Windows build. The v25 Worker can read the additive schema. Keep the added columns, align
the Windows and Site versions, and renew the browser authorization under the restored policy.
Resolve any ambiguous submission through its native receipt or queue. A backup and production
rollback decision are part of the separately authorized rollout.

## Maintained regression coverage

| Protected behavior | Deterministic suites | Browser acceptance |
| --- | --- | --- |
| D1–D2 Protocol and authorization order | Native `test_site_phone_connector.py`; Site `worker/phone-connector.test.mjs` | `worker/phone-queue.browser.mjs` covers version refusal. |
| D3–D4 Connection ownership and async ordering | Site `worker/connection-recovery.test.mjs`, `phone-client.test.mjs`, `desktop-activity.test.mjs`, `autoconnect.test.mjs` and `relay-client.test.mjs` use controlled responses and timers. Worker tests fence requests during revocation. | Phone Queue separates server revocation from browser awareness and checks the in-flight read. |
| D5 Session limits and recovery | Native `test_site_pairing_protocol.py` and `test_site_queue_bridge.py`; Site `connection-recovery.test.mjs`, `phone-connector.test.mjs` and `relay.test.mjs`. | Phone Queue exercises expiry and explicit reconnect. |
| D6 Admission and receipts | Native `test_site_phone_admission.py` and `test_site_queue_bridge.py`; Site `connection-recovery.test.mjs`, `phone-connector.test.mjs` and `relay.test.mjs`. | Phone Queue checks one submission, one canonical job and exact receipt recovery after reload. |
| D7 Browser permissions and workflow continuity | Native `test_site_pairing_protocol.py` checks the precise loopback origin. | Site `offline-albums.browser.mjs`, `phone-queue.browser.mjs` and `phone-video-eval.browser.mjs`; keep Chromium network protections enabled and grant fixture access only to the test origin. |
| D8 Migration and compatibility matrix | Site `phone-connector.test.mjs` uses the actual v25 Worker in Git history and the built v2 Worker with synthetic SQLite. | Covered by the deterministic transition tests before rollout. |

The native test files are in `tests/controller/`. The standard Python 3.14 census includes all four.
The required smoke includes the native HTTP and enrollment sequencing contract checks. Run
`node worker/build.mjs` and `node --test worker/*.test.mjs` from the Site root, then the three
maintained browser scripts for changes to connection, scope, receipts or protocol. The companion's
`worker/CONNECTION_AND_REVIEW.md` describes its local review gate and fixture setup.

SITE-MOTION-500, SITE-STORY-510, SITE-STORY-520, SITE-MEDIA-530 and later Site packages must identify
affected invariants and reference this coverage. Run the affected focused tests during implementation
and the corresponding broader suite when shared connection, authorization, receipt or protocol
code changes. Use the prescribed final gate. Weakening or removing a protected behavior requires
owner-approved equivalent coverage.

## Execution profile and validation

Architectural Windows and hosted Site integration. Use Claude Code Opus 5.5 High or Codex GPT-6 Astra
High on local Windows for access to both worktrees and scoped Chrome loopback. This tier reduces
retries across the asynchronous browser, Worker and native authorization boundaries.

Controller Surface Assessment. The connector and browser apply connection consent and lifecycle
rules through their existing transport boundaries. AppController and JobService stay unchanged.
The native Preview, queue and repository remain authoritative for admissions and receipts.

Token-Efficient Validation Plan. Reproduce connection defects with focused native and Site tests,
using controlled clocks, deferred responses, synthetic grants and isolated storage. Run the Site
build and maintained deterministic and browser suites with Chrome protections enabled. Run the
native PR gate near closeout and review the two aggregate diffs against their exact heads. At
authorized publication verify `required`, `full-suite` and `windows` at the native PR head.
