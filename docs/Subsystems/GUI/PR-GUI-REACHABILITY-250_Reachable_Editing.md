# PR-GUI-REACHABILITY-250 — Reachable editing and artifact previews

## Execution Profile + Model/Reasoning Recommendation

Standard GUI repair within existing presentation and projection ownership.
Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.
Local/Desktop supports real Tk geometry checks. Expected usage: about 5M cache-read
and 20k output tokens. Existing widget, scrolling and artifact contracts keep the
implementation bounded and avoid a new GUI or lifecycle architecture.

## Behavior and boundaries

Prompt text owns the Prompts page. Template, LoRAs, Embeddings and Conditioning
have separate pages in the editor notebook; Matrix remains available. Existing
slot state and callbacks remain shared, so changing pages does not discard values.
Long pages and the right-hand options use the existing ScrollableFrame. Embedding
lists use its shared wheel router instead of replacing the application's global
wheel binding. Positive and negative editing retain useful minimum heights.

Readiness keeps header actions above a scrollable body, including first-run
guidance and GPU recovery controls. Recovery still requires the existing explicit
confirmation, fresh host evidence and controller callback; layout changes neither
release quarantine nor start a runtime.

Optimizer options explain their effects, including logging prompt text and the
currently inactive anchor operation. No optimizer behavior or stored configuration
is changed.

History's Show selected artifact displays the selected row's recorded image or
explicit video thumbnail beside the table. History publication refreshes that row;
matching a pack/model or scanning an output folder never selects an image. Missing
files, directories, videos and manifests are not passed to image decoding. SFW
visibility and the thumbnail checkbox remain enforced. Artifact bytes are not
claimed to have model-resource integrity; historical resource reconstruction is
outside this package. Replay with Changes remains on HOLD.

## Controller Surface Assessment

No controller/coordinator changes. Existing readiness callbacks and immutable job
projections remain authoritative. No queue, schema or runtime ownership change.

## Token-Efficient Validation Plan

Use deterministic Tk tests at compact and normal geometries, with temporary
settings/artifacts and fake readiness snapshots. Verify editable text survives tab
changes, embedding and recovery controls can be reached by scrolling, wheel
bindings survive picker construction/destruction, optimizer copy matches its
implementation, exact-job artifact updates display, and unrelated/missing/video
artifacts do not. Run adjacent prompt, conditioning, Readiness and thumbnail tests,
then the canonical gate once. No GPU generation or live recovery action.
