// Decisions and requests the gateway has not accepted yet: saving, undo, sending and the "Not saved" screen.

import { ApiError, api, idempotencyKey } from "./api.js";
import { bus } from "./bus.js";
import { actionLabel } from "./catalog.js";
import { el, show, toast } from "./dom.js";
import { mediaUrl } from "./media.js";
import { currentTriage, findItem, key } from "./store.js";

// PHONE-FAST: the last decision stays on the phone this long, so it can be undone.
const UNDO_MS = 8000;

export const QUEUE_KEY = "rg.unsent";
export const REJECTED_KEY = "rg.rejected";
const ANSWERS = new Set(["pending", "applied", "refused"]);
export const NOT_SAVED = {
  unknown_item: "the gateway does not have this item",
  not_granted: "this phone is not allowed to review",
  idempotency_conflict: "it clashed with an earlier request",
  not_an_image: "only images can be fixed",
  too_many_pending: "too many requests from this phone are waiting",
};

// --- decisions not yet accepted by the gateway --------------------------------------------------------------------
// Kept on the phone and resent with the same idempotency key, so a dropped connection loses nothing. Storage is
// shared by every tab: it is re-read for each change and never overwritten with one tab's older list. A decision
// the gateway will not take is moved to a "not saved" list that stays until the owner deals with it.

const memory = new Map(); // what was last read or written, used if storage becomes unusable
let storageBroken = false;
let sending = false;
let retryTimer = 0;
let retryDelay = 2000;

export function readList(name) {
  if (!storageBroken) {
    try {
      const value = JSON.parse(localStorage.getItem(name) || "[]");
      if (Array.isArray(value)) memory.set(name, value);
    } catch {
      storageBroken = true; // private browsing: the lists then live only as long as this page
    }
  }
  return memory.get(name) || [];
}

export function changeList(name, change) {
  const next = change(readList(name));
  memory.set(name, next);
  try {
    localStorage.setItem(name, JSON.stringify(next));
  } catch {
    storageBroken = true;
  }
  showBadges();
}

export const without = (idempotency) => (list) => list.filter((e) => e.idempotency_key !== idempotency);

export function showBadges() {
  const waiting = readList(QUEUE_KEY).length;
  const badge = document.getElementById("unsent");
  badge.textContent = `${waiting} unsent`;
  badge.hidden = waiting === 0;
  const lost = readList(REJECTED_KEY).length;
  const button = document.getElementById("rejected");
  button.textContent = `${lost} not saved`;
  button.hidden = lost === 0;
}

export function queueDecision(item, verdict, favorite, tags, heldUntil = 0) {
  const entry = {
    library_id: item.library_id,
    sha256: item.sha256,
    verdict,
    favorite,
    tags,
    idempotency_key: idempotencyKey(),
    ...(heldUntil ? { held_until: heldUntil } : {}),
  };
  changeList(REJECTED_KEY, (list) => list.filter((e) => e.action || key(e) !== key(item)));
  changeList(QUEUE_KEY, (list) => [...list, entry]);
  item.decision = { verdict, favorite, tags };
  item.state = "unsent";
  item.reason_code = null;
  flush();
  return entry.idempotency_key;
}

// --- undo (PHONE-FAST) --------------------------------------------------------------------------------------------
// The gateway has no "undecide", so the last decision (one item, or a compare's pair) is held on the phone for a few
// seconds. The next decision, leaving the page or the time running out sends it.

let undoable = null; // { keys, before, at, timer }

export function decideUndoably(choices) {
  releaseHeld();
  const until = Date.now() + UNDO_MS;
  const keys = [];
  const before = [];
  for (const [item, verdict, favorite, tags] of choices) {
    const copies = [item, ...findItem(key(item))];
    before.push(...copies.map((copy) => [copy, copy.decision, copy.state, copy.reason_code]));
    keys.push(queueDecision(item, verdict, favorite, tags, until));
    for (const copy of copies) Object.assign(copy, { decision: item.decision, state: item.state, reason_code: null });
  }
  const triage = currentTriage();
  const at = triage ? { runId: triage.runId, libraryId: triage.list[triage.index].library_id } : null;
  undoable = { keys, before, at, timer: setTimeout(releaseHeld, UNDO_MS) };
  showUndo(true);
}

export function releaseHeld() {
  if (undoable) clearTimeout(undoable.timer);
  undoable = null;
  showUndo(false);
  changeList(QUEUE_KEY, (list) => list.map(({ held_until, ...entry }) => entry));
  flush();
}

function undo() {
  if (!undoable) return;
  const triage = currentTriage();
  const { keys, before, at, timer } = undoable;
  clearTimeout(timer);
  undoable = null;
  showUndo(false);
  changeList(QUEUE_KEY, (list) => list.filter((entry) => !keys.includes(entry.idempotency_key)));
  for (const [copy, decision, state, reason] of before) {
    Object.assign(copy, { decision, state, reason_code: reason });
  }
  toast("Undone");
  flush();
  const index = triage && at ? triage.list.findIndex((item) => item.library_id === at.libraryId) : -1;
  if (index >= 0 && triage.runId === at.runId) {
    triage.index = index;
    bus.emit("item:restored");
  } else if (at) {
    location.hash = `#/triage/${encodeURIComponent(at.runId)}/${at.libraryId}`;
  }
}

function showUndo(visible) {
  let button = document.getElementById("undo");
  if (!button) {
    if (!visible) return;
    button = el("button", { type: "button", id: "undo", text: "Undo", onclick: undo });
    document.body.append(button);
  }
  button.hidden = !visible;
}

async function send(entry) {
  const { reason, held_until, ...body } = entry;
  const { state } = await api(entry.action ? "/api/actions" : "/api/decisions", body);
  const known = ANSWERS.has(state) || (entry.action && state === "cancelled"); // RG-160
  if (!known) throw new Error("unreadable reply"); // keep it and try again
  return state;
}

export async function flush() {
  if (sending) return;
  sending = true;
  clearTimeout(retryTimer);
  try {
    let entry;
    while ((entry = readList(QUEUE_KEY)[0])) {
      const wait = (entry.held_until || 0) - Date.now();
      if (wait > 0) {
        retryTimer = setTimeout(flush, wait); // still undoable; what follows it waits too, to keep the order
        return;
      }
      let state;
      let reason = null;
      try {
        state = await send(entry);
      } catch (error) {
        if (error.status === 401) {
          bus.emit("session:lost");
          return;
        }
        // RG-160: "too many waiting" lasts until the PC answers them, so it is set aside rather than holding up the list.
        const busy = error.status === 429 && error.code !== "too_many_pending";
        if (!(error instanceof ApiError) || error.status >= 500 || busy) {
          retryTimer = setTimeout(flush, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 30000);
          return;
        }
        state = "rejected";
        reason = error.code;
        const lost = { ...entry, reason };
        changeList(REJECTED_KEY, (list) => [...without(lost.idempotency_key)(list), lost]);
        toast(entry.action ? "A request was not saved" : "A decision was not saved");
      }
      const sent = entry.idempotency_key;
      changeList(QUEUE_KEY, without(sent));
      retryDelay = 2000;
      const target = key(entry);
      if (entry.action) {
        bus.emit("outbox:sent", entry, state); // RG-160: it says nothing about the item's decision
      } else if (!readList(QUEUE_KEY).some((e) => !e.action && key(e) === target)) {
        for (const item of findItem(target)) {
          item.state = state;
          item.reason_code = reason;
        }
        bus.emit("items:changed");
      }
    }
  } finally {
    sending = false;
  }
}

export function showRejected() {
  const retry = (entry) => {
    const { reason, ...again } = entry;
    changeList(REJECTED_KEY, without(entry.idempotency_key));
    changeList(QUEUE_KEY, (list) => [...list, again]);
    flush();
    showRejected();
  };
  const dismiss = (entry) => {
    changeList(REJECTED_KEY, without(entry.idempotency_key));
    showRejected();
  };
  const rows = readList(REJECTED_KEY).map((entry) => {
    const choice = entry.action
      ? actionLabel(entry.action)
      : entry.favorite ? "Favorite" : entry.verdict === "keep" ? "Keep" : "Delete";
    return el("section", { class: "run" }, [
      el("h2", { text: `${choice} was not saved` }),
      el("p", { class: "muted", text: NOT_SAVED[entry.reason] || "the gateway did not accept it" }),
      el("div", { class: "covers" }, [el("img", { src: mediaUrl(entry, "thumb"), alt: "" })]),
      el("div", { class: "tools" }, [
        el("button", { type: "button", class: "primary", text: "Try again", onclick: () => retry(entry) }),
        el("button", { type: "button", text: "Dismiss", onclick: () => dismiss(entry) }),
      ]),
    ]);
  });
  show("Not saved", true, ...(rows.length ? rows : [el("p", { class: "muted", text: "Nothing is waiting." })]));
}
