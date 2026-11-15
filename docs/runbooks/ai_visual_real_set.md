# Building the real-image evaluation set from Review (owner guide)

Purpose: give the visual candidates (LFM3-VL-2B fast tier, Gemma 4 12B deep tier) real images that **you** judged, so the
evaluation can say something about your outputs and not only about drawn shapes. You do this in the app you already use. A
read-only exporter then turns what you recorded into an evaluation set. Nothing here changes the app, starts a model or
sends anything anywhere. Your images, prompts and notes stay on this computer and out of Git.

Read this first: **what the app can record today is narrower than the full wish list.** Review can record (1) a defect you
confirmed *and then queued a correction for*, and (2) your judgment of an original/corrected pair. It cannot yet record
"inspected, no defect" for a clean image, how many subjects an image has, severity, or per-item prompt adherence. So two of
the four targets below (clean images, multi-subject images) cannot be produced yet. The exporter says so in its output
instead of guessing. Do the parts that work now; the missing parts need a small Review change that is your decision (see
`docs/work_packages/AI-VL-240_review_label_export.md`, section 3).

## What counts

Only what you confirm yourself. An AI suggestion, an unconfirmed finding, a 1-5 rating and the app's pixel-difference check
are never exported as labels. Confirming a suggestion needs your own words describing the issue.

## Targets for a first useful set

| What | Target | Pilot (start here) | Can Review record it today? |
| --- | --- | --- | --- |
| Images with a confirmed defect | 30 | 15 | Yes, via a queued correction |
| of which Hands | at least 8 | 4 | Yes |
| of which limbs (use **Anatomy**) | at least 8 | 4 | Yes |
| of which face or eyes (use **Face**) | at least 8 | 4 | Yes |
| Original/corrected pairs with your judgment | 12 | 6 | Yes |
| Images confirmed clean | 20 | 10 | **No, not yet** |
| Multi-subject images | 10 | 5 | **No, not yet** |

One correction gives you both a defect image and (once it finishes and you judge it) a pair, so 30 corrected defects can
also supply the 12 pairs. A 30-image pilot is a fine start: about 15 defect images, 6 judged pairs. Choose images from your
real outputs across your usual models, and include some where the correction does **not** help, because "no benefit" and
"worse" are the answers the evaluation most needs.

Limits you will hit: guided corrections work only on a registry-resolved SDXL base image (other models are refused with a
reason), Edit Mask needs Forge, and each correction is a real queued generation job. Defects on images the app cannot correct
cannot be recorded yet.

## Step 1. Confirm a defect and queue a correction

1. Open the **Review** tab, select **one** still image (PNG, JPEG or WebP) and show it.
2. Click **Inspect & Improve…**.
3. Drag a box around the defect with **Draw region**, or click **Whole image** if the problem is the whole picture.
4. Set **Issue category**: **Hands** for hands, **Anatomy** for arms, legs and body shape, **Face** for face and eyes (the
   target counts use these three). Set **Certainty** honestly. Set **Confirmation** to **Confirmed** only if you are sure.
5. Write the visible issue in your own words in **Visible issue**, then **Record finding**. The text stays in the dialog and is
   never exported.
6. Pick an action in the action list (the app explains why an action is unavailable). **ADetailer face pass** or **hand pass**
   are the cheapest for faces and hands.
7. Click **Open correction draft**, then **Preview frozen job**, check it, then **Add to Queue**. Do not leave the dialog before
   the queue step: the confirmed defect is recorded by the queued job, not by the dialog.

A finding you record but never queue a correction for is **not** saved anywhere and cannot be exported.

## Step 2. Judge the result

When the job finishes:

1. In **Review**, select the **result** image and open **Inspect & Improve…**.
2. Click **Compare completed result**. If it says the source is not verified, you cannot save a judgment for that pair; skip it.
3. For each region you care about, pick the outcome in the list (improved, unchanged, worsened or uncertain) and click
   **Record judgment**. Set **Overall preference** if you have one.
4. Click **Save with Review ratings**. Check the **Review Feedback** status says the record was saved. Use **Undo** there if you
   saved by mistake.

Do not edit, rename-and-replace or re-save the original or result files afterwards (including "Save with Review ratings" on
the ordinary form for the same file); the export accepts an image only if its bytes still match what was recorded.

## Step 3. See progress with `describe`

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
  on the rows marked `true`; the `false` rows will stay at 0 until Review can record them.
- `counts.defect_images_by_category` and `counts.pairs_by_judgment` show the spread; keep Hands, Anatomy and Face level, and
  keep some pairs in `no_benefit` and `worse`.
- `counts.withheld_by_visibility`: items hidden by the visibility mode. The tool defaults to `sfw` and hides restricted items;
  the app's own default is `nsfw`. If your images are adult content, pass `--content-visibility nsfw` as above or nearly
  everything is withheld.
- `counts.refused_by_reason` explains records it would not use: `image_changed_since_review` (a file changed after you judged
  it), `image_unavailable` (moved or deleted), `job_not_found`, `no_recorded_source_digest`, and so on. A refusal is a code,
  never content.

## Step 4. Export (only when you decide)

```bash
python -m tools.qualification.vl240 export --content-visibility nsfw
```

This copies the images under hash names (never their original names) and writes `review_export.json` and `manifest.json` into
`D:\StableNew-Assets\offline-ai\visual-evaluation\vl240-<time>\`. It refuses any folder inside Git. Check an export with
`python -m tools.qualification.vl240 verify <folder>`. The export holds your images and labels but no prompt text and no
notes. Keep the folder private.
