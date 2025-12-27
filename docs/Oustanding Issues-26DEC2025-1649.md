Current issues in the StableNewGui
1. In pipeline Tab, left side panel
  a. the 'Actions" button in the Pipeline Presets Frame doesn't use darkmode
  b. The 'Refresh' button in the Pack Selector Frame doesn't actually refresh the Prompt Pack list
  c. the 'Refresh' button also doesn't use darkmode
  d. The 'Load Config', 'Apply Config', 'Add to Job' and 'Show Preview' buttons do not use dark mode
  e. The 'Global Prompts' Frame doesn't use darkmode
  f. Need to confirm functionality of the Save Global Positive and Save Global Negative buttons. Expected action: saving would overwrite default Global Positive or Global Negative (so always shown in these fields) but only when 'Enable" checkbox is clicked would the Global positive or Global negative be pre-pended to the prompts. Prompt pack configs should save the "state" of the checkboxes when 'Apply Config' button is clicked. 
  g. Remove 'Filename' label and textbox from Output Settings frame (filenaming is hardcoded to prevent duplication)
  h. Move the elements around better in the Output settings frame. The 'Output Dir' label, textbox, and browse button should span the whole frame (widen the text field to show more of the path), and the 'Format' with dropdown, 'batch size' with spin buttons, and 'Seed Mode' with dropdown can all fit on the same line below the Output Dir textbox.
  i. The 'Browse' button for Output Dir isn't using darkmode
  j. the Batch Size spin button isn't using darkmode
  k. Almost all of the widgets/elements in Reprocess images is not using darkmode. 
    k-1. The label/txt box that starts with "Select existing images to send through..." can go all the way across the panel/frame so it only takes up one line
  l. Move the 3 buttons 'Select Images', 'Select Folder(s)...' and 'Clear Selection' into the same row and make them use darkmode variant
  m. move 'Max width:' and 'Max height' with their spin boxes up one row to be next to the "Filter by max dimension:" checkbox
  n. 'Refresh filter' - not dark mode and unclear what it does. What is it refreshing?
  o. 'Filter Results' frame is not using darkmode
  p. 'Stages to Apply' frame isn't using dark mode
  q. Move all 3 checkboxes with labels onto the same line (img2img, Adetailer, and Upscale)
  
 2. In pipeline Tab, central panel
   a. in Txt2Img Configuration frame, make the 'CFG' Slider go all the way across the frame to the edge
   b. Subseed needs a randomizer button as well (just like Seed has), and subseed strength needs a randomizer button (but only random between 0.0 and 1.0)
   c. SDXL Refiner label needs to be dark mode
   d. SDXL Refiner's 'Refiner Start' default needs to be set at 80 percent if not previously configured and saved in a prompt pack
   e. Hires fix label needs to use dark mode
   f. Hires fix 'Use base model during hires' - if checked, updates hires model to be Txt2img Configuration's base model (visually changed as if the user selected it from the dropdown box), and disables dropdown of 'Hires model' until unchecked
   g. shorten the 'Mask merge mode:" dropdown to be in line with 'Mask Blur:'s spin box. 
   h. For 'Confidence:', 'Max detections:', 'Mask blur:' and 'Mask merge mode:' put a label/txt to the right with a short one sentence of what the config is/does, and then on hover over the word/label have a more detailed description that appears on hover
   i. Do the exact same for the Mask filtering section (make Filter method drop down more narrow, add the description of what that config does/is/means, and more detailed information when hovering over it.
   j. Do the same for the 'Mask Processing' section
   k. make the default 'size' of the Positive and Negative prompt fields (change the 'Prompt:' to be 'Positive:') to be 3 lines tall, and add scrollbars if the prompt text exceeds the 3 lines. 
   l. Add hover and descriptor text for the 'Inpaint Settings' section as well
   m. in the Upscale Configuration frame, if 'Face restore' is checked, it should reveal a dropdown box with two options GFPGAN and Codeformers (have the better one be the default) (currently no option to pick between the face restorers).
   n. Final size: doesn't actually work (it's not calculating the final size of the image after the upscale, taking into account the txt2img and hires fix size and outputs. 

 3. In preview/queue/pipeline tab on Right
   a. 'Show preview thumbnails' doesn't use dark mode
   b. Layout for the 'Preview' frame is not optimized. Move the thumbnail previewer over to the far right side, move the text that's underneath up and to the Left side of the thumbnail box. Then rearrange the labels to take/make better use of the space
   c. Make the positive and negative prompt show the full prompt for each (just have it expand the preview panel if needed)
   d. Still doesn't show that when a queued job is selected, if the up or down key is hit, it doesn't visually show that job moving up or down in the queue (not clear that it is or isn't moving, but it appears like nothing has changed. Same with 'Front' and 'Back' buttons. It's not updating the queue with the new order
   e. In 'Running Job' frame, Seed: doesn't show anything, and the 3 text fields aren't using Darkmode. 
   f. The 'Pause Job' and 'Cancel Job' button are disabled, so you can't ever pause or cancel the actively running job.
   g. The variant # for the image isn't being incremented. Also the Output field is still wrong, selecting a job and hitting open output folder, should take you to where the job was saved. Currently it opens the /runs/ folder (not where images are being stored).
   h. Job Lifecycle Log shows nothing, might as well remove it. The Panel that shows Jobs and Metadata is non-functional shows only the processes, but that's not useful (can get the same from task manager). Remove it.
   
   
   