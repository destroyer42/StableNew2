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
4. Stop the relay in the PC browser or close the StableNew pairing window when finished. A pairing lasts up to 15
   minutes. A host without a heartbeat for 80 seconds stops accepting new remote requests.

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
