// The action row, its words and pickers, the PC's summary and the receipt (RG-140).

import { api, idempotencyKey } from "../../core/api.js";
import { closeSheet, el, sheet } from "../../core/dom.js";
import { queueDecision } from "../../core/outbox.js";
import { canQueue } from "../../core/session.js";
import { currentTriage, findItem, key, needsReview } from "../../core/store.js";
import { REASONS } from "../../core/text.js";
import * as Queued from "../queued/queued.js";
import { advance, updateTriageStatus } from "../triage/triage.js";

// RG-140 phone actions. The PC compiles and decides; the phone shows its summary, warnings and receipts as text.
const ACTIONS = [
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
const CLIP_ACTIONS = [["continue_clip", "Continue clip"]];
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
const ACTION_POLL_MS = 1000;

const ACTION_WAIT_MS = 10 * 60 * 1000;

// Sent for rework: the item counts as reviewed at once; a refusal puts it back.
export function markRework(item, sent) {
  for (const copy of [item, ...findItem(key(item))]) {
    if (sent && needsReview(copy)) {
      copy.before = copy.state;
      copy.state = "rework";
    } else if (!sent && copy.state === "rework" && copy.before) {
      copy.state = copy.before;
    }
  }
  updateTriageStatus();
}

export function closeAfterRework(item) {
  closeSheet();
  const triage = currentTriage();
  if (triage && key(triage.list[triage.index]) === key(item) && item.state === "rework") advance();
}

// --- phone actions (RG-140) ---------------------------------------------------------------------------------------
// Two steps, both outbox requests: "prepare" asks the PC for a summary of exactly what it would queue; "Queue" sends
// "confirm" naming that summary. Nothing is queued until the PC admits it, and its receipt is shown.

// Asking for a fix says what is wrong with the image, so the matching reason tags are switched on (and a decision
// already made for it is resent with them).
const FIX_TAGS = { fix_face: ["face"], fix_hands: ["hands"], fix_both: ["face", "hands"] };

function addTags(item, wanted) {
  const triage = currentTriage();
  if (!triage || triage.list[triage.index] !== item) return;
  const before = triage.tags.size;
  for (const tag of wanted) triage.tags.add(tag);
  for (const button of document.querySelectorAll(".tags button[data-tag]")) {
    button.setAttribute("aria-pressed", String(triage.tags.has(button.dataset.tag)));
  }
  const decision = item.decision;
  if (triage.tags.size !== before && decision && decision.verdict === "keep") {
    queueDecision(item, "keep", decision.favorite, [...triage.tags]);
    updateTriageStatus();
  }
}

export function actionRow(item) {
  const offered = item.kind === "image" ? ACTIONS : item.kind === "video" ? CLIP_ACTIONS : null;
  if (!offered || !canQueue()) return null;
  return el(
    "div",
    { class: "fixes", role: "group", "aria-label": "Ask the PC" },
    offered.map(([action, text]) =>
      el("button", {
        type: "button",
        text,
        onclick: () => {
          if (FIX_TAGS[action]) addTags(item, FIX_TAGS[action]);
          if (Queued.offer(item, action)) return; // RG-160: the PC is away
          if (WORDS[action]) askWords(item, action);
          else openAction(item, action);
        },
      }),
    ),
  );
}

export const actionLabel = (action) => Object.fromEntries([...ACTIONS, ...CLIP_ACTIONS])[action];

function askWords(item, action) {
  const { required, hint, placeholder } = WORDS[action];
  const label = actionLabel(action);
  const input = el("input", { maxlength: "200", placeholder, "aria-label": label, autocomplete: "off" });
  const error = el("p", { class: "error", role: "alert" });
  const go = () => {
    // One line of plain text: the PC refuses control characters, so they never leave the phone.
    const text = input.value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, 200);
    if (required && !text) {
      error.textContent = "Type a few words first.";
      return;
    }
    openAction(item, action, text ? { text } : {});
  };
  input.addEventListener("keydown", (event) => event.key === "Enter" && go());
  sheet(
    el("h2", { text: label }),
    el("p", { class: "muted", text: hint }),
    input,
    error,
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", text: "Cancel", onclick: closeSheet }),
      el("button", { type: "button", class: "primary", text: "Ask the PC", onclick: go }),
    ]),
  );
  input.focus();
}

function showChoices(item, action, choices) {
  const buttons = choices.items.map((choice) =>
    el("button", {
      type: "button",
      text: choice.current ? `${choice.label} (this image)` : choice.label,
      "aria-pressed": String(choice.id === choices.selected),
      onclick: () => openAction(item, action, { choice: choice.id }),
    }),
  );
  return sheet(
    el("h2", { text: actionLabel(action) }),
    el("p", { class: "muted", text: PICKERS[action] }),
    el("div", { class: "choices", role: "group", "aria-label": "Options" }, buttons),
    el("div", { class: "sheet-actions" }, [el("button", { type: "button", text: "Cancel", onclick: closeSheet })]),
  );
}

function waitFor(recordId, alive) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      if (!alive()) return resolve(null);
      try {
        const answer = await api(`/api/actions/${recordId}`);
        if (answer.state !== "pending") return resolve(answer);
      } catch (error) {
        if (error.status === 401 || error.status === 403 || error.status === 404) return reject(error);
      }
      if (Date.now() - started > ACTION_WAIT_MS) return resolve({ state: "pending" });
      setTimeout(tick, ACTION_POLL_MS);
    };
    tick();
  });
}

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

function summaryView(summary) {
  const where = summary.queue_position === "next" ? "runs next" : "joins the end of the queue";
  const jobs = `${summary.job_count} job${summary.job_count === 1 ? "" : "s"}, ${where}`;
  return [
    el("h2", { text: summary.title }),
    ...summary.lines.map((line) => el("p", { text: line })),
    el("p", { class: "muted", text: jobs }),
    ...summary.warnings.map(warningBlock),
  ];
}

// One request at a time per sheet; the same idempotency key is resent until the gateway answers.
async function sendAction(body) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await api("/api/actions", body);
    } catch (error) {
      if (error.status || attempt >= 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
}

async function openAction(item, action, extra = {}) {
  if (Queued.offer(item, action, extra)) return;
  const label = actionLabel(action);
  const asking = PICKERS[action] && !extra.choice ? "Asking the PC for its options…" : "Asking the PC for a summary…";
  const node = sheet(el("h2", { text: label }), el("p", { class: "muted", text: asking }));
  const alive = () => document.getElementById("sheet") === node;
  const cancel = () =>
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", class: "primary", text: "Close", onclick: closeSheet }),
    ]);
  const fail = (text) => alive() && sheet(el("h2", { text: label }), el("p", { class: "error", text }), cancel());
  const params = { step: "prepare", ...extra };
  if (action === "more_like_this") params.count = 4;
  const body = {
    library_id: item.library_id,
    sha256: item.sha256,
    action,
    params,
    idempotency_key: idempotencyKey(),
  };
  try {
    const { record_id: recordId } = await sendAction(body);
    if (alive()) Queued.watch(node, item, action, recordId, "prepare");
    const answer = await waitFor(recordId, alive);
    if (answer) showAnswer(item, action, recordId, answer, cancel, fail);
  } catch (error) {
    if (!error.status && alive() && Queued.unreachable(item, action)) return;
    fail(error.status === 429 ? "Too many requests from this phone for now." : `Not sent: ${error.code || "no connection"}.`);
  }
}

function showAnswer(item, action, recordId, answer, cancel, fail) {
  const label = actionLabel(action);
  if (answer.state === "pending") return fail("The PC has not answered yet. It may be off; ask again later.");
  const summary = answer.receipt && answer.receipt.action_summary;
  const choices = answer.receipt && answer.receipt.choices;
  if (answer.state === "applied" && choices && !summary) return showChoices(item, action, choices);
  if (answer.state === "refused" && REWORK.has(action)) markRework(item, false);
  if (answer.state === "refused" && Queued.notReady(item, action, answer)) return;
  if (answer.state === "refused" && !(answer.reason_code === "summary_changed" && summary)) {
    return fail(`Not possible: ${refusalText(answer)}`);
  }
  if (answer.step === "confirm" && answer.state === "applied") {
    const ids = answer.receipt.job_ids || [];
    const where = summary && summary.queue_position === "next" ? "It runs next." : "It joins the queue.";
    return sheet(
      el("h2", { text: `${label}: queued` }),
      el("p", { text: `${ids.length} job${ids.length === 1 ? "" : "s"} admitted on the PC. ${where}` }),
      el("p", {
        class: "muted",
        text: REWORK.has(action)
          ? "This image counts as reviewed. When the result arrives, compare the two and keep one."
          : "The result appears in the inbox once it is published.",
      }),
      el("div", { class: "sheet-actions" }, [
        el("button", { type: "button", class: "primary", text: "Close", onclick: () => closeAfterRework(item) }),
      ]),
    );
  }
  const node = sheet(
    answer.state === "refused" ? el("p", { class: "error", text: "The PC's summary changed. Check it again." }) : null,
    ...summaryView(summary),
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", text: "Cancel", onclick: closeSheet }),
      choices ? el("button", { type: "button", text: "Change", onclick: () => showChoices(item, action, choices) }) : null,
      el("button", {
        type: "button",
        class: "primary",
        text: "Queue",
        onclick: async (event) => {
          event.currentTarget.disabled = true;
          const alive = () => document.getElementById("sheet") === node;
          // This sheet replaced the one the request started on, so a refusal is shown while this one is open.
          const failHere = (text) => alive() && sheet(el("h2", { text: label }), el("p", { class: "error", text }), cancel());
          try {
            const sent = await sendAction({
              library_id: item.library_id,
              sha256: item.sha256,
              action,
              params: { step: "confirm", prepared_record: recordId, summary_revision: summary.revision },
              idempotency_key: idempotencyKey(),
            });
            if (REWORK.has(action)) markRework(item, true);
            node.querySelector(".sheet-actions").replaceChildren(
              el("p", { class: "muted", text: "Waiting for the PC…" }),
              el("button", { type: "button", text: "Close", onclick: () => closeAfterRework(item) }),
            );
            Queued.watch(node, item, action, sent.record_id, "confirm");
            const result = await waitFor(sent.record_id, alive);
            if (result) showAnswer(item, action, sent.record_id, result, cancel, failHere);
          } catch (error) {
            failHere(`Not sent: ${error.code || "no connection"}.`);
          }
        },
      }),
    ]),
  );
  return node;
}
