// The triage stream: one item at a time, swipes, reason tags and the three choices.

import { bus } from "../../core/bus.js";
import { el, show, toast } from "../../core/dom.js";
import { PREFETCH, mediaElement, prefetch } from "../../core/media.js";
import { NOT_SAVED, decideUndoably, queueDecision } from "../../core/outbox.js";
import { leaving } from "../../core/router.js";
import { loadScopes } from "../../core/session.js";
import { slots } from "../../core/slots.js";
import { currentFilter, currentTriage, key, loadRun, needsReview, setTriage } from "../../core/store.js";
import { REASONS, isStream, runName } from "../../core/text.js";
import { doubleTaps, openViewer } from "./viewer.js";

const TAGS = [
  ["face", "Face"],
  ["hands", "Hands"],
  ["anatomy", "Anatomy"],
  ["artifact", "Artifact"],
  ["prompt_miss", "Prompt miss"],
  ["needs_fix", "Needs fix"],
];

// --- triage -------------------------------------------------------------------------------------------------------

export async function showTriage(runId, libraryId, view) {
  await loadScopes();
  const items = await loadRun(runId);
  if (!view.alive()) return;
  const todo = items.filter(needsReview);
  const useTodo = currentFilter() === "todo" && todo.length && (!libraryId || todo.some((i) => i.library_id === libraryId));
  const list = useTodo ? todo : items;
  if (!list.length) {
    bus.emit("grid:wanted", runId);
    return;
  }
  const index = Math.max(0, list.findIndex((item) => item.library_id === libraryId));
  setTriage({ runId, list, index, tags: new Set(), lockedUntil: 0 });
  renderItem();
}

function statusText(item) {
  if (item.state === "rework") return "Sent for rework";
  if (!item.decision) {
    if (item.original_missing) return "Not decided · original not found";
    if (!item.compare) return "Not decided";
    return item.compare.desk ? "Reprocess result: which is better?" : "Rework result: which is better?";
  }
  const choice = item.decision.favorite ? "Favorite" : item.decision.verdict === "keep" ? "Keep" : "Delete";
  if (item.state === "unsent") return `${choice} · sending…`;
  if (item.state === "pending") return `${choice} · waiting for PC`;
  if (item.state === "refused") return `${choice} refused: ${REASONS[item.reason_code] || "no reason given"}`;
  if (item.state === "rejected") return `${choice} not saved: ${NOT_SAVED[item.reason_code] || "not accepted"}`;
  return `${choice} · applied`;
}

export function updateTriageStatus() {
  const node = document.getElementById("state");
  const triage = currentTriage();
  if (!triage || !node) return;
  const item = triage.list[triage.index];
  node.textContent = statusText(item) + slots.render("item.status", { item }).join("");
  node.className = item.state === "refused" || item.state === "rejected" ? "refused" : "";
}

function attachSwipe(stage, media, info, item) {
  const taps = doubleTaps();
  const hint = el("div", { class: "hint", hidden: "" });
  stage.append(hint);
  let start = null;
  let pointers = 0;
  const choose = (dx, dy) => {
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.3) return dx > 0 ? "keep" : "delete";
    if (dy < -90 && Math.abs(dy) > Math.abs(dx) * 1.3) return "favorite";
    return null;
  };
  const reset = () => {
    start = null;
    media.style.transform = "";
    hint.hidden = true;
  };
  stage.addEventListener("pointerdown", (event) => {
    pointers += 1;
    const zoomed = window.visualViewport && window.visualViewport.scale > 1.05;
    // The bottom of a video is its scrub bar; dragging there must never decide anything.
    const scrubbing = media.tagName === "VIDEO" && event.clientY > media.getBoundingClientRect().bottom - 72;
    if (pointers > 1 || zoomed || scrubbing || event.target.closest(".info")) return reset();
    start = { x: event.clientX, y: event.clientY };
  });
  stage.addEventListener("pointermove", (event) => {
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    media.style.transform = `translate(${dx}px, ${Math.min(dy, 0)}px)`;
    const choice = choose(dx, dy);
    hint.hidden = !choice;
    if (choice) {
      hint.className = `hint ${choice}`;
      hint.textContent = choice.toUpperCase();
    }
  });
  stage.addEventListener("pointerup", (event) => {
    pointers = Math.max(0, pointers - 1);
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    const choice = choose(dx, dy);
    reset();
    if (choice) decide(choice === "delete" ? "delete" : "keep", choice === "favorite");
    else if (Math.abs(dx) < 8 && Math.abs(dy) < 8 && media.tagName === "IMG") {
      taps(event.clientX, event.clientY, () => (info.hidden = !info.hidden), () => openViewer(item));
    }
  });
  stage.addEventListener("pointercancel", () => {
    pointers = Math.max(0, pointers - 1);
    reset();
  });
}

export function renderItem() {
  const triage = currentTriage();
  const { list, index, runId } = triage;
  const item = list[index];
  triage.tags = new Set(item.decision ? item.decision.tags : []);
  history.replaceState(null, "", `#/triage/${encodeURIComponent(runId)}/${item.library_id}`);
  // Another feature may show this item its own way (a compare); it gets the triage's controls to do it with.
  const controls = { step, advance, rerender: renderItem, showStatus: updateTriageStatus, doubleTaps, openViewer };
  if (slots.claim("item.view", { item, ...controls })) return;

  const media = mediaElement(item);
  const [info] = slots.render("item.info", { item });
  const stage = el("div", { class: "stage" }, [media, info]);
  attachSwipe(stage, media, info, item);

  const tags = el(
    "div",
    { class: "tags", role: "group", "aria-label": "Reason tags" },
    TAGS.map(([value, text]) => {
      const button = el("button", {
        type: "button",
        text,
        "data-tag": value,
        "aria-pressed": String(triage.tags.has(value)),
      });
      button.addEventListener("click", () => {
        const { tags } = currentTriage();
        if (!tags.delete(value)) tags.add(value);
        button.setAttribute("aria-pressed", String(tags.has(value)));
      });
      return button;
    }),
  );
  const action = (className, text, label, onclick) =>
    el("button", { type: "button", class: className, text, "aria-label": label, onclick });
  const choices = [
    action("delete", "Delete", "Delete", () => decide("delete", false)),
    action("favorite", "★ Favorite", "Favorite", () => decide("keep", true)),
    action("keep", "Keep", "Keep", () => decide("keep", false)),
  ];
  const current = triage;
  const allow = () => {
    if (currentTriage() !== current || current.list[current.index] !== item) return;
    current.ready = true;
    for (const button of choices) button.disabled = false;
  };
  current.ready = false;
  for (const button of choices) button.disabled = true;
  media.addEventListener(item.kind === "video" ? "loadedmetadata" : "load", allow, { once: true });
  media.addEventListener(
    "error",
    () =>
      stage.append(
        el("div", { class: "info" }, [
          el("p", { text: "This item could not be loaded." }),
          el("button", { type: "button", class: "primary", text: "Try again", onclick: renderItem }),
          el("button", { type: "button", text: "Decide without seeing it", onclick: allow }),
        ]),
      ),
    { once: true },
  );

  const previous = action("", "‹", "Previous item", () => step(-1));
  previous.disabled = index === 0;
  const next = action("", "›", "Next item", () => step(1));
  next.disabled = index === list.length - 1;

  show(
    runName(runId),
    true,
    el("div", { class: "triage" }, [
      el("div", { class: "status" }, [
        el("span", { id: "state", role: "status" }),
        el("button", { type: "button", text: `${index + 1} / ${list.length} · More info`, onclick: () => (info.hidden = !info.hidden) }),
      ]),
      stage,
      tags,
      ...slots.render("item.tools", { item }),
      el("div", { class: "actions" }, [
        previous,
        ...choices,
        next,
      ]),
    ]),
  );
  updateTriageStatus();
  prefetch(list.slice(index + 1, index + 1 + PREFETCH));
}

export function step(direction) {
  const triage = currentTriage();
  const index = triage.index + direction;
  if (index < 0 || index >= triage.list.length) return;
  triage.index = index;
  renderItem();
}

function decide(verdict, favorite, confirmed = false) {
  const triage = currentTriage();
  if (!triage || Date.now() < triage.lockedUntil) return;
  if (!triage.ready) {
    toast("Still loading");
    return;
  }
  const item = triage.list[triage.index];
  const warning = verdict === "delete" && !confirmed && slots.claim("delete.warn", { items: [item] });
  if (warning) return warning.confirm(() => decide(verdict, favorite, true));
  const tags = [...triage.tags].filter((tag) => !(verdict === "delete" && tag === "needs_fix"));
  decideUndoably([[item, verdict, favorite, tags]]);
  if (navigator.vibrate) navigator.vibrate(15);
  toast(favorite ? "★ Favorite" : verdict === "keep" ? "Kept" : "Deleted");
  advance();
}

export function advance() {
  const triage = currentTriage();
  if (triage.index + 1 < triage.list.length) {
    triage.index += 1;
    renderItem();
    triage.lockedUntil = Date.now() + 250; // a double tap must not decide the next item unseen
  } else {
    toast(isStream(triage.runId) ? "Nothing more to review" : "End of this run");
    location.hash = leaving(triage.runId);
  }
}

// An action says what is wrong with the image: switch those reason tags on, and resend a Keep already made for it.
export function addTags(item, wanted) {
  const triage = currentTriage();
  if (!triage || triage.list[triage.index] !== item) return;
  const before = triage.tags.size;
  for (const tag of wanted) triage.tags.add(tag);
  for (const button of document.querySelectorAll(".tags button[data-tag]")) {
    button.setAttribute("aria-pressed", String(triage.tags.has(button.dataset.tag)));
  }
  const decision = item.decision;
  if (triage.tags.size !== before && decision && decision.verdict === "keep") {
    queueDecision(item, "keep", decision.favorite, [...triage.tags]);
    updateTriageStatus();
  }
}

// The sheet of a rework was closed: if its item is still on screen, review moves on.
export function moveOnAfterRework(item) {
  const triage = currentTriage();
  if (triage && key(triage.list[triage.index]) === key(item) && item.state === "rework") advance();
}

// The periodic refresh keeps the item on screen and only brings its rows up to date, so the scroll stays put.
export async function refreshTriage(view) {
  if (!currentTriage()) return false;
  const fresh = await loadRun(currentTriage().runId);
  if (!view.alive() || !currentTriage()) return false;
  const latest = new Map(fresh.map((item) => [key(item), item]));
  for (const item of currentTriage().list) {
    const found = latest.get(key(item));
    if (found) Object.assign(item, found);
  }
  updateTriageStatus();
  return false;
}
