// The pairing screen.

import { api } from "../../core/api.js";
import { el, show, view } from "../../core/dom.js";
import { flush } from "../../core/outbox.js";
import { route } from "../../core/router.js";
import { forgetScopes } from "../../core/session.js";
import { setTriage } from "../../core/store.js";

export function showPairing() {
  if (view.querySelector(".pair")) return; // never wipe a code that is being typed
  setTriage(null);
  const code = el("input", {
    class: "code",
    name: "code",
    autocomplete: "one-time-code",
    autocapitalize: "characters",
    spellcheck: "false",
    maxlength: "64",
    "aria-label": "Pairing code",
    placeholder: "Code",
  });
  const label = el("input", { name: "label", maxlength: "64", "aria-label": "Phone name", value: "Phone" });
  const error = el("p", { class: "error", role: "alert" });
  const form = el("form", { class: "pair" }, [
    el("p", { text: "In StableNew on the PC, create a pairing code and enter it here within five minutes." }),
    el("p", {
      class: "muted",
      text:
        "Paired before? This browser has lost the pairing, usually because it cleared this site's data. " +
        "In DuckDuckGo, open the ⋮ menu on this page and choose Fireproof this site, then pair once more.",
    }),
    code,
    label,
    el("button", { type: "submit", class: "primary", text: "Pair this phone" }),
    error,
  ]);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!code.value.trim()) return;
    error.textContent = "";
    try {
      await api("/api/pair", { code: code.value, label: label.value });
      forgetScopes();
      flush();
      route();
    } catch (failure) {
      error.textContent =
        failure.status === 429
          ? "Too many attempts. Wait ten minutes."
          : failure.status === 403
            ? "That code did not work. Codes last five minutes and work once."
            : "Could not reach the gateway.";
    }
  });
  show("Pair this phone", false, form);
}
