// The action row, its words and pickers, the PC's summary and the receipt (RG-140).

import { api, idempotencyKey } from "../../core/api.js";
import { bus } from "../../core/bus.js";
import {
  ACTIONS,
  CLIP_ACTIONS,
  PICKERS,
  REWORK,
  WORDS,
  actionLabel,
  refusalText,
  warningBlock,
} from "../../core/catalog.js";
import { closeSheet, el, sheet } from "../../core/dom.js";
import { canQueue } from "../../core/session.js";
import { slots } from "../../core/slots.js";
import { closeAfterRework, markRework } from "../../core/store.js";

const ACTION_POLL_MS = 1000;

const ACTION_WAIT_MS = 10 * 60 * 1000;

// --- phone actions (RG-140) ---------------------------------------------------------------------------------------
// Two steps, both outbox requests: "prepare" asks the PC for a summary of exactly what it would queue; "Queue" sends
// "confirm" naming that summary. Nothing is queued until the PC admits it, and its receipt is shown.

// Asking for a fix says what is wrong with the image, so the matching reason tags are switched on (the triage does
// that, and resends a decision already made for it with them).
const FIX_TAGS = { fix_face: ["face"], fix_hands: ["hands"], fix_both: ["face", "hands"] };

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
          if (FIX_TAGS[action]) bus.emit("tags:wanted", item, FIX_TAGS[action]);
          if (slots.claim("action.open", { why: "ask", item, action })) return; // RG-160: the PC is away
          if (WORDS[action]) askWords(item, action);
          else openAction(item, action);
        },
      }),
    ),
  );
}

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
  if (slots.claim("action.open", { why: "ask", item, action, extra })) return;
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
    if (alive()) bus.emit("action:asked", { node, item, action, recordId, step: "prepare" });
    const answer = await waitFor(recordId, alive);
    if (answer) showAnswer(item, action, recordId, answer, cancel, fail);
  } catch (error) {
    if (!error.status && alive() && slots.claim("action.open", { why: "unreachable", item, action })) return;
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
  if (answer.state === "refused" && slots.claim("action.open", { why: "not-ready", item, action, answer })) return;
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
            bus.emit("action:asked", { node, item, action, recordId: sent.record_id, step: "confirm" });
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
