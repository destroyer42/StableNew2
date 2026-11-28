// RG-170: the answers given on this phone, kept until the gateway has them.

import { api } from "../../core/api.js";
import { toast } from "../../core/dom.js";

const UNSENT_KEY = "rg.rating.unsent";
let sending = null;

// One entry per (task, item, clip): the latest value wins, so resending is harmless.
let memory = {};

export function unsent() {
  try {
    const value = JSON.parse(localStorage.getItem(UNSENT_KEY) || "{}");
    if (value && typeof value === "object") memory = value;
  } catch {
    // private browsing: the map then lives only as long as this page
  }
  return memory;
}

export function keep(map) {
  memory = map;
  try {
    localStorage.setItem(UNSENT_KEY, JSON.stringify(map));
  } catch {
    // as above
  }
}

export const unitKey = (taskId, itemId, clipId) => `${taskId}|${itemId}|${clipId}`;
export const waitingFor = (taskId) => Object.keys(unsent()).filter((k) => k.startsWith(`${taskId}|`));

export function flush() {
  if (!sending) sending = sendAll().finally(() => (sending = null));
  return sending;
}

async function sendAll() {
  for (const [name, body] of Object.entries(unsent())) {
    const taskId = name.split("|")[0];
    try {
      await api(`/api/rating/tasks/${encodeURIComponent(taskId)}/answers`, body);
    } catch (error) {
      if (![404, 409, 422].includes(error.status)) return; // offline or signed out: try again later
      toast(error.status === 409 ? "Already submitted; that change was not saved" : "That answer was not saved");
    }
    const latest = unsent();
    if (JSON.stringify(latest[name]) === JSON.stringify(body)) {
      delete latest[name];
      keep(latest);
    }
  }
}
