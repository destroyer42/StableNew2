// RG-160: requests that wait for the PC, and everywhere the page shows them.

import { el } from "../../core/dom.js";
import { line, mark, overlay, suffix, sync, waitingOn } from "./queued.js";
import { notReady, offer, sent, unreachable, watch } from "./request.js";
import { confirmDelete, show } from "./waiting.js";

// The header's "N waiting for PC" button; its count and visibility are kept by queued.js.
const headerButton = () =>
  el("button", { id: "waiting", type: "button", hidden: "", onclick: () => (location.hash = "#/requests") });

function deleteWarning({ items }) {
  const waiting = items.filter(waitingOn).length;
  return waiting ? { text: `${waiting} have a request waiting. Deleting cancels it.`, confirm: confirmDelete } : null;
}

// With the PC away, not ready or unreachable, the request is made to wait instead.
function takeAction({ why, item, action, extra, answer }) {
  if (why === "ask") return offer(item, action, extra);
  if (why === "not-ready") return notReady(item, action, answer);
  return unreachable(item, action);
}

export default {
  id: "queued",
  order: 60,
  routes: [
    {
      pattern: "#/requests",
      render: (params, view) => show(view),
      // Not redrawn under an open sheet.
      refresh: async (params, view) => {
        if (!document.getElementById("sheet")) await show(view);
      },
    },
  ],
  start({ bus, slots }) {
    slots.contribute("header.badges", headerButton);
    slots.contribute("home.prepare", () => sync());
    slots.contribute("home.top", ({ status }) => line(status));
    slots.contribute("tile.marks", ({ item }) => mark(item));
    slots.contribute("item.status", ({ item }) => suffix(item));
    slots.contribute("items.overlay", ({ items }) => overlay(items));
    slots.contribute("delete.warn", deleteWarning);
    slots.contribute("action.open", takeAction);
    bus.on("action:asked", ({ node, item, action, recordId, step }) => watch(node, item, action, recordId, step));
    bus.on("outbox:sent", sent);
    bus.on("app:started", sync);
    bus.on("app:refresh", sync);
  },
};
