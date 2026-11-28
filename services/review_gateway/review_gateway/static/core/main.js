// StableNew phone review: start-up. Everything from the server is put on screen as text (textContent), never as
// markup.

import { bus } from "./bus.js";
import { back, view } from "./dom.js";
import { flush, releaseHeld, showBadges } from "./outbox.js";
import { backTarget, refresh, register, route } from "./router.js";
import { slots } from "./slots.js";

const REFRESH_MS = 20000;
// What a feature is handed to register itself with. Everything else it imports from core/.
const core = Object.freeze({ bus, slots });

// The server names the features it has (static_files.py); each is a directory with a feature.js.
async function loadFeatures() {
  const names = document.querySelector('meta[name="rg-features"]').content.split(",").filter(Boolean);
  const loaded = await Promise.all(names.map((name) => import(`../features/${name}/feature.js`)));
  return loaded.map((module) => module.default).sort((a, b) => a.order - b.order);
}

// Every feature is in place before the first screen. If one cannot be loaded, the page keeps its fallback text.
async function start() {
  for (const feature of await loadFeatures()) {
    for (const entry of feature.routes || []) register(entry);
    feature.start?.(core);
  }
  document.getElementById("rejected").before(...slots.render("header.badges"));

  back.addEventListener("click", () => (location.hash = backTarget()));
  window.addEventListener("hashchange", route);
  window.addEventListener("online", () => flush());
  window.addEventListener("storage", () => {
    showBadges();
    flush();
  });
  document.getElementById("rejected").addEventListener("click", () => (location.hash = "#/rejected"));
  document.addEventListener("visibilitychange", refresh);
  document.addEventListener("visibilitychange", () => document.hidden && releaseHeld());
  window.addEventListener("pagehide", releaseHeld);
  setInterval(refresh, REFRESH_MS);

  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  view.replaceChildren(); // the page's fallback text goes once the modules have loaded
  showBadges();
  flush();
  route();
  bus.emit("app:started");
}

start();
