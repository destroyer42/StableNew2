// The Settings screen (PHONE-CORE 2.3): which version this is, whether the phone keeps it, and Repair.

import { api } from "./api.js";
import { el, show } from "./dom.js";
import { describe, repair } from "./sw-client.js";

const pageVersion = () => document.querySelector('meta[name="rg-version"]').content;

export const settingsLink = () =>
  el("button", { type: "button", class: "settings-link", text: "Settings", onclick: () => (location.hash = "#/settings") });

// The commit of the copy that is running; without a worker, the gateway's own.
async function commit() {
  const saved = await describe(navigator.serviceWorker?.controller);
  if (saved?.commit) return saved.commit;
  const session = await api("/api/session").catch(() => null);
  return session?.commit?.slice(0, 12) || "unknown";
}

async function repairAsked(button) {
  // Without the gateway there is nothing to fetch the app from again. Warn, don't block.
  const reachable = await fetch("/sw.js", { cache: "no-store" }).then(
    (response) => response.ok,
    () => false,
  );
  const question =
    "The gateway cannot be reached. Repair removes the saved app, so it will not open until the gateway is back. Continue?";
  if (!reachable && !window.confirm(question)) return;
  button.disabled = true;
  await repair();
}

export async function showSettings(view) {
  const saved = await window.caches?.has(`rg-shell-${pageVersion()}`);
  const kept = await navigator.storage?.persisted?.();
  const running = await commit();
  if (!view.alive()) return;
  const button = el("button", { type: "button", class: "wide", text: "Repair this app" });
  button.addEventListener("click", () => repairAsked(button));
  show(
    "Settings",
    true,
    el("h2", { class: "section-title", text: "About" }),
    el("p", { id: "about-version", text: `Version ${pageVersion()} · commit ${running.slice(0, 7)}` }),
    el("p", {
      class: "muted",
      text: saved
        ? "Saved on this phone: it opens without the gateway."
        : "Not saved on this phone yet: it needs the gateway to open.",
    }),
    kept
      ? null
      : el("p", {
          class: "muted",
          text: "This phone may clear saved work under storage pressure. Install the app in Chrome to keep it.",
        }),
    el("h2", { class: "section-title", text: "Repair" }),
    el("p", {
      class: "muted",
      text: "Removes the saved copy of the app and fetches it again. Pairing, unsent work and settings stay.",
    }),
    button,
  );
}
