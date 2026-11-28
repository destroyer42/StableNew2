// StableNew phone review: the "To rate" tab (RG-170). Everything from the server is put on screen as text, never as
// markup.

import { api, idempotencyKey } from "../../core/api.js";
import { el, show, toast } from "../../core/dom.js";

const UNSENT_KEY = "rg.rating.unsent";
const LAYOUT_KEY = "rg.rating.layout"; // "side" or "stacked", once the owner has chosen
const NOTE_DELAY_MS = 800;
const KINDS = { pairs: "A or B", scores: "Scores", ranking: "Ranking", choice: "Question" };
const STATES = {
  open: "to rate",
  partly: "partly done",
  refused: "not accepted",
  submitted: "waiting for the PC",
  done: "done",
};
const REFUSALS = {
  already_rated: "the PC already holds a different rating for this; nothing was written",
  clip_changed: "a clip on the PC is not the one you rated; nothing was written",
  unknown_task: "the PC no longer has this rating set",
  revoked_device: "this phone was revoked",
  not_granted: "this phone is not allowed to review",
  invalid_record: "the PC rejected the answers",
  write_failed: "the PC could not write the ratings file",
};
let current = null; // the task being rated
let index = 0;
let submitKey = null;
let sending = null;
const noteTimers = new Map();

// --- answers not yet on the gateway ---------------------------------------------------------------------------
// One entry per (task, item, clip): the latest value wins, so resending is harmless.
let memory = {};

function unsent() {
  try {
    const value = JSON.parse(localStorage.getItem(UNSENT_KEY) || "{}");
    if (value && typeof value === "object") memory = value;
  } catch {
    // private browsing: the map then lives only as long as this page
  }
  return memory;
}

function keep(map) {
  memory = map;
  try {
    localStorage.setItem(UNSENT_KEY, JSON.stringify(map));
  } catch {
    // as above
  }
}

const unitKey = (taskId, itemId, clipId) => `${taskId}|${itemId}|${clipId}`;
const waitingFor = (taskId) => Object.keys(unsent()).filter((k) => k.startsWith(`${taskId}|`));

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

// --- one task -------------------------------------------------------------------------------------------------

const editable = () => ["open", "partly", "refused"].includes(current.state);
const isScores = () => current.kind === "scores";

function answerFor(itemId, clipId) {
  let found = current.answers.find((a) => a.item_id === itemId && a.clip_id === clipId);
  if (!found) {
    found = { item_id: itemId, clip_id: clipId, values: {}, notes: "" };
    current.answers.push(found);
  }
  return found;
}

const clipsOf = (item) => (isScores() ? item.clips.map((clip) => clip.clip_id) : [""]);
const required = () => current.criteria.filter((c) => c.required).map((c) => c.criterion_id);

function complete(item) {
  return clipsOf(item).every((clipId) => {
    const { values } = answerFor(item.item_id, clipId);
    return required().every((criterion) => criterion in values);
  });
}

function save(answer) {
  const body = {
    item_id: answer.item_id,
    clip_id: answer.clip_id,
    values: { ...answer.values },
    notes: answer.notes,
  };
  keep({ ...unsent(), [unitKey(current.task_id, answer.item_id, answer.clip_id)]: body });
  updateFooter();
  flush();
}

function setValue(answer, criterion, value) {
  if (answer.values[criterion] === value) delete answer.values[criterion];
  else answer.values[criterion] = value;
  save(answer);
}

// A row of mutually exclusive buttons; tapping the chosen one again clears it.
function buttonRow(answer, criterion, options, className) {
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
            setValue(answer, criterion.criterion_id, value);
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
function rankRow(answer, criterion, item) {
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

function control(answer, criterion, item) {
  let row;
  if (criterion.type === "score") {
    row = buttonRow(answer, criterion, ["1", "2", "3", "4", "5"].map((v) => ({ value: v, label: v })), "score");
  } else if (criterion.type === "choice") {
    const options = item.clips.map((clip) => ({ value: clip.clip_id, label: clip.label }));
    options.splice(1, 0, { value: "tie", label: "Same" });
    row = buttonRow(answer, criterion, options, "choice");
  } else if (criterion.type === "rank") {
    row = rankRow(answer, criterion, item);
  } else {
    row = buttonRow(answer, criterion, criterion.options, "enum");
  }
  return el("div", { class: "rt-criterion" }, [el("p", { text: criterion.label }), row]);
}

function notesBox(answer) {
  const box = el("textarea", { class: "rt-notes", rows: "2", maxlength: "1000", placeholder: "Notes (optional)" });
  box.value = answer.notes || "";
  const name = unitKey(current.task_id, answer.item_id, answer.clip_id);
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

function controls(item, clipId) {
  const answer = answerFor(item.item_id, clipId);
  const main = current.criteria.filter((c) => c.required).map((c) => control(answer, c, item));
  const optional = current.criteria.filter((c) => !c.required).map((c) => control(answer, c, item));
  return el("div", { class: "rt-controls" }, [
    ...main,
    optional.length ? el("details", {}, [el("summary", { text: "Optional" }), ...optional]) : null,
    notesBox(answer),
  ]);
}

const ratingMedia = (media) => `/rating-media/${encodeURIComponent(current.task_id)}/${media.sha256}`;

function player(clip) {
  if (clip.media.content_type.startsWith("image/")) {
    return el("img", { src: ratingMedia(clip.media), alt: clip.label });
  }
  const video = el("video", { src: ratingMedia(clip.media), loop: "", playsinline: "", controls: "", preload: "metadata" });
  video.muted = true;
  return video;
}

const figure = (clip) => el("figure", {}, [el("figcaption", { text: clip.label }), player(clip)]);

function playAll(videos, fromStart) {
  for (const video of videos) {
    if (fromStart) video.currentTime = 0;
    video.play().catch(() => {});
  }
}

function chosenLayout() {
  try {
    return localStorage.getItem(LAYOUT_KEY);
  } catch {
    return null;
  }
}

// Two or three clips sit side by side when they are portrait (they then fit one screen), until the owner says otherwise.
function arrange(stage, button) {
  const paint = (side) => {
    stage.classList.toggle("side", side);
    button.textContent = side ? "Stacked" : "Side by side";
  };
  const saved = chosenLayout();
  paint(saved === "side");
  const first = stage.querySelector("video");
  if (!saved && first) {
    first.addEventListener("loadedmetadata", () => paint(first.videoHeight > first.videoWidth), { once: true });
  }
  button.addEventListener("click", () => {
    const side = !stage.classList.contains("side");
    paint(side);
    try {
      localStorage.setItem(LAYOUT_KEY, side ? "side" : "stacked");
    } catch {
      // private browsing: the choice lasts for this screen
    }
  });
}

function itemNodes(item) {
  const clips = item.clips || [];
  const nodes = [];
  if (item.title) nodes.push(el("h2", { class: "section-title", text: item.title }));
  if (item.context) {
    const text = el("p", { class: "rt-context", text: item.context });
    nodes.push(current.kind === "choice" ? text : el("details", {}, [el("summary", { text: "What was asked" }), text]));
  }
  if (item.reference) {
    nodes.push(
      el("details", { open: "" }, [
        el("summary", { text: "Source picture" }),
        el("img", { class: "rt-reference", src: ratingMedia(item.reference), alt: "Source picture" }),
      ]),
    );
  }
  const stage = el("div", { class: "rt-clips" });
  const layout = !isScores() && clips.length > 1 ? el("button", { type: "button" }) : null;
  if (clips.length > 1) {
    nodes.push(
      el("div", { class: "tools" }, [
        el("button", { type: "button", class: "grow", text: "Play all from the start", onclick: () => playAll(stage.querySelectorAll("video"), true) }),
        el("button", { type: "button", text: "Pause", onclick: () => stage.querySelectorAll("video").forEach((v) => v.pause()) }),
        layout,
      ]),
    );
  }
  if (isScores()) {
    stage.append(...clips.map((clip) => el("div", { class: "rt-scored" }, [figure(clip), controls(item, clip.clip_id)])));
    nodes.push(stage);
  } else {
    stage.append(...clips.map(figure));
    if (layout) arrange(stage, layout);
    if (clips.length) nodes.push(stage);
    nodes.push(controls(item, ""));
  }
  return nodes;
}

function updateFooter() {
  const button = document.getElementById("rt-submit");
  if (!button) return;
  const done = current.items.filter(complete).length;
  button.disabled = done < current.items.length;
  button.textContent =
    done < current.items.length ? `${done} of ${current.items.length} answered` : "Submit ratings";
}

function go(next) {
  location.hash = `#/rate/${encodeURIComponent(current.task_id)}/${next}`;
}

async function submit(button) {
  if (!window.confirm("Submit is final. The PC then records your answers. Submit now?")) return;
  button.disabled = true;
  try {
    document.querySelectorAll(".rt-notes").forEach((box) => box.dispatchEvent(new Event("change")));
    await flush();
    if (waitingFor(current.task_id).length) {
      toast("Not everything is saved yet. Check the connection and try again.");
      return;
    }
    submitKey = submitKey || idempotencyKey();
    await api(`/api/rating/tasks/${encodeURIComponent(current.task_id)}/submit`, { idempotency_key: submitKey });
    submitKey = null;
    location.hash = "#/rate";
    toast("Submitted. The PC records it when it next syncs.");
  } catch (error) {
    toast(error.code === "incomplete" ? "Something is still unanswered." : "Could not submit; try again.");
  } finally {
    button.disabled = false;
    updateFooter();
  }
}

function revealTable(table) {
  return el("div", { class: "rt-reveal" }, [
    el("h2", { class: "section-title", text: table.title }),
    el("div", { class: "rt-scroll" }, [
      el("table", {}, [
        el("tr", {}, table.columns.map((column) => el("th", { text: column }))),
        ...table.rows.map((row) => el("tr", {}, row.map((cell) => el("td", { text: cell })))),
      ]),
    ]),
  ]);
}

function showResult() {
  const message =
    current.state === "submitted"
      ? "Submitted. Waiting for the PC to record it."
      : current.note || "Done. The PC recorded your answers.";
  show(
    current.title,
    true,
    el("p", { text: message }),
    ...(current.reveal || []).map(revealTable),
    el("button", { type: "button", text: "Back to the list", onclick: () => (location.hash = "#/rate") }),
  );
}

function renderTask() {
  if (!editable()) return showResult();
  index = Math.min(Math.max(index, 0), current.items.length - 1);
  const item = current.items[index];
  const last = current.items.length - 1;
  const several = last > 0;
  const submitButton = el("button", { type: "button", id: "rt-submit", class: "primary", onclick: (event) => submit(event.currentTarget) });
  const nodes = [
    el("div", { class: "rt-head" }, [
      several ? el("span", { text: `${index + 1} of ${current.items.length}` }) : null,
      current.state === "refused"
        ? el("span", { class: "error", text: REFUSALS[current.reason_code] || "not accepted" })
        : null,
    ]),
    current.instructions
      ? el("details", {}, [el("summary", { text: "How to rate" }), el("p", { class: "rt-context", text: current.instructions })])
      : null,
    ...itemNodes(item),
    several
      ? el("div", { class: "rt-nav" }, [
          el("button", { type: "button", text: "Previous", ...(index === 0 ? { disabled: "" } : {}), onclick: () => go(index - 1) }),
          el("button", { type: "button", text: "Next", ...(index === last ? { disabled: "" } : {}), onclick: () => go(index + 1) }),
        ])
      : null,
    submitButton,
  ];
  show(current.title, true, ...nodes.filter(Boolean));
  updateFooter();
  window.scrollTo(0, 0);
}

async function showTask(taskId, wanted, view) {
  await flush();
  if (!current || current.task_id !== taskId || !editable()) {
    const task = await api(`/api/rating/tasks/${encodeURIComponent(taskId)}`);
    if (!view.alive()) return;
    current = task;
    submitKey = null;
    // Answers still waiting on this phone are newer than the gateway's.
    for (const name of waitingFor(taskId)) {
      const body = unsent()[name];
      Object.assign(answerFor(body.item_id, body.clip_id), body, { values: { ...body.values } });
    }
    const first = current.items.findIndex((item) => !complete(item));
    index = first < 0 ? 0 : first;
  }
  if (wanted !== undefined && wanted !== "") index = Number.parseInt(wanted, 10) || 0;
  renderTask();
}

export async function route(taskId, wanted, view) {
  if (!taskId) {
    current = null;
    await showList(view);
  } else {
    await showTask(decodeURIComponent(taskId), wanted, view);
  }
}
