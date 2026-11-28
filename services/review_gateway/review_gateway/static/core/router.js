// Hash routes, the render serial, the refresh, and where each list was left.

import { closeSheet, el, show, view } from "./dom.js";
import { flush, showRejected } from "./outbox.js";
import { currentTriage, key, loadRun, setTriage } from "./store.js";
import { SECTIONS, isStream } from "./text.js";
import { showHome, showRun, showSection } from "../features/inbox/inbox.js";
import { showPairing } from "../features/pairing/pairing.js";
import * as Queued from "../features/queued/queued.js";
import * as Rating from "../features/rating/rating.js";
import { showUpdate } from "../features/status/status.js";
import { showTriage, updateTriageStatus } from "../features/triage/triage.js";
import { closeViewer } from "../features/triage/viewer.js";

let renderSerial = 0;
let section = ""; // the section being looked in, where "back" from one of its runs returns to

// A screen compares the number it was started with: a later route makes it stale.
export const currentSerial = () => renderSerial;
export const setSection = (name) => {
  section = name;
};

// --- scroll position (PHONE-FAST) ---------------------------------------------------------------------------------
// The home, section and run lists come back where they were left. A place is remembered by the entries on screen, so
// it holds when reviewed ones have left the list; the pixel offset is the fallback.

const places = new Map(); // list address -> { y, seen: [[entry id, distance from the top of the window]] }
let listed = null; // the address of the list on screen ("" is home), null for any other view

const listName = (hash) => hash.replace(/^#\/?/, "");
const entries = () => [...view.querySelectorAll("[data-anchor]")];

function savePlace() {
  if (listed === null) return;
  const header = document.getElementById("bar")?.offsetHeight || 0;
  const seen = entries()
    .map((node) => [node.getAttribute("data-anchor"), node.getBoundingClientRect()])
    .filter(([, box]) => box.bottom > header)
    .slice(0, 12)
    .map(([id, box]) => [id, box.top]);
  places.set(listed, { y: window.scrollY, seen });
}

function restorePlace(name) {
  listed = name;
  const place = places.get(name);
  window.scrollTo(0, place ? place.y : 0);
  if (!place) return;
  const present = new Map(entries().map((node) => [node.getAttribute("data-anchor"), node]));
  for (const [id, top] of place.seen) {
    const node = present.get(id);
    if (node) {
      window.scrollBy(0, node.getBoundingClientRect().top - top);
      return;
    }
  }
}

// --- routing ------------------------------------------------------------------------------------------------------

// Where "back" goes from a run or from reviewing it: the grid, else the section it was opened from, else home.
export function leaving(runId, fromTriage = true) {
  if (fromTriage && !isStream(runId)) return `#/run/${encodeURIComponent(runId)}`;
  const name = runId.startsWith("all:") ? runId.slice(4) : runId === "all" ? "" : section;
  return name ? `#/section/${name}` : "#/";
}

export async function route() {
  const serial = ++renderSerial;
  const [, page, run, libraryId] = location.hash.split("/");
  const name = listName(location.hash);
  savePlace();
  listed = null;
  setTriage(null);
  closeViewer();
  closeSheet();
  try {
    if (page === "triage" && run) await showTriage(decodeURIComponent(run), libraryId, serial);
    else if (page === "run" && run) await showRun(decodeURIComponent(run), serial);
    else if (page === "rejected") showRejected();
    else if (page === "update") await showUpdate(serial);
    else if (page === "requests") await Queued.show(serial);
    else if (page === "rate") await Rating.route(run, libraryId, serial);
    else if (page === "section" && SECTIONS[run]) await showSection(run, serial);
    else await showHome(serial);
    const isList = !page || page === "run" || page === "section";
    if (isList && serial === renderSerial) restorePlace(name);
  } catch (error) {
    if (serial !== renderSerial) return;
    if (error.status === 401) showPairing();
    else if (error.status === 403) show("Review", false, el("p", { text: "This phone is not allowed to review." }));
    else
      show(
        "Review",
        Boolean(page),
        el("p", { class: "error", text: "Could not reach the gateway." }),
        el("button", { type: "button", text: "Try again", onclick: route }),
      );
  }
}

export async function refresh() {
  if (document.hidden) return;
  flush();
  if (view.querySelector(".pair")) return;
  Queued.sync();
  const [, page, run] = location.hash.split("/");
  const serial = renderSerial;
  const scroll = window.scrollY;
  try {
    if (currentTriage()) {
      const fresh = await loadRun(currentTriage().runId);
      if (serial !== renderSerial || !currentTriage()) return;
      const latest = new Map(fresh.map((item) => [key(item), item]));
      for (const item of currentTriage().list) {
        const found = latest.get(key(item));
        if (found) Object.assign(item, found);
      }
      updateTriageStatus();
    } else if (page === "run" && run) {
      await showRun(decodeURIComponent(run), serial);
      window.scrollTo(0, scroll);
    } else if (page === "requests") {
      if (!document.getElementById("sheet")) await Queued.show(serial);
      window.scrollTo(0, scroll);
    } else if (page === "update") {
      await showUpdate(serial);
      window.scrollTo(0, scroll);
    } else if (page === "section" && SECTIONS[run]) {
      await showSection(run, serial);
      window.scrollTo(0, scroll);
    } else if (!page) {
      await showHome(serial);
      window.scrollTo(0, scroll);
    }
  } catch (error) {
    if (error.status === 401) showPairing();
  }
}
