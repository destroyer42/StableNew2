PR-GUI-V2-PIPELINE-RUNTAB-001A_stage_cards_to_pipeline_center_2025-11-26
1. Title

PR-GUI-V2-PIPELINE-RUNTAB-001A: Move Advanced Stage Cards from Run Tab into Pipeline Center Panel

2. Summary

This PR re-parents the real advanced stage cards (txt2img / img2img / upscale) from the legacy Run tab into the Pipeline tab’s center panel.

The Pipeline tab already owns the three-column execution layout and is the architectural “home” for pipeline behavior.

Today, that center panel is still using scaffold placeholders while the real stage cards live on the Run tab.

After this PR, the Pipeline tab’s center column will host the actual advanced stage cards, and the Run tab’s stage content will be redundant (but not yet removed — that’s PR-001B).

No lifecycle logic or controller behavior changes here — we are only moving widgets and adjusting layout wiring.

3. Problem / Motivation

Two different tabs both look like “pipeline configuration”:

Pipeline tab: correct overall layout, but center cards are dummy scaffolds.

Run tab: real stage cards, but visually disconnected from the rest of the V2 design.

This split violates the intent of the V2 GUI architecture (single Pipeline workspace that owns stage configuration and execution†).

We need the Pipeline tab to be the single, authoritative location for configuring txt2img/img2img/upscale stages.

4. Goals / Non-Goals

Goals

Instantiate and layout the AdvancedTxt2Img / AdvancedImg2Img / AdvancedUpscale stage cards inside the Pipeline tab center panel.

Replace the existing “Stage Content (Scaffold)” frames with those real cards.

Preserve all existing controller wiring and behavior (validation, config round-trip, etc.).

Keep Run tab code compiling and functional for now; removal happens in PR-001B.

Non-Goals

Removing the Run tab or its buttons (handled in PR-001B).

Changing controller / pipeline behavior.

Changing randomizer, LoRA runtime controls, or Learning integrations.

5. Allowed / Forbidden Files

Allowed (examples — adjust to real paths if they differ)

src/gui/main_window_v2.py (only where it wires Pipeline tab children, not tab list yet)

src/gui/pipeline_panel_v2.py (or equivalent Pipeline tab frame)

src/gui/pipeline_stage_cards_panel_v2.py (if present)

src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py

GUI layout tests under tests/gui_v2/ that assert Pipeline layout or stage presence

Forbidden

Any src/pipeline/* or src/controller/* modules.

Randomizer core (src/utils/randomizer*.py).

API client (src/api/*).

Learning core (src/learning/*).

6. Implementation Steps

Locate scaffold frames in Pipeline center panel

In pipeline_panel_v2.py (or equivalent), find the three “txt2img / img2img / Upscale Stage (Scaffold)” frames.

Wrap those in a StageCardsPanel or similar container if not already present.

Instantiate advanced stage cards in Pipeline

Import the three advanced card classes:

AdvancedTxt2ImgStageCardV2

AdvancedImg2ImgStageCardV2

AdvancedUpscaleStageCardV2

Create one instance of each in the Pipeline center panel, using the same controller/state objects that the Run tab uses today (copy wiring, don’t invent new controller logic).

Layout and expand/collapse

Place each card in its own row in the center column (e.g., row=0/1/2).

Hook their show/hide buttons into the existing expand/collapse logic used by the scaffolds:

When a card is hidden, row height collapses.

When shown, the card expands to fill available width.

Wire stage enable toggles

Ensure the Pipeline tab’s stage enable checkboxes / buttons (usually near the top-left or in the left column) control:

Whether the stage is flagged as enabled in shared state.

Whether the corresponding stage card is visually enabled (but not necessarily hidden — that’s optional).

Keep semantics consistent with the existing Run tab implementation.

Leave Run tab code intact (for now)

Do not remove or disable the Run tab yet; just duplicate instantiation so both tabs now see working cards.

This allows a safe intermediate state for PR-001B.

7. Testing & Validation

Manual

Open the app, go to Pipeline tab:

Confirm txt2img, img2img, and upscale cards are visible with their full controls (not scaffold labels).

Toggle stages and ensure appropriate card behavior (enabled/disabled + any collapse logic).

Make small config tweaks (steps, CFG, upscaler) in Pipeline tab and run a single-stage test to confirm values flow through.

Automated

Update / add GUI tests under tests/gui_v2 to:

Assert that advanced stage cards exist under Pipeline tab container.

Confirm basic properties (widgets present, show/hide toggles wired).

Keep any existing Run-tab tests passing for now (removal later).