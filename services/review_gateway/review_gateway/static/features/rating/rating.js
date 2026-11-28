// StableNew phone review: the "To rate" tab (RG-170). Everything from the server is put on screen as text, never as
// markup.

import { api } from "../../core/api.js";
import { el, show } from "../../core/dom.js";
import { flush } from "./answers.js";
import { REFUSALS, closeTask, showTask } from "./task.js";

const KINDS = { pairs: "A or B", scores: "Scores", ranking: "Ranking", choice: "Question" };
const STATES = {
  open: "to rate",
  partly: "partly done",
  refused: "not accepted",
  submitted: "waiting for the PC",
  done: "done",
};

// --- the entry on the home screen -------------------------------------------------------------------------------------

// The navigation hook: a full-width "To rate" button with the open count as its badge, for the home screen. On a
// gateway without rating tasks it hides itself and calls ``unavailable``.
export function entry(unavailable = () => {}) {
  const count = el("span", { class: "rt-count", hidden: "" });
  const open = el("button", { type: "button", class: "wide", onclick: () => (location.hash = "#/rate") }, [
    document.createTextNode("To rate"),
    count,
  ]);
  api("/api/rating/tasks").then(
    ({ waiting }) => {
      count.textContent = String(waiting);
      count.hidden = waiting === 0;
    },
    (error) => {
      if (error.status !== 404) return;
      open.hidden = true;
      unavailable();
    },
  );
  return open;
}

// --- the list -------------------------------------------------------------------------------------------------

const groups = [
  ["To rate", ["refused", "partly", "open"]],
  ["Waiting for the PC", ["submitted"]],
  ["Done", ["done"]],
];

function card(task) {
  const progress =
    task.state === "open"
      ? `${task.total} to answer`
      : task.state === "partly" || task.state === "refused"
        ? `${task.answered} of ${task.total}`
        : `${task.total} item${task.total === 1 ? "" : "s"}`;
  const open = () => (location.hash = `#/rate/${encodeURIComponent(task.task_id)}`);
  return el("section", { class: "run", tabindex: "0", onclick: open }, [
    el("h2", { text: task.title }),
    el("div", { class: "counts" }, [
      el("span", { class: "chip", text: KINDS[task.kind] || task.kind }),
      el("span", {
        class: `chip ${task.state === "refused" ? "refused" : task.state === "open" ? "todo" : ""}`,
        // Every answer given but not sent yet is the one thing left to do.
        text: task.state === "partly" && task.answered === task.total ? "ready to submit" : STATES[task.state] || task.state,
      }),
      el("span", { class: "chip", text: progress }),
    ]),
    task.state === "refused" ? el("p", { class: "error", text: REFUSALS[task.reason_code] || "not accepted" }) : null,
    task.note ? el("p", { class: "muted", text: task.note }) : null,
  ]);
}

async function showList(view) {
  await flush();
  const { tasks } = await api("/api/rating/tasks");
  if (!view.alive()) return;
  const nodes = [];
  for (const [heading, states] of groups) {
    const found = tasks.filter((task) => states.includes(task.state));
    if (!found.length) continue;
    nodes.push(el("h2", { class: "section-title", text: heading }), ...found.map(card));
  }
  if (!nodes.length) nodes.push(el("p", { class: "muted", text: "Nothing to rate. New sets appear after the PC syncs." }));
  show("To rate", true, ...nodes);
}

// --- the route --------------------------------------------------------------------------------------------------

export async function route(taskId, wanted, view) {
  if (!taskId) {
    closeTask();
    await showList(view);
  } else {
    await showTask(decodeURIComponent(taskId), wanted, view);
  }
}
