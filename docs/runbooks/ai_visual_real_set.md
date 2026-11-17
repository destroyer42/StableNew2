# Building the real-image evaluation set from Review (owner guide)

Purpose: give the visual candidates (LFM3-VL-2B fast tier, Gemma 4 12B deep tier) real images that **you** judged, so the
evaluation can say something about your outputs and not only about drawn shapes. You do this in the app you already use. A
read-only exporter then turns what you recorded into an evaluation set. Nothing here changes the image files, starts a model
or sends anything anywhere. Your images, prompts and notes stay on this computer and out of Git.

Read this first: Review can now record four kinds of evidence, all bound to the exact bytes of the image you looked at:

1. **Save inspection** (Inspect & Improve): the defects you confirmed (category, region, how sure you were, optional severity),
   or **No defect seen** for a clean image, plus an optional **Subjects in image**. It queues nothing. This is how you
   produce clean images, multi-subject images and defect images without paying for a correction job.
2. A defect you confirmed *and then queued a correction for* (the queued job records the finding too).
3. Your judgment of an original/corrected pair.
4. Per-item prompt adherence is still **not** recorded: it would need prompt-derived labels, which needs a separate decision.
   The evaluation reports prompt adherence as not measured.

If this is the first time you use Save inspection, the change is new and has not yet been tried in the live app: do one image
first and check the row in the Review list (step 1) before doing many.

## What counts

Only what you confirm yourself. An AI suggestion, an unconfirmed finding, a 1-5 rating and the app's pixel-difference check
are never exported as labels. Confirming a suggestion needs your own words describing the issue. The words you write in
**Visible issue** stay in the dialog: the saved inspection holds only the category, region, certainty, severity and count.

## Targets for a first useful set

| What | Target | Pilot (start here) | Can Review record it? |
| --- | --- | --- | --- |
| Images with a confirmed defect | 30 | 15 | Yes: Save inspection, or a queued correction |
| of which Hands | at least 8 | 4 | Yes |
| of which limbs (use **Anatomy**) | at least 8 | 4 | Yes |
| of which face or eyes (use **Face**) | at least 8 | 4 | Yes |
| Original/corrected pairs with your judgment | 12 | 6 | Yes (needs a queued correction and Step 3) |
| Images confirmed clean | 20 | 10 | Yes: **No defect seen** |
| Multi-subject images (2 or more subjects) | 10 | 5 | Yes: **Subjects in image** |

A 30-image pilot is a fine start: about 15 defect images, 10 clean images and 6 judged pairs. Choose images from your real
outputs across your usual models. Include clean images you would genuinely call fine, including ones with several people, and
include some corrections that do **not** help, because "no benefit" and "worse" are the answers the evaluation most needs.
Only call an image clean after you have looked at all of it: that label is how the evaluation measures false alarms.

Limits you will hit: guided corrections work only on a registry-resolved SDXL base image (other models are refused with a
reason), Edit Mask needs Forge, and each correction is a real queued generation job. Save inspection has none of those limits.

## Step 1. Save an inspection (clean or defective)

1. Open the **Review** tab, select **one** still image (PNG, JPEG or WebP) and show it. Look at all of it.
2. Click **Inspect & Improve…**.
3. If you see no defect: leave the findings empty, optionally type how many people or characters are in the picture in
   **Subjects in image** (1 to 12; leave it empty if you are not sure), and click **No defect seen**.
4. If you see one or more defects: for each one drag a box around it with **Draw region** (or click **Whole image**), set
   **Issue category** (**Hands** for hands, **Anatomy** for arms, legs and body shape, **Face** for face and eyes; the target
   counts use these three), set **Certainty** honestly, optionally set **Severity** (minor or major), set **Confirmation** to
   **Confirmed** only if you are sure, write the issue in your own words in **Visible issue**, and click **Record finding**.
   When all are recorded, optionally set **Subjects in image**, and click **Save inspection**.
5. Check the status line and the Review list: the image's row now ends with `(inspected: no defect)` or
   `(inspected: defects)`, and the status says the file was not changed and no job was queued.

Notes: only findings marked **Confirmed** are saved. **No defect seen** is refused while any finding is Confirmed (use Save
inspection) or Uncertain (set it to Confirmed or Rejected first), because a clean label must be one you are sure of. You can
save again for the same image later; the latest save counts. Saving does not close the dialog, so you can still continue to
Step 2 for the same image. If the app says the image changed or is hidden, reopen Inspect & Improve and save again.

To take back the last save, press **Undo (U)** in Review: a clearing record is added, the row mark disappears, and nothing is
deleted (it also hides an earlier inspection of the same image; save again if you want it back).

## Step 2. Optionally queue a correction (for before/after pairs)

Only needed for the judged-pair targets.

1. In the same dialog, pick an action in the action list (the app explains why one is unavailable). **ADetailer face pass** or
   **hand pass** are the cheapest for faces and hands.
2. Click **Open correction draft**, then **Preview frozen job**, check it, then **Add to Queue**.

A finding you only record, without Save inspection and without queuing a correction, is **not** saved anywhere and cannot be
exported.

## Step 3. Judge the result

When the job finishes:

1. In **Review**, select the **result** image and open **Inspect & Improve…**.
2. Click **Compare completed result**. If it says the source is not verified, you cannot save a judgment for that pair; skip it.
3. For each region you care about, pick the outcome in the list (improved, unchanged, worsened or uncertain) and click
   **Record judgment**. Set **Overall preference** if you have one. If you judge different regions differently (hands
   improved, face worsened) the pair is counted as `mixed` and does not count toward the pair target, so for the target
   judge one region per pair unless the difference matters.
4. Click **Save with Review ratings**. Check the **Review Feedback** status says the record was saved. Use **Undo** there if you
   saved by mistake.

Do not edit, rename-and-replace or re-save the original or result files afterwards (including "Write rating to file" for the
same file); the export accepts an image only if its bytes still match what was recorded. An inspection whose file changed is
excluded and counted as `inspection_image_changed_since_review`.

## Step 4. See progress with `describe`

`describe` prints **counts only**. It shows no image names, ids, prompts or notes. Run it from the StableNew checkout that holds
your data, with the app closed or open:

```bash
python -m tools.qualification.vl240 describe --targets pilot --content-visibility nsfw
```

Use `--targets full` for the full set. Add `--learning-records <path>` and `--job-repository <path>` only if your data is not in
this checkout's `data/` and `state/` folders. (If the repository cannot be read, copy `jobs.sqlite3` and any `jobs.sqlite3-wal`
beside it to another folder and point `--job-repository` at the copy.)

How to read it:

- `progress` lists each target with `have`, `target`, `remaining`, `met` and `recordable_in_review`. Aim for `remaining: 0`
  on every row. `clean_confirmed_images` and `multi_subject_images` now move when you save inspections.
- `counts.clean_confirmed_images`, `counts.inspections_by_verdict` (your latest saved verdict per image; `cleared` means you
  undid it), `counts.images_with_subject_count` and `counts.subject_counts` (1, 2, 3, 4, 5_or_more) show how many labels you
  have; `counts.findings_with_severity` shows how many findings carry a severity.
- `counts.defect_images_by_category` and `counts.pairs_by_judgment` show the spread; keep Hands, Anatomy and Face level, and
  keep some pairs in `no_benefit` and `worse`.
- `counts.withheld_by_visibility`: items hidden by the visibility mode. The tool defaults to `sfw` and hides restricted items;
  the app's own default is `nsfw`. If your images are adult content, pass `--content-visibility nsfw` as above or nearly
  everything is withheld.
- `counts.refused_by_reason` explains records it would not use. A refusal is a code, never content:
  - `inspection_image_changed_since_review` / `image_changed_since_review`: a file changed after you saved or judged it.
  - `inspection_image_unavailable` / `image_unavailable`: the file was moved or deleted.
  - `clean_contradicts_confirmed_finding`: you marked an image clean and also confirmed a defect on the same file (for
    example through a queued correction). Neither label is exported; decide which is true, then save the inspection again.
  - `malformed_inspection`: a saved inspection row the exporter could not read; it is skipped.
  - `job_not_found`, `no_recorded_source_digest` and similar describe pair and correction records.

## Step 5. Export (only when you decide)

```bash
python -m tools.qualification.vl240 export --content-visibility nsfw
```

This copies the images under hash names (never their original names) and writes `review_export.json` and `manifest.json` into
`D:\StableNew-Assets\offline-ai\visual-evaluation\vl240-<time>\`. It refuses any folder inside Git. Check an export with
`python -m tools.qualification.vl240 verify <folder>`. The export holds your images and labels but no prompt text and no
notes. Keep the folder private.
