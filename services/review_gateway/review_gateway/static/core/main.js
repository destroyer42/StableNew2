// StableNew phone review: start-up. Everything from the server is put on screen as text (textContent), never as
// markup.

import { settingsLink, showSettings } from "./about.js";
import { bus } from "./bus.js";
import { back, banner, view } from "./dom.js";
import { flush, releaseHeld, showBadges } from "./outbox.js";
import { backTarget, refresh, register, route } from "./router.js";
import { slots } from "./slots.js";
import { applyUpdate, onUpdate, register as registerWorker } from "./sw-client.js";

const REFRESH_MS = 20000;
// What a feature is handed to register itself with. Everything else it imports from core/.
const core = Object.freeze({ bus, slots });

// The server names the features it has (static_files.py); each is a directory with a feature.js.
async function loadFeatures() {
  const names = document.querySelector('meta[name="rg-features"]').content.split(",").filter(Boolean);
  const loaded = await Promise.all(names.map((name) => import(`../features/${name}/feature.js`)));
  return loaded.map((module) => module.default).sort((a, b) => a.order - b.order);
}

// PHONE-CORE 2.3: the app is saved on the phone, and a new version is offered, never forced. This comes before the
// features, so a version in which one of them is broken can still be replaced.
function keepSaved() {
  onUpdate((found) => {
    const name = found?.commit ? ` · ${found.commit.slice(0, 7)}` : "";
    banner(`Update available${name}`, "Reload", () => {
      releaseHeld(); // what is still held for Undo is sent now, as on leaving the page
      applyUpdate();
    });
  });
  registerWorker().catch((error) => console.warn("the app was not saved on this phone", error));
}

// Every feature is in place before the first screen. If one cannot be loaded, the page keeps its fallback text.
async function start() {
  keepSaved();
  register({ pattern: "#/settings", render: (params, view) => showSettings(view) });
  for (const feature of await loadFeatures()) {
    for (const entry of feature.routes || []) register(entry);
    feature.start?.(core);
  }
  slots.contribute("home.bottom", settingsLink); // after the features' own, so it stays last
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
