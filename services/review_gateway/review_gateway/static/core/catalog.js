// The wording of phone actions and of the PC's answers, shared by the actions, queued and outbox screens.

import { el } from "./dom.js";
import { REASONS } from "./text.js";

// RG-140 phone actions. The PC compiles and decides; the phone shows its summary, warnings and receipts as text.
export const ACTIONS = [
  ["fix_face", "Fix face"],
  ["fix_hands", "Fix hands"],
  ["fix_both", "Fix both"],
  ["more_like_this", "More like this"],
  ["another_model", "Another model"],
  ["aspect_ratio", "Aspect ratio"],
  ["prompt_tweak", "Tweak prompt"],
  ["make_video", "Make video"],
];
// V1-6: what a video offers instead.
export const CLIP_ACTIONS = [["continue_clip", "Continue clip"]];
// Slice 2. A picker action first asks the PC for its options; a words action asks the owner first.
export const PICKERS = {
  another_model: "Choose a checkpoint on the PC. The image is run through it with img2img.",
  aspect_ratio: "Choose a shape. Outpainting adds space around the image; every original pixel is kept.",
};
export const WORDS = {
  prompt_tweak: { required: true, hint: "Words added to this image's prompt, then img2img of the image.", placeholder: "smiling, golden hour" },
  make_video: { required: false, hint: "What should move? Leave it empty to use the image's own prompt.", placeholder: "she turns towards the window" },
  continue_clip: { required: false, hint: "What happens next? Leave it empty to keep the clip's own prompt.", placeholder: "she sits down" },
};
// PHONE-FAST: actions that replace the image (the gateway holds the same list). The original then counts as reviewed
// until the result arrives and one of the two is kept.
export const REWORK = new Set(["fix_face", "fix_hands", "fix_both", "another_model", "aspect_ratio"]);
const SLICE_TWO = new Set(["another_model", "aspect_ratio", "prompt_tweak", "make_video", "continue_clip"]);
const DETAILS = {
  not_an_image: "only images can be fixed",
  source_changed: "the image changed on the PC",
  provenance_unverified: "the PC cannot find the job that made this",
  recipe_not_variable: "this image cannot be re-run with new seeds (it was made from another image, such as a face or hands fix)",
  model_unavailable: "the checkpoint is not available",
  model_family_refused: "the checkpoint cannot run this fix",
  adetailer_unavailable: "ADetailer is not available; connect Forge on the PC",
  detector_unavailable: "Forge lists no detector for this pass",
  operation_unsupported: "the backend cannot run this",
  choice_unavailable: "that option is not on the PC any more; choose again",
  no_change: "that is what the image already has",
  prompt_required: "there are no words to use for the prompt",
  size_unsupported: "the new canvas would be too large",
  video_unavailable: "the PC has no approved Make Video workflow",
  app_busy: "StableNew was busy; try again",
  app_shutting_down: "StableNew is shutting down",
  compile_failed: "the PC could not prepare it",
};

export const actionLabel = (action) => Object.fromEntries([...ACTIONS, ...CLIP_ACTIONS])[action];

export function refusalText(answer) {
  // A PC from before RG-140 slice 2 knows only the first four actions: it refuses the others as invalid.
  if (answer.reason_code === "invalid_record" && SLICE_TWO.has(answer.action)) {
    return "StableNew on the PC does not offer this action yet. Update it and try again.";
  }
  const reason = REASONS[answer.reason_code] || "no reason given";
  const detail = answer.receipt && DETAILS[answer.receipt.detail];
  return detail ? `${reason}: ${detail}.` : `${reason}.`;
}

export function warningBlock(warning) {
  return el("div", { class: "warning" }, [
    el("p", { class: "warning-title", text: `⚠ ${warning.title}` }),
    warning.why ? el("p", { text: warning.why }) : null,
    warning.fix ? el("p", { class: "muted", text: warning.fix }) : null,
  ]);
}
