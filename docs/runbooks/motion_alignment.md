# Aligning a driving motion to a source image

Use **Align Motion** when a driving clip's subject sits in a different part of the frame, or at a different size, than the subject in your source image, and you want to fix that explicitly before generating. It moves and scales the whole driving motion inside the source image's frame with one constant transform you can see and reproduce. Nothing here queues a job or uses the GPU, and the original driving video and the Motion Library asset are never changed.

Design record and exact contract: `docs/Subsystems/Video/PR-VID-MOTION-420_Subject_Alignment_and_Compatibility.md`.

## When alignment helps, and when it cannot

It can help when the difference is only **where** and **how large**: the figure is off-centre, much smaller or larger than yours, or the driving clip is framed tighter or wider.

It **cannot** fix a difference in the subjects themselves, and it does not try to:

* a different starting pose (arms down versus arms up, head turned versus facing the camera);
* a different viewpoint (front versus side), or a driver that shows a full body when your image is a close-up;
* a driver with a moving camera, several people, or a movement that needs room your image does not have;
* different body proportions. Alignment is not retargeting, pose estimation or tracking: no landmark is detected, the subject is never re-centred frame by frame, and no body part is moved on its own.

The **Compatibility** panel names these mismatches (always as advice, never as a block). A preview that looks well aligned is not evidence that the generated motion will transfer; that is what an evaluation shows.

## What you need

A workflow that takes a driving video and whose resize is verified for alignment (today: **Wan-Animate-2 Driving Video Motion**; other workflows say why they are not offered), a source image, a driving video (a Motion Library clip is fine), and the length you want. The row `Alignment: ... [Align Motion...]` appears under the driving-motion panel.

## Using the workspace

1. **Open** `Align Motion...`. The first, middle and last frames of the selected window are decoded (never the GPU). The left view is your prepared source image at its true frame size; the right is the driving frame as the workflow would use it today (**Original motion**) or after your changes (**Aligned motion**). White line: the target frame. Dashed yellow: where the whole driving frame sits; gray areas are fill.
2. **Position and size.** Scale is uniform (about the frame centre); Shift moves the motion right/down in target pixels (negative moves left/up); the arrows nudge by 10. Values outside the supported range are refused with a message, never quietly changed.
3. **Mirror** flips the motion left-to-right. It reverses the movement's direction and swaps left and right, so it is off unless you turn it on, it is flagged whenever on, and your motion prompt is never rewritten.
4. **Corresponding points** (optional). Choose a point type (head, shoulders, hip, feet or other), press *Mark pair*, click the point on the source image, then the same point on the driving frame. Mark one pair for position, two or more for position and scale. *Suggest alignment* fits scale and shift by least squares and shows the residual error and any conflict (for example points that disagree about size). It is only a proposal: *Accept* copies it into the controls, *Discard* drops it, and editing a number afterwards makes it your own. Pairs you mark are things you say, not detected landmarks.
5. **Check the whole movement, not only the first frame.** Step through or play the decoded frames (*Also inspect frame* adds one more). Enter the subject's bounds (`x0,y0,x1,y1`) for the source, for the driver at the first frame, and at other frames to see where they land and whether the frame boundary clips them. The report says how many frames it covered; sampled frames are never presented as proof the whole clip fits.
6. **Overlay** blends the two views with adjustable opacity; *Reset to unaligned* returns the controls to no change.
7. **Apply and prepare.** This accepts the alignment for *this* source image, driving clip, window, workflow and length, and prepares the exact aligned frames (a lossless RGB clip, content-addressed). The same constant transform is applied to every selected frame. Preview and the published clip are the same pixels.

The status word says where you are: **Not applied**, **Editing** (unapplied changes), **Preparation required**, **Preparing**, **Verified**, **Stale** (something it depends on changed: the source image, the clip or either file's bytes, the window, the rate conversion, the workflow, its version or the length), **Failed or unsupported**. A stale, failed, running or unprepared alignment stops submission with the reason; it never falls back to the unaligned clip. *Prepare again* re-runs it; *Discard alignment* returns to ordinary preparation.

## What gets frozen

The job runs the aligned clip. It records: the original driving video's hash (unchanged; the Motion Library identity stays with it), the aligned clip's own hash, the source image and its prepared reference, the exact transform (including how the numbers were chosen), the frame selection, and the tool versions. Replay and Check inputs use the frozen clip and never recompute an alignment. The aligned clip belongs to one source image: another image needs its own alignment (a batch refuses a source the clip was not made for).

## Judging whether it helped

Use the evaluation kit, not the preview. A case declares its alignment and two arms differ only in whether it is applied (`docs/runbooks/video_eval_kit.md`, section 10; templates in `docs/runbooks/examples/video_eval_motion_alignment_*.suite.json`). The comparison verifies that the original driver, the frame selection, the seed and every other setting are identical; the prepared clip differs by design. The review rates action achievement, subject attachment, motion fidelity, identity, anatomy and continuity as for any motion case, and alignment success in the preview stays separate from generated-motion success.

## If something is refused

* *"outside the supported 0.25 to 4"* / *"more than one frame from the centred placement"*: the scale or shift is out of range.
* *"no longer overlaps the target frame"*: the placement moved the driving frame out of view.
* *"points too close together"* / *"disagree about the scale"*: re-mark the pairs further apart or check each marks the same body point.
* *"Alignment is not offered..."*: the selected workflow cannot honestly take an aligned clip (the reason is shown).
* *"different source image"* / *"out of date"*: align and prepare again for the current inputs.
* *"frame too large"* / *"distinct source frames"*: the clip exceeds the 9 megapixel or 96-frame preparation limits.

## Experimental and unverified

Alignment is a preparation tool. That the aligned clip equals the declared transform of the selected frames is verified for every preparation; that aligned conditioning improves generated motion, or is better than leaving the clip alone, is **not** established. Wan-Animate-2 remains experimental and per-job opt-in, and nothing here promotes a workflow or changes a default.
