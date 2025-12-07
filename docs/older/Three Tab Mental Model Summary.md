Prompt tab = text & packs brain

Pipeline tab = “how to run it” brain

Learning tab = “what worked” brain

Let me break it down in terms of what was intended vs what you’re seeing now.

1. Prompt vs Pipeline: original division of labor
Prompt tab (and Advanced Prompt Editor)

Prompt tab was always meant to be the text source of truth:

Prompt packs live here as first-class citizens

Browse packs

Inspect all prompts in a pack

Choose which prompts go in which slots

Do any editing here, not in the pipeline tab

Advanced Prompt Editor is the workbench

Full-text editing

Randomization matrix / template tokens

Category tagging / metadata

LoRA & embedding tokens are inserted here, into the text

e.g. <lora:JuggerFemale_v3:0.8> in the positive prompt

embedding:cinematic_hdr in negative prompt, etc.

“Apply to prompt” semantics

Very literally: “take this pack’s selected prompt (or template) and shove it into the active prompt slot.”

Once applied, the Prompt tab owns that text; Pipeline doesn’t mutate it.

In other words: Prompt tab is “what we’re asking for” + “which packs/templates we’re using.”

Pipeline tab (left column config)

Pipeline tab was meant to own run configuration, not prompt authoring:

One global preset dropdown

A “run preset” that controls:

model / VAE / sampler / scheduler

batch size / batch count

seed mode (fixed, per-image, per-variant)

output dir / filename pattern / format

stage toggles (txt2img, adetailer, upscale)

LoRA strengths, not tokens

This preset is independent of which prompt pack is loaded.

Stage toggles + stage list

Checkboxes map 1:1 to stage cards (middle column) and the preview list.

Turning off “Upscale” hides the upscale card and removes it from the preview summary.

These are runtime graph toggles, not prompt behavior.

Core model config (wired to WebUI resources)

Model / VAE / Sampler / Scheduler dropdowns populated from WebUI API.

Refresh button asks WebUIResourceService to re-sync lists.

This is where we now correctly point DPR-029/028 logic.

Output and seed

Output folder picker (file dialog)

Filename pattern (with a tiny “help” tooltip for tokens)

File format dropdown (png/jpg/webp)

Batch size and seed mode live here.

LoRA & embeddings behavior

Prompt tab decides which LoRAs appear (via tokens).

Pipeline tab exposes sliders / toggles for each detected LoRA token:

e.g. JuggerFemale_v3: 0.8 → slider from 0.0–1.2

That way learning can log: “same prompt, same model, LoRA strength change only.”

Embeddings: same idea – injected via Prompt tab, but strength/toggle can live in Pipeline config if we want them experimentable.

So “division of labor” in one sentence:

**Prompt tab decides what to say and what tools to invoke; Pipeline tab decides how to run it and with what knobs.

2. What’s gone wrong in the current left column

What you’re describing is basically three generations of experiments living on top of each other:

Legacy pack panel bolted into V2

Top pack list with “Load pack / Edit pack” – this is V1 behavior that never got cleanly relocated.

“Edit pack” absolutely belongs in the Prompt tab/advanced editor, not here.

Category-based preset/pack linkage

The middle pack list + category dropdown + second preset dropdown look like an older experiment where:

Presets were “config archetypes” tied to pack categories (e.g., “Character Portrait”, “Landscape”).

Changing the preset would:

Update config knobs and

Filter the pack list by category.

That’s why that list differs from the others.

Third pack list with preview

This one is closest to the intended modern UX:

List of packs

Preview of selected pack’s first prompt

“Apply to prompt” button

But it’s in the wrong tab – it belongs in the Prompt tab, not the Pipeline tab.

On top of that, a lot of the knobs (core config, output, global negative, stages checkbox row) are currently disconnected – they were wired in an older main_window hybrid, then V2 refactor pulled the shell but didn’t complete the controller/state wiring for those widgets.

3. Where prompt packs and presets should live

Given all that, here’s the clean split that matches the original vision and your current needs:

In the Pipeline tab left column

Keep / strengthen:

Run Preset dropdown (single, clear)

Label: “Run preset”

Description (tooltip): “Model, sampler, batch, output & stage configuration.”

Save / overwrite / delete preset actions.

Core Model & Sampling card

Model dropdown (WebUI resource)

VAE dropdown (WebUI resource)

Sampler dropdown (WebUI resource)

Scheduler dropdown (WebUI resource)

Refresh button actually wired (already mostly there now).

Output & Seed card

Output folder with a “Browse…” button.

Filename template and format dropdown.

Batch size and seed mode (Fixed / Per image / Per variant).

Stage & Run Mode card

Run mode (Direct vs Queue)

Randomizer toggle + max variants

Checkboxes for: txt2img, ADetailer, img2img-base (if we keep it as separate), Upscale.

These checkboxes must:

Toggle the stage cards in the middle.

Update the preview panel.

Global negative prompt

“Always append this negative prompt” toggle.

Text box for global negative.

LoRA / embedding controls (numeric)

Detected LoRA tokens in prompt become sliders here.

Optional auto-detection from the active prompt.

Remove / migrate from Pipeline tab:

All “Edit pack” controls.

Any direct prompt text editing.

Extra pack lists that mirror the same data.

The “Apply to prompt” that manipulates text – that belongs on the Prompt tab.

In the Prompt tab

Own all of the following:

Primary Prompt Packs browser:

Single canonical list of packs.

Category filter lives here (if we keep categories).

“Load pack”, “Duplicate pack”, “Open in Advanced Editor.”

Prompt Slots:

E.g. “Hero prompt”, “Supporting character prompt”, “Environment prompt.”

“Apply this pack’s prompt into active slot.”

Advanced Prompt Editor:

Full text editing.

Randomization blocks.

Token highlighting (LoRAs, embeddings).

Pack metadata fields.

This keeps prompt management purely in the Prompt domain, where your brain expects to work with text and examples.

4. ADetailer: separate stage vs img2img add-on

You’re describing exactly what we talked about originally: ADetailer is conceptually its own stage.

It is:

Conditional (only runs if faces/hands found)

Specialized (very different knobs from generic img2img)

A logical step between txt2img and upscale, not a generic effect.

So the intended design is:

Pipeline

Stage sequence: txt2img → adetailer → (optional img2img-base tweaks) → upscale.

ADetailer has its own stage card in the center column with:

Enable toggle.

Detection targets (faces, hands, both).

Confidence threshold.

ADetailer model selection.

When enabled:

For each generated image, run detection; if nothing above threshold, skip; otherwise, run face/hand fix and pass the result forward.

Prompt

Uses the same prompt text as txt2img (or a variant), not a totally separate prompt system.

No special tokens are needed from the user beyond standard prompts – the stage logic handles detection.

This matches your intuition: ADetailer is high leverage and “auto” by nature; you should be able to just toggle “Improve faces/hands” in the pipeline and have it “just work” when applicable.