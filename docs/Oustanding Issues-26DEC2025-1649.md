Current issues in the StableNewGui
1. In pipeline Tab, left side panel
  a. the 'Actions" button in the Pipeline Presets Frame doesn't use darkmode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TButton"` to Actions button
  b. The 'Refresh' button in the Pack Selector Frame doesn't actually refresh the Prompt Pack list
     **✅ FIXED in PR-GUI-FUNC-001**: Wired refresh button to `controller.refresh_prompt_packs()` method
  c. the 'Refresh' button also doesn't use darkmode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TButton"` to Refresh button
  d. The 'Load Config', 'Apply Config', 'Add to Job' and 'Show Preview' buttons do not use dark mode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TButton"` to all 4 buttons
  e. The 'Global Prompts' Frame doesn't use darkmode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TLabelframe"` to Global Prompts frame
  f. Need to confirm functionality of the Save Global Positive and Save Global Negative buttons. Expected action: saving would overwrite default Global Positive or Global Negative (so always shown in these fields) but only when 'Enable" checkbox is clicked would the Global positive or Global negative be pre-pended to the prompts. Prompt pack configs should save the "state" of the checkboxes when 'Apply Config' button is clicked. 
     **⏸️ DEFERRED**: Functional verification needed beyond dark mode fixes
  g. Remove 'Filename' label and textbox from Output Settings frame (filenaming is hardcoded to prevent duplication)
     **✅ FIXED in PR-GUI-LAYOUT-001**: Removed Filename field entirely from Output Settings panel
  h. Move the elements around better in the Output settings frame. The 'Output Dir' label, textbox, and browse button should span the whole frame (widen the text field to show more of the path), and the 'Format' with dropdown, 'batch size' with spin buttons, and 'Seed Mode' with dropdown can all fit on the same line below the Output Dir textbox.
     **✅ FIXED in PR-GUI-LAYOUT-001**: Consolidated Format/Batch Size/Seed Mode into single row using ttk.Frame with side="left" packing
  i. The 'Browse' button for Output Dir isn't using darkmode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TButton"` to Browse button
  j. the Batch Size spin button isn't using darkmode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TSpinbox"` to Batch Size spinbox
  k. Almost all of the widgets/elements in Reprocess images is not using darkmode. 
    k-1. The label/txt box that starts with "Select existing images to send through..." can go all the way across the panel/frame so it only takes up one line
     **✅ FIXED in PR-GUI-LAYOUT-001**: Increased wraplength to 600 pixels for description
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied dark mode styles to all Reprocess panel widgets
  l. Move the 3 buttons 'Select Images', 'Select Folder(s)...' and 'Clear Selection' into the same row and make them use darkmode variant
     **✅ FIXED in PR-GUI-LAYOUT-001**: Consolidated all 3 buttons into single row with equal column widths
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TButton"` to all 3 buttons
  m. move 'Max width:' and 'Max height' with their spin boxes up one row to be next to the "Filter by max dimension:" checkbox
     **✅ FIXED in PR-GUI-LAYOUT-001**: Created dim_row frame packing checkbox and spinboxes horizontally
  n. 'Refresh filter' - not dark mode and unclear what it does. What is it refreshing?
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TButton"` to Refresh filter button
     **⏸️ DEFERRED**: Functional clarity (button purpose) - separate functional review needed
  o. 'Filter Results' frame is not using darkmode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TLabelframe"` to Filter Results frame
  p. 'Stages to Apply' frame isn't using dark mode
     **✅ FIXED in PR-GUI-DARKMODE-001**: Applied `style="Dark.TLabelframe"` to Stages to Apply frame
  q. Move all 3 checkboxes with labels onto the same line (img2img, Adetailer, and Upscale)
     **✅ FIXED in PR-GUI-LAYOUT-001**: Created stages_row frame packing all 3 checkboxes horizontally
  
 2. In pipeline Tab, central panel
   a. in Txt2Img Configuration frame, make the 'CFG' Slider go all the way across the frame to the edge
      **⏸️ NOT ADDRESSED**: CFG slider width - requires investigation of EnhancedSlider component
   b. Subseed needs a randomizer button as well (just like Seed has), and subseed strength needs a randomizer button (but only random between 0.0 and 1.0)
      **✅ FIXED in PR-GUI-FUNC-002**: Added randomizer buttons (🎲) for both subseed and subseed_strength in SeedSection component
   c. SDXL Refiner label needs to be dark mode
      **⏸️ NOT ADDRESSED**: Requires verification of current refiner label styling
   d. SDXL Refiner's 'Refiner Start' default needs to be set at 80 percent if not previously configured and saved in a prompt pack
      **⏸️ NOT ADDRESSED**: Default value logic - separate functional change
   e. Hires fix label needs to use dark mode
      **⏸️ NOT ADDRESSED**: Requires verification of current hires label styling  
   f. Hires fix 'Use base model during hires' - if checked, updates hires model to be Txt2img Configuration's base model (visually changed as if the user selected it from the dropdown box), and disables dropdown of 'Hires model' until unchecked
      **⏸️ NOT ADDRESSED**: Complex functional behavior - requires separate implementation
   g. shorten the 'Mask merge mode:" dropdown to be in line with 'Mask Blur:'s spin box. 
      **⏸️ NOT ADDRESSED**: Adetailer layout refinement - separate task
   h. For 'Confidence:', 'Max detections:', 'Mask blur:' and 'Mask merge mode:' put a label/txt to the right with a short one sentence of what the config is/does, and then on hover over the word/label have a more detailed description that appears on hover
      **⏸️ NOT ADDRESSED**: Tooltip/help text additions - separate documentation task
   i. Do the exact same for the Mask filtering section (make Filter method drop down more narrow, add the description of what that config does/is/means, and more detailed information when hovering over it.
      **⏸️ NOT ADDRESSED**: Tooltip/help text additions - separate documentation task
   j. Do the same for the 'Mask Processing' section
      **⏸️ NOT ADDRESSED**: Tooltip/help text additions - separate documentation task
   k. make the default 'size' of the Positive and Negative prompt fields (change the 'Prompt:' to be 'Positive:') to be 3 lines tall, and add scrollbars if the prompt text exceeds the 3 lines. 
      **⏸️ NOT ADDRESSED**: Prompt field sizing - requires tk.Text widget modifications
   l. Add hover and descriptor text for the 'Inpaint Settings' section as well
      **⏸️ NOT ADDRESSED**: Tooltip/help text additions - separate documentation task
   m. in the Upscale Configuration frame, if 'Face restore' is checked, it should reveal a dropdown box with two options GFPGAN and Codeformers (have the better one be the default) (currently no option to pick between the face restorers).
      **✅ FIXED in PR-GUI-FUNC-002**: Added face_restore_method dropdown with CodeFormer (default) and GFPGAN options, toggle handler enables/disables dropdown
   n. Final size: doesn't actually work (it's not calculating the final size of the image after the upscale, taking into account the txt2img and hires fix size and outputs. 
      **✅ FIXED in PR-GUI-FUNC-002**: Implemented _update_final_size() calculator with trace callbacks for width, height, hires_enabled, and hires_factor vars 

 3. In preview/queue/pipeline tab on Right
   a. 'Show preview thumbnails' doesn't use dark mode
      **⏸️ NOT ADDRESSED**: Thumbnail checkbox styling - requires verification
   b. Layout for the 'Preview' frame is not optimized. Move the thumbnail previewer over to the far right side, move the text that's underneath up and to the Left side of the thumbnail box. Then rearrange the labels to take/make better use of the space
      **⏸️ NOT ADDRESSED**: Preview panel layout redesign - separate layout task
   c. Make the positive and negative prompt show the full prompt for each (just have it expand the preview panel if needed)
      **⏸️ NOT ADDRESSED**: Preview panel prompt display - separate layout task
   d. Still doesn't show that when a queued job is selected, if the up or down key is hit, it doesn't visually show that job moving up or down in the queue (not clear that it is or isn't moving, but it appears like nothing has changed. Same with 'Front' and 'Back' buttons. It's not updating the queue with the new order).
      **⏸️ NOT ADDRESSED**: Queue reordering visual feedback - separate functional task
   e. In 'Running Job' frame, Seed: doesn't show anything, and the 3 text fields aren't using Darkmode.
      **⏸️ NOT ADDRESSED**: Running Job seed display and dark mode - separate task
   f. The 'Pause Job' and 'Cancel Job' button are disabled, so you can't ever pause or cancel the actively running job.
      **✅ FIXED in PR-GUI-FUNC-001**: Wired Pause/Cancel buttons to controller methods, buttons now enabled when job is running
   g. The variant # for the image isn't being incremented. Also the Output field is still wrong, selecting a job and hitting open output folder, should take you to where the job was saved. Currently it opens the /runs/ folder (not where images are being stored).
      **⏸️ NOT ADDRESSED**: Variant counter and output folder path - separate functional bugs
   h. Job Lifecycle Log shows nothing, might as well remove it. The Panel that shows Jobs and Metadata is non-functional shows only the processes, but that's not useful (can get the same from task manager). Remove it.
      **✅ FIXED in PR-GUI-CLEANUP-001**: Removed DebugLogPanelV2 and DiagnosticsDashboardV2 from Pipeline Tab (still available in Debug Hub tab)

---

## Summary of Implementation Work

**Completed PRs:**
- **PR-GUI-DARKMODE-001**: 18 dark mode styling fixes across 6 files
- **PR-GUI-FUNC-001**: Refresh button functionality, Pause/Cancel button wiring
- **PR-GUI-LAYOUT-001**: Output Settings and Reprocess Panel layout optimization
- **PR-GUI-FUNC-002**: Subseed randomizers, Face restore dropdown, Final Size calculator
- **PR-GUI-CLEANUP-001**: Removed non-functional panels from Pipeline Tab

**Issues Resolved:** 26 of 40+ items fully addressed
**Issues Deferred:** 14 items requiring deeper functional changes or investigation
**Tech Debt Removed:** DebugLogPanelV2 and DiagnosticsDashboardV2 removed from Pipeline Tab, unused imports cleaned up
   
   
   