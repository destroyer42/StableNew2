// What the page holds about items: the runs read from the gateway, the filter, the triage in progress.

import { api } from "./api.js";
import { QUEUE_KEY, REJECTED_KEY, readList } from "./outbox.js";
import * as Queued from "../features/queued/queued.js";

const runItems = new Map(); // run_id -> items
let filter = "todo";
let triage = null; // { runId, list, index, tags, lockedUntil }

// Other modules read and change the state above only through these.
export const itemsOf = (runId) => runItems.get(runId);
export const allItems = () => [...runItems.values()];
export const currentFilter = () => filter;
export const setFilter = (value) => {
  filter = value;
};
export const currentTriage = () => triage;
export const setTriage = (value) => {
  triage = value;
};

export const key = (item) => `${item.library_id}/${item.sha256}`;

// A group is a named batch ("batch:<id>", N5) or an output run folder; batch names come from the server.
const groupNames = new Map();
export const groupName = (id) => groupNames.get(id);
export const setGroupName = (id, name) => groupNames.set(id, name);

export function findItem(wanted) {
  const found = [];
  for (const items of runItems.values()) found.push(...items.filter((i) => key(i) === wanted));
  if (triage) found.push(...triage.list.filter((i) => key(i) === wanted));
  return found;
}

function overlayUnsent(items) {
  const decisionOf = (e) => ({ verdict: e.verdict, favorite: e.favorite, tags: e.tags });
  for (const entry of readList(REJECTED_KEY).filter((e) => !e.action)) {
    for (const item of items.filter((i) => key(i) === key(entry) && i.state === "undecided")) {
      item.decision = decisionOf(entry);
      item.state = "rejected";
      item.reason_code = entry.reason;
    }
  }
  for (const entry of readList(QUEUE_KEY).filter((e) => !e.action)) {
    for (const item of items.filter((i) => key(i) === key(entry))) {
      item.decision = decisionOf(entry);
      item.state = "unsent";
      item.reason_code = null;
    }
  }
  return Queued.overlay(items);
}

export async function loadRun(runId) {
  const data = await api(`/api/runs/${encodeURIComponent(runId)}`);
  if (data.name) groupNames.set(runId, data.name);
  const items = overlayUnsent(data.items);
  runItems.set(runId, items);
  return items;
}

export const needsReview = (item) => ["undecided", "refused", "rejected"].includes(item.state);
