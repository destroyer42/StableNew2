// A rework or reprocess result against its original.

import { el, show, toast } from "../../core/dom.js";
import { PREFETCH, mediaUrl, prefetch } from "../../core/media.js";
import { decideUndoably } from "../../core/outbox.js";
import { readSetting, writeSetting } from "../../core/settings.js";
import { currentTriage } from "../../core/store.js";
import { runName } from "../../core/text.js";
import { actionRow } from "../actions/actions.js";
import { infoPanel } from "../info/moreinfo.js";
import * as Queued from "../queued/queued.js";
import { advance, renderItem, step, updateTriageStatus } from "../triage/triage.js";
import { doubleTaps, openViewer } from "../triage/viewer.js";

// --- compare a rework with its original (PHONE-FAST) --------------------------------------------------------------
// Three views, the phone's choice: side by side (tap one to see it alone), flip (tap or swipe) and a before/after
// slider. Picking keeps one and discards the other.
const COMPARE_KEY = "rg.compare";
const COMPARE_MODES = [
  ["side", "Side by side"],
  ["flip", "Flip"],
  ["slider", "Slider"],
];

export function renderCompare(item) {
  const triage = currentTriage();
  const { list, index, runId } = triage;
  const original = item.compare;
  const current = triage;
  const result = original.desk ? "Reprocess" : "Rework";
  const sides = [
    ["Original", original],
    [result, item],
  ];
  const images = sides.map(([name, side]) =>
    el("img", {
      src: mediaUrl(side, side.variants.includes("preview") ? "preview" : "original"),
      alt: name,
      draggable: "false",
    }),
  );
  const figures = sides.map(([name], position) =>
    el("figure", {}, [el("figcaption", { text: name }), images[position]]),
  );
  const divider = el("div", { class: "divider", "aria-hidden": "true" });
  const stage = el("div", { class: "stage compare" }, [...figures, divider]);
  let mode = "side";
  let shown = 1;
  let split = 50; // the slider: the original left of it, the rework right of it
  const toggles = COMPARE_MODES.map(([value, text]) =>
    el("button", {
      type: "button",
      text,
      onclick: () => {
        writeSetting(COMPARE_KEY, value);
        setMode(value);
      },
    }),
  );
  const showSide = (position) => {
    shown = position;
    figures.forEach((figure, i) => figure.classList.toggle("shown", i === shown));
  };
  const slide = (percent) => {
    split = Math.min(100, Math.max(0, percent));
    figures[1].style.clipPath = mode === "slider" ? `inset(0 0 0 ${split}%)` : "";
    divider.style.left = `${split}%`;
  };
  const setMode = (value) => {
    mode = value;
    stage.className = `stage compare ${mode}`;
    toggles.forEach((toggle, i) => toggle.setAttribute("aria-pressed", String(COMPARE_MODES[i][0] === mode)));
    divider.hidden = mode !== "slider";
    showSide(shown);
    slide(split);
  };
  const saved = readSetting(COMPARE_KEY, "side");
  setMode(COMPARE_MODES.some(([value]) => value === saved) ? saved : "side");
  const across = (event) => {
    const box = stage.getBoundingClientRect();
    return ((event.clientX - box.left) / (box.width || 1)) * 100;
  };
  const taps = doubleTaps();
  let start = null;
  stage.addEventListener("pointerdown", (event) => {
    start = event.isPrimary ? { x: event.clientX, y: event.clientY, target: event.target } : null;
  });
  stage.addEventListener("pointermove", (event) => {
    if (start && mode === "slider" && Math.abs(event.clientX - start.x) >= 8) slide(across(event));
  });
  stage.addEventListener("pointercancel", () => (start = null));
  stage.addEventListener("pointerup", (event) => {
    if (!start || event.target.closest(".info")) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    const touched = figures.findIndex((figure) => figure.contains(start.target));
    start = null;
    const zoomed = window.visualViewport && window.visualViewport.scale > 1.05;
    if (zoomed) return;
    const tap = Math.abs(dx) < 8 && Math.abs(dy) < 8;
    const swipe = Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy);
    if (mode === "flip" && swipe) return showSide(1 - shown);
    if (!tap) return;
    const at = across(event);
    // The picture under the finger.
    const side = mode === "slider" ? Number(at >= split) : mode === "flip" ? shown : touched;
    if (side < 0) return;
    const single = () => {
      if (mode === "slider") slide(at);
      else if (mode === "flip") showSide(1 - shown);
      else {
        shown = side;
        setMode("flip"); // one alone for a closer look; the saved view stays side by side
      }
    };
    taps(event.clientX, event.clientY, single, () => openViewer(sides[side][1]));
  });

  const button = (className, text, onclick) =>
    el("button", { type: "button", class: className, text, "aria-label": text, onclick });
  const choices = [
    button("keep", "Keep original", () => pick(original, item)),
    button("keep", `Keep ${result.toLowerCase()}`, () => pick(item, original)),
    button("keep", "Keep both", () => pick(item, original, true)),
  ];
  const allow = () => {
    if (currentTriage() !== current || current.list[current.index] !== item) return;
    current.ready = true;
    for (const choice of choices) choice.disabled = false;
  };
  current.ready = false;
  for (const choice of choices) choice.disabled = true;
  let loaded = 0;
  for (const image of images) {
    image.addEventListener("load", () => (loaded += 1) === images.length && allow(), { once: true });
    image.addEventListener(
      "error",
      () =>
        stage.append(
          el("div", { class: "info" }, [
            el("p", { text: "One of the two could not be loaded." }),
            el("button", { type: "button", class: "primary", text: "Try again", onclick: renderItem }),
            el("button", { type: "button", text: "Decide without seeing it", onclick: allow }),
          ]),
        ),
      { once: true },
    );
  }
  const info = infoPanel(item, original);
  stage.append(info);
  const previous = button("", "‹", () => step(-1));
  previous.disabled = index === 0;
  const next = button("", "›", () => step(1));
  next.disabled = index === list.length - 1;
  show(
    runName(runId),
    true,
    el("div", { class: "triage" }, [
      el("div", { class: "status" }, [
        el("span", { id: "state", role: "status" }),
        el("button", { type: "button", text: `${index + 1} / ${list.length} · More info`, onclick: () => (info.hidden = !info.hidden) }),
      ]),
      el("div", { class: "modes", role: "group", "aria-label": "Compare view" }, toggles),
      stage,
      actionRow(item),
      el("div", { class: "actions compare-actions" }, [previous, ...choices, next]),
    ]),
  );
  updateTriageStatus();
  prefetch(list.slice(index + 1, index + 1 + PREFETCH));
}

function pick(winner, loser, both = false, confirmed = false) {
  const triage = currentTriage();
  if (!triage || Date.now() < triage.lockedUntil) return;
  if (!triage.ready) {
    toast("Still loading");
    return;
  }
  if (!both && !confirmed && Queued.waitingOn(loser)) {
    return Queued.confirmDelete(() => pick(winner, loser, false, true));
  }
  decideUndoably(
    [
      [winner, "keep"],
      [loser, both ? "keep" : "delete"],
    ].map(([side, verdict]) => {
      const before = side.decision;
      const tags = before ? before.tags : [];
      return [
        side,
        verdict,
        verdict === "keep" && Boolean(before && before.favorite),
        verdict === "keep" ? tags : tags.filter((tag) => tag !== "needs_fix"),
      ];
    }),
  );
  if (navigator.vibrate) navigator.vibrate(15);
  toast(both ? "Both kept" : "Picked; the other goes to the archive");
  advance();
}
