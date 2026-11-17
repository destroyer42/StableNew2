# StableNew Operator Site

The private [Operator Site](https://stablenew-b11960-review.stillbeacon3.chatgpt.site/#connect) uses your
Windows StableNew installation for preview, queue admission, and local output. On the updated Windows build, **Operator
Site** is in the top toolbar beside **Readiness**.

## Pair on the StableNew PC

1. Click **Operator Site** and keep the pairing window open. On the same PC, open **Connect StableNew**, paste
   the Windows pairing code and allow browser access to the local listener if prompted.
2. In StableNew, choose **Share eval output…** and select your output folder for read-only eval and result browsing.
   Choose **Share visible PromptPacks** when you want to share pack names and slot prompts for this session.
3. To work from another device, click **Start remote session** in the paired PC browser. Keep that tab, the StableNew
   window and the PC online. Sign in to the same private Site on the other device and enter the separate remote code.
   Hosted requests are handled by the paired browser on the PC. The local StableNew pairing code stays on the PC.
4. Stop the relay in the PC browser or close the StableNew pairing window when finished. A pairing lasts up to 15
   minutes. A host without a heartbeat for 80 seconds stops accepting new remote requests.

## Browse evals and submit PromptPacks

- Select **Find shared runs**, choose a report, then browse its clips and source images. Build the eval report in
  StableNew first if the run is missing. The separate **Video review** screen takes local ratings.
- Select **Find shared PromptPacks**, choose a pack and its slots, and request a Preview. StableNew asks before filling
  an empty desktop draft. The existing draft action applies saved pack settings and the active desktop pipeline
  configuration. The browser shows effective model, seed, dimensions, sampler, steps and stage chain when Preview
  compilation finishes. Desktop settings remain the way to edit those controls in this version.
- Select **Request queue submission** after reviewing the frozen Preview. Confirm in StableNew. Once the normal queue
  records the batch, use its receipt to refresh job status and load available results from the shared folder. A Site
  submission uses the existing queue dispatch policy.
- If the Preview changes or an admission cannot be verified, inspect the Windows draft or queue. A timed-out remote
  request is never resubmitted automatically.

## Ownership and access

The native listener binds only IPv4 loopback port 49381 and requires the precise Site origin and an in-memory bearer.
The owner-private hosted relay binds its short-lived remote code to the signed-in owner. It claims each relay request
once and forwards a closed list of operations. Response data passes through private hosted storage and is removed after
retrieval or by cleanup on subsequent relay activity. Responses expire for retrieval after 75 seconds. The relay allows
32 MiB per transferred file. Output folder grants are read-only. Eval media must resolve under the granted folder and
match the saved SHA-256. Job results are limited to jobs recorded in this session and to media in the granted folder.

PromptPack requests resolve an opaque selection, require the selected pack to retain its saved digest and bind the selected
slots to an empty native draft revision. Both clients use the same Add to Job, immutable Preview, and normal queue
admission. The paired session stores only preparation and delivery state. The existing queue and repository own execution
and persistence.

## Execution profile and validation

Architectural Windows and hosted Site integration. Claude Code Opus 5.5 High or Codex GPT-6 Astra High. Prefer local
Windows for the host adapter and mock queue, with the current session for Sites publication. Expected usage is about
10M–30M cache-read and 100k output tokens. Routing the package through a single higher-tier session reduces retries
across request identity, disk scope, and the asynchronous native draft lifecycle.

Controller Surface Assessment. Move the existing Add to Job implementation into its own service and delegate from
AppController. The controller ceiling decreases. The relay has no second compiler, queue, runner or history store.

Token-Efficient Validation Plan. Run the focused startup, bridge, PromptPack draft and queue tests on Python 3.14.
Use synthetic media and an isolated queue. Exercise the hosted relay with an in-memory SQLite database and temporary
media storage. Run the local PR gate once near closeout. At authorized publication verify `required`, `full-suite`
and `windows` at the PR head. Live generation is outside deterministic validation.
