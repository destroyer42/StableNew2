// RG-170: one rating task, its items and clips, Submit, and the reveal afterwards.

import { api, idempotencyKey } from "../../core/api.js";
import { el, show, toast } from "../../core/dom.js";
import { flush, keep, unitKey, unsent, waitingFor } from "./answers.js";
import { answerControls } from "./controls.js";

const LAYOUT_KEY = "rg.rating.layout"; // "side" or "stacked", once the owner has chosen

export const REFUSALS = {
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

export function closeTask() {
  current = null;
}

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

const controls = (item, clipId) => answerControls(current, item, answerFor(item.item_id, clipId), save);

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

export async function showTask(taskId, wanted, view) {
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
