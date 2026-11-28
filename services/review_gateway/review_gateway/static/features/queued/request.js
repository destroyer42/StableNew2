// RG-160: making a request wait for the PC: the sheet, the saved entry, and what happens when it is sent.

import { api, idempotencyKey } from "../../core/api.js";
import { bus } from "../../core/bus.js";
import { PICKERS, REWORK, WORDS, actionLabel, warningBlock } from "../../core/catalog.js";
import { closeSheet, el, sheet, toast } from "../../core/dom.js";
import { QUEUE_KEY, changeList, flush } from "../../core/outbox.js";
import { route } from "../../core/router.js";
import { closeAfterRework, findItem, key, markRework } from "../../core/store.js";
import {
  away,
  badge,
  catalog,
  copiesOf,
  lostGateway,
  noteWaiting,
  onScreen,
  presence,
  sync,
  unsent,
  usable,
} from "./queued.js";

// A PC that is there answers a summary within seconds; after this long the phone offers not to wait for it.
const OFFER_AFTER_MS = 10000;
const NOT_READY = new Set(["adetailer_unavailable", "model_unavailable"]);
// V1-6: never left waiting for an away PC; the PC refuses a `queue` step for these.
const NOT_DEFERRABLE = new Set(["continue_clip"]);
const AWAY_SAVE = "The PC checks this when it is back and queues it with any warnings.";

let asked = {}; // what the open online request was made with

// --- making a request -------------------------------------------------------------------------------------------

function paramsFor(action, extra) {
  return {
    step: "queue",
    ...(extra.choice ? { choice: extra.choice } : {}),
    ...(extra.text ? { text: extra.text } : {}),
    ...(action === "more_like_this" ? { count: 4 } : {}),
  };
}

const alreadyWaiting = (item, action) =>
  (item.waiting || []).includes(action) || unsent().some((e) => e.action === action && key(e) === key(item));

function add(item, action, extra) {
  const entry = {
    action,
    library_id: item.library_id,
    sha256: item.sha256,
    params: paramsFor(action, extra),
    idempotency_key: idempotencyKey(),
  };
  changeList(QUEUE_KEY, (list) => [...list, entry]);
  for (const copy of [item, ...copiesOf(onScreen(), item)]) noteWaiting(copy, action);
  if (REWORK.has(action)) markRework(item, true);
  flush();
  badge();
  toast("Saved; the PC runs it when it can");
  if (REWORK.has(action)) closeAfterRework(item); // review moves on, as it does for a rework queued online
  else {
    closeSheet();
    bus.emit("items:changed");
  }
  redraw();
}

// The waiting list, redrawn unless a sheet is open over it.
function redraw() {
  if (location.hash === "#/requests" && !document.getElementById("sheet")) route();
}

// The gateway answered (or refused) a saved request.
async function sent(entry, state) {
  if (state === "rejected") {
    for (const copy of copiesOf(onScreen(), entry)) {
      copy.waiting = (copy.waiting || []).filter((action) => action !== entry.action);
    }
    for (const copy of findItem(key(entry))) {
      if (REWORK.has(entry.action)) markRework(copy, false);
    }
  }
  await sync();
  redraw();
}

function sheetFor(item, action, extra = {}, note = "") {
  const known = catalog();
  const label = actionLabel(action);
  let choice = extra.choice || "";
  const picker = Boolean(PICKERS[action]);
  const words = WORDS[action];
  const input = words
    ? el("input", { maxlength: "200", placeholder: words.placeholder, "aria-label": label, autocomplete: "off" })
    : null;
  if (input) input.value = extra.text || "";
  const error = el("p", { class: "error", role: "alert" });
  const warnings = el("div", {});
  const choices = !picker ? [] : action === "another_model" ? known.models : known.ratios;
  if (!choices.some((entry) => entry.id === choice)) choice = "";
  const queue = el("button", { type: "button", class: "primary", text: "Queue when the PC is back" });
  const buttons = choices.map((entry) => {
    const warned = entry.warnings && entry.warnings.length;
    const button = el("button", { type: "button", text: warned ? `${entry.label} ⚠` : entry.label });
    button.addEventListener("click", () => {
      choice = entry.id;
      select();
    });
    return [button, entry];
  });
  function select() {
    for (const [button, entry] of buttons) button.setAttribute("aria-pressed", String(entry.id === choice));
    const entry = choices.find((candidate) => candidate.id === choice);
    const found = entry && entry.warnings ? entry.warnings.map((index) => known.warnings[index]).filter(Boolean) : [];
    warnings.replaceChildren(...found.map(warningBlock));
    queue.disabled = picker && !choice;
  }
  queue.addEventListener("click", () => {
    // One line of plain text: the PC refuses control characters, so they never leave the phone.
    const text = input ? input.value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, 200) : "";
    if (words && words.required && !text) {
      error.textContent = "Type a few words first.";
      return;
    }
    queue.disabled = true;
    add(item, action, { choice, text });
  });
  const asOf = known.models_as_of
    ? ` · list as of ${new Date(known.models_as_of).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}`
    : "";
  const video =
    action !== "make_video"
      ? null
      : known.video.available
        ? el("p", { class: "muted", text: known.video.label || "Make Video" })
        : warningBlock({ title: "The PC had no approved Make Video workflow.", why: "It checks again when it takes the request." });
  sheet(
    el("h2", { text: label }),
    el("p", { class: "muted", text: `${presence()}${picker ? asOf : ""}` }),
    note ? el("p", { text: note }) : null,
    picker ? el("p", { class: "muted", text: PICKERS[action] }) : null,
    words ? el("p", { class: "muted", text: words.hint }) : null,
    action === "more_like_this" ? el("p", { class: "muted", text: "4 new images, each with a new seed." }) : null,
    picker && !choices.length ? el("p", { text: "The PC has not listed any checkpoints yet." }) : null,
    picker ? el("div", { class: "choices", role: "group", "aria-label": "Options" }, buttons.map(([button]) => button)) : null,
    input,
    video,
    warnings,
    alreadyWaiting(item, action) ? warningBlock({ title: "Already waiting. Queue another?" }) : null,
    error,
    el("p", { class: "muted", text: AWAY_SAVE }),
    el("div", { class: "sheet-actions" }, [el("button", { type: "button", text: "Cancel", onclick: closeSheet }), queue]),
  );
  select();
}

// Called before asking the PC: with the PC away, the request is made to wait instead.
function offer(item, action, extra = {}) {
  asked = extra;
  if (NOT_DEFERRABLE.has(action) || !usable() || !away()) return false;
  sheetFor(item, action, extra);
  return true;
}

// A prepare refused only because the image backend is not connected can still wait for it.
function notReady(item, action, answer) {
  const detail = answer.receipt && answer.receipt.detail;
  if (NOT_DEFERRABLE.has(action) || answer.step !== "prepare" || !NOT_READY.has(detail) || !usable()) return false;
  sheetFor(item, action, asked, "Forge is not connected on the PC.");
  return true;
}

// The gateway could not be reached at all.
function unreachable(item, action) {
  if (NOT_DEFERRABLE.has(action) || !usable()) return false;
  lostGateway();
  sheetFor(item, action, asked, "The request is saved on this phone and sent when the gateway is reachable.");
  return true;
}

// After a while with no answer, offer to leave the request waiting instead. ``step`` is what the PC was asked.
function watch(node, item, action, recordId, step) {
  if (NOT_DEFERRABLE.has(action)) return;
  const extra = asked;
  setTimeout(() => {
    if (document.getElementById("sheet") !== node || !usable()) return;
    const holder = node.querySelector(".sheet-actions") || el("div", { class: "sheet-actions" });
    if (!holder.parentNode) node.querySelector(".sheet-body").append(holder);
    holder.append(
      el("button", {
        type: "button",
        class: "primary",
        text: "Queue when the PC is back",
        onclick: () => leave(item, action, extra, recordId, step),
      }),
    );
  }, OFFER_AFTER_MS);
}

async function leave(item, action, extra, recordId, step) {
  const say = (text) =>
    sheet(
      el("h2", { text: actionLabel(action) }),
      el("p", { text }),
      el("div", { class: "sheet-actions" }, [el("button", { type: "button", text: "Close", onclick: closeSheet })]),
    );
  say("One moment…"); // the online wait ends with its sheet
  let state = "";
  try {
    state = (await api(`/api/actions/${recordId}/cancel`, {})).state;
  } catch {
    // a prepare admits nothing, so one left behind is harmless; a confirm is not converted without knowing
    if (step === "confirm") return say("Could not reach the gateway, so the request was left as it is.");
  }
  if (step !== "confirm") return sheetFor(item, action, extra);
  if (state === "cancelled") return add(item, action, extra);
  if (state === "refused") {
    markRework(item, false);
    return say("The PC has already refused this request. Ask again to see why.");
  }
  say("The PC already has this request. Its result appears when it runs.");
}

export { sheetFor, sent, offer, notReady, unreachable, watch };
