// Hash routes, the render serial, the refresh, and where each list was left.

import { bus } from "./bus.js";
import { closeSheet, el, show, view } from "./dom.js";
import { flush, showRejected } from "./outbox.js";
import { setTriage } from "./store.js";
import { isStream } from "./text.js";

let renderSerial = 0;
let section = ""; // the section being looked in, where "back" from one of its runs returns to

// A screen asks its view whether a later route has made it stale.
const viewOf = (serial) => ({ alive: () => serial === renderSerial });
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

// --- the route table ----------------------------------------------------------------------------------------------
// A feature's route is {pattern: "#/page/:name/:optional?", render(params, view), accepts?(params), list?: true (the
// scroll place is kept), refresh?(params, view) (false: leave the scroll alone), back?(params)}. "#/" is home, and
// whatever matches nothing shows it.

const routes = new Map(); // page ("" is home) -> entry

export function register(entry) {
  const [, page, ...names] = entry.pattern.split("/");
  routes.set(page, { ...entry, names: names.filter(Boolean) });
}

function match(hash) {
  const [, page = "", ...values] = hash.split("/");
  const entry = routes.get(page);
  if (!entry) return null;
  const params = {};
  for (const [position, name] of entry.names.entries()) {
    const optional = name.endsWith("?");
    if (values[position]) params[name.slice(1, optional ? -1 : undefined)] = values[position];
    else if (!optional) return null;
  }
  return entry.accepts && !entry.accepts(params) ? null : { entry, params };
}

export const backTarget = () => {
  const found = match(location.hash);
  return found?.entry.back?.(found.params) || "#/";
};

register({ pattern: "#/rejected", render: () => showRejected() });

export async function route() {
  const serial = ++renderSerial;
  const [, page] = location.hash.split("/");
  const name = listName(location.hash);
  savePlace();
  listed = null;
  setTriage(null);
  bus.emit("route:start");
  closeSheet();
  try {
    const { entry, params } = match(location.hash) || { entry: routes.get(""), params: {} };
    await entry.render(params, viewOf(serial));
    const isList = !page || routes.get(page)?.list;
    if (isList && serial === renderSerial) restorePlace(name);
  } catch (error) {
    if (serial !== renderSerial) return;
    if (error.status === 401) bus.emit("session:lost");
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
  bus.emit("app:refresh");
  const found = match(location.hash);
  const serial = renderSerial;
  const scroll = window.scrollY;
  try {
    if (found?.entry.refresh && (await found.entry.refresh(found.params, viewOf(serial))) !== false) {
      window.scrollTo(0, scroll);
    }
  } catch (error) {
    if (error.status === 401) bus.emit("session:lost");
  }
}
