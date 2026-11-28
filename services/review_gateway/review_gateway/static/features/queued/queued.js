// RG-160: phone actions made while the PC is away. A request is saved in the same list as unsent decisions, so it
// also survives a dropped connection, and the gateway keeps it until the PC can take it. Everything from the server is
// put on screen as text.
//
// This module is what the feature knows: the choice catalog, whether the PC is there, the gateway's last answer and
// the marks on items. request.js makes a request wait; waiting.js lists what waits.

import { api } from "../../core/api.js";
import { REWORK } from "../../core/catalog.js";
import { el } from "../../core/dom.js";
import { QUEUE_KEY, readList } from "../../core/outbox.js";
import { canQueue, loadScopes } from "../../core/session.js";
import { STATUS_STALE_MS } from "../../core/status.js";
import { allItems, currentTriage, key, needsReview } from "../../core/store.js";
import { since } from "../../core/text.js";

const CATALOG_KEY = "rg.catalog";
const SEEN_KEY = "rg.pcSeen";
const DISMISSED_KEY = "rg.dismissed";

const kept = new Map(); // used when storage is unusable
let latest = null; // the last /api/requests reply
let offline = false; // this phone could not reach the gateway

function recall(name, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(name) || "null");
    if (value !== null) return value;
  } catch {
    // private browsing: only what this page remembers
  }
  return kept.has(name) ? kept.get(name) : fallback;
}

function keep(name, value) {
  kept.set(name, value);
  try {
    localStorage.setItem(name, JSON.stringify(value));
  } catch {
    // the page's memory has it
  }
}

const catalog = () => recall(CATALOG_KEY, null);
const usable = () => canQueue() && Boolean(catalog());
const unsent = () => readList(QUEUE_KEY).filter((entry) => entry.action);

// --- is the PC there? -------------------------------------------------------------------------------------------

// The age of the PC's last request, by the gateway's clock plus the time since the phone read it.
function pcAge() {
  const seen = recall(SEEN_KEY, null);
  if (!seen || !seen.pc_seen_at) return null;
  return Date.parse(seen.now) - Date.parse(seen.pc_seen_at) + (Date.now() - seen.read_at);
}

function away() {
  if (offline) return true;
  const age = pcAge();
  return age === null || age > STATUS_STALE_MS;
}

function presence() {
  if (offline) return "The gateway is not reachable from this phone";
  const age = pcAge();
  if (age === null) return "The PC has not been seen";
  return age > STATUS_STALE_MS ? `PC last seen ${since(age)} ago` : "The PC is there";
}

async function sync() {
  await loadScopes();
  if (!canQueue()) return badge();
  try {
    const data = await api("/api/requests");
    latest = data;
    offline = false;
    keep(SEEN_KEY, { pc_seen_at: data.pc_seen_at, now: data.now, read_at: Date.now() });
    const held = recall(CATALOG_KEY, null);
    if (data.catalog_at && (!held || held.received_at !== data.catalog_at)) {
      const reply = await api("/api/catalog");
      if (reply.catalog) keep(CATALOG_KEY, { ...reply.catalog, received_at: reply.received_at });
    }
  } catch (error) {
    if (!error.status) offline = true; // anything the gateway answered (an older one: 404) is not "offline"
  }
  badge();
}

// What request.js and waiting.js read or change; they cannot assign this module's bindings.
const lastReply = () => latest;
function lostGateway() {
  offline = true;
}

const dismissed = () => new Set(recall(DISMISSED_KEY, []));

function dismiss(recordId) {
  keep(DISMISSED_KEY, [...recall(DISMISSED_KEY, []), recordId].slice(-500));
}

// --- the header and the marks -----------------------------------------------------------------------------------

function answered() {
  const gone = dismissed();
  return (latest ? latest.requests : []).filter((e) => e.state !== "pending" && !gone.has(e.record_id));
}

function badge() {
  const button = document.getElementById("waiting");
  if (!button) return;
  const pending = (latest ? latest.requests.filter((e) => e.state === "pending").length : 0) + unsent().length;
  const replies = answered().length;
  button.textContent = pending ? `${pending} waiting for PC` : `${replies} from PC`;
  button.hidden = !pending && !replies;
}

const waitingOn = (item) => Boolean(item.waiting && item.waiting.length);

function mark(item) {
  return waitingOn(item) && item.state !== "rework"
    ? el("span", { class: "badge waiting", text: "⌛", title: "A request is waiting for the PC" })
    : null;
}

const suffix = (item) => (waitingOn(item) ? " · request waiting for PC" : "");

// The inbox line for a phone that is not sent the PC's queue.
function line(status) {
  if (!status || status.pc || !status.pc_seen_at) return null;
  const age = Date.parse(status.now) - Date.parse(status.pc_seen_at);
  return age > STATUS_STALE_MS ? el("p", { class: "muted", text: `PC last seen ${since(age)} ago.` }) : null;
}

// Every copy of an item in these lists, including the one a rework result is compared with: "Keep rework" deletes
// that copy, so it must know what waits for it.
const copiesOf = (items, entry) =>
  items.flatMap((item) => [item, item.compare]).filter((copy) => copy && key(copy) === key(entry));

const onScreen = () => [...allItems(), currentTriage() ? currentTriage().list : []].flat();

function noteWaiting(copy, action) {
  copy.waiting = [...(copy.waiting || []).filter((other) => other !== action), action];
}

// Requests still on this phone, shown on the items they are about.
function overlay(items) {
  for (const entry of unsent()) {
    for (const copy of copiesOf(items, entry)) noteWaiting(copy, entry.action);
    for (const item of items.filter((i) => key(i) === key(entry))) {
      if (REWORK.has(entry.action) && needsReview(item)) item.state = "rework";
    }
  }
  return items;
}

export {
  catalog,
  usable,
  unsent,
  away,
  presence,
  sync,
  lastReply,
  lostGateway,
  dismissed,
  dismiss,
  badge,
  waitingOn,
  mark,
  suffix,
  line,
  copiesOf,
  onScreen,
  noteWaiting,
  overlay,
};
