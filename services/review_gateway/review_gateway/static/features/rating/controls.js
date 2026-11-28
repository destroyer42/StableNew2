// RG-170: the answer controls of one item or clip. ``save`` records the answer it is given.

import { el } from "../../core/dom.js";
import { unitKey } from "./answers.js";

const NOTE_DELAY_MS = 800;
const noteTimers = new Map();

function setValue(answer, criterion, value, save) {
  if (answer.values[criterion] === value) delete answer.values[criterion];
  else answer.values[criterion] = value;
  save(answer);
}

// A row of mutually exclusive buttons; tapping the chosen one again clears it.
function buttonRow(answer, criterion, options, className, save) {
  const row = el("div", { class: `rt-options ${className}` });
  const paint = () =>
    row.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", String(answer.values[criterion.criterion_id] === button.dataset.value));
    });
  row.append(
    ...options.map(({ value, label, recommended }) =>
      el(
        "button",
        {
          type: "button",
          "data-value": value,
          onclick: () => {
            setValue(answer, criterion.criterion_id, value, save);
            paint();
          },
        },
        [
          document.createTextNode(label),
          recommended ? el("span", { class: "rt-recommended", text: "recommended" }) : null,
        ],
      ),
    ),
  );
  paint();
  return row;
}

// Tap the clips best first; "=" ties are not offered one by one, only "all the same".
function rankRow(answer, criterion, item, save) {
  const row = el("div", { class: "rt-options rank" });
  let order = [];
  const saved = answer.values[criterion.criterion_id];
  if (saved && saved !== "tie") order = saved.split(/[>=]/);
  const paint = () => {
    row.querySelectorAll("button[data-clip]").forEach((button) => {
      const place = order.indexOf(button.dataset.clip);
      button.textContent = place < 0 ? button.dataset.label : `${place + 1}. ${button.dataset.label}`;
      button.setAttribute("aria-pressed", String(place >= 0));
    });
    row.querySelector("[data-tie]").setAttribute("aria-pressed", String(answer.values[criterion.criterion_id] === "tie"));
  };
  const store = (value) => {
    if (value) answer.values[criterion.criterion_id] = value;
    else delete answer.values[criterion.criterion_id];
    save(answer);
    paint();
  };
  row.append(
    ...item.clips.map((clip) =>
      el("button", {
        type: "button",
        "data-clip": clip.clip_id,
        "data-label": clip.label,
        onclick: () => {
          if (order.includes(clip.clip_id)) order = [];
          else order.push(clip.clip_id);
          if (order.length === item.clips.length - 1) {
            order.push(...item.clips.map((c) => c.clip_id).filter((id) => !order.includes(id)));
          }
          store(order.length === item.clips.length ? order.join(">") : "");
        },
      }),
    ),
    el("button", {
      type: "button",
      "data-tie": "1",
      text: "All the same",
      onclick: () => {
        order = [];
        store(answer.values[criterion.criterion_id] === "tie" ? "" : "tie");
      },
    }),
  );
  paint();
  return row;
}

function control(answer, criterion, item, save) {
  let row;
  if (criterion.type === "score") {
    row = buttonRow(answer, criterion, ["1", "2", "3", "4", "5"].map((v) => ({ value: v, label: v })), "score", save);
  } else if (criterion.type === "choice") {
    const options = item.clips.map((clip) => ({ value: clip.clip_id, label: clip.label }));
    options.splice(1, 0, { value: "tie", label: "Same" });
    row = buttonRow(answer, criterion, options, "choice", save);
  } else if (criterion.type === "rank") {
    row = rankRow(answer, criterion, item, save);
  } else {
    row = buttonRow(answer, criterion, criterion.options, "enum", save);
  }
  return el("div", { class: "rt-criterion" }, [el("p", { text: criterion.label }), row]);
}

function notesBox(answer, taskId, save) {
  const box = el("textarea", { class: "rt-notes", rows: "2", maxlength: "1000", placeholder: "Notes (optional)" });
  box.value = answer.notes || "";
  const name = unitKey(taskId, answer.item_id, answer.clip_id);
  const write = () => {
    clearTimeout(noteTimers.get(name));
    noteTimers.delete(name);
    if (answer.notes === box.value) return;
    answer.notes = box.value;
    save(answer);
  };
  box.addEventListener("input", () => {
    clearTimeout(noteTimers.get(name));
    noteTimers.set(name, setTimeout(write, NOTE_DELAY_MS));
  });
  box.addEventListener("change", write);
  return box;
}

export function answerControls(task, item, answer, save) {
  const main = task.criteria.filter((c) => c.required).map((c) => control(answer, c, item, save));
  const optional = task.criteria.filter((c) => !c.required).map((c) => control(answer, c, item, save));
  return el("div", { class: "rt-controls" }, [
    ...main,
    optional.length ? el("details", {}, [el("summary", { text: "Optional" }), ...optional]) : null,
    notesBox(answer, task.task_id, save),
  ]);
}
