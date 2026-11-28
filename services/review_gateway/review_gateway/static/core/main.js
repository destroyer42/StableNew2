// StableNew phone review: start-up. Everything from the server is put on screen as text (textContent), never as
// markup.

import { back, view } from "./dom.js";
import { flush, releaseHeld, showBadges } from "./outbox.js";
import { leaving, refresh, route } from "./router.js";
import * as Queued from "../features/queued/queued.js";

const REFRESH_MS = 20000;

back.addEventListener("click", () => {
  const [, page, run] = location.hash.split("/");
  location.hash = (page === "triage" || page === "run") && run ? leaving(decodeURIComponent(run), page === "triage") : page === "rate" && run ? "#/rate" : "#/";
});
window.addEventListener("hashchange", route);
window.addEventListener("online", () => flush());
window.addEventListener("storage", () => {
  showBadges();
  flush();
});
document.getElementById("rejected").addEventListener("click", () => (location.hash = "#/rejected"));
document.getElementById("waiting").addEventListener("click", () => (location.hash = "#/requests"));
document.addEventListener("visibilitychange", refresh);
document.addEventListener("visibilitychange", () => document.hidden && releaseHeld());
window.addEventListener("pagehide", releaseHeld);
setInterval(refresh, REFRESH_MS);

if ("scrollRestoration" in history) history.scrollRestoration = "manual";
view.replaceChildren(); // the page's fallback text goes once the modules have loaded
showBadges();
flush();
route();
Queued.sync();
