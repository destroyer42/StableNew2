// RG-160: phone actions made while the PC is away. Loaded before app.js and uses its helpers (el, api, sheet, ...) only
// when called. A request is saved in the same list as unsent decisions, so it also survives a dropped connection, and
// the gateway keeps it until the PC can take it. Everything from the server is put on screen as text.
"use strict";

const Queued = (() => {
  const CATALOG_KEY = "rg.catalog";
  const SEEN_KEY = "rg.pcSeen";
  const DISMISSED_KEY = "rg.dismissed";
  // A PC that is there answers a summary within seconds; after this long the phone offers not to wait for it.
  const OFFER_AFTER_MS = 10000;
  const NOT_READY = new Set(["adetailer_unavailable", "model_unavailable"]);
  const AWAY_SAVE = "The PC checks this when it is back and queues it with any warnings.";

  const kept = new Map(); // used when storage is unusable
  let latest = null; // the last /api/requests reply
  let offline = false; // this phone could not reach the gateway
  let asked = {}; // what the open online request was made with
  let listing = 0;

  function recall(name, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(name) || "null");
      if (value !== null) return value;
    } catch {
      // private browsing: only what this page remembers
    }
    return kept.has(name) ? kept.get(name) : fallback;
  }

  function keep(name, value) {
    kept.set(name, value);
    try {
      localStorage.setItem(name, JSON.stringify(value));
    } catch {
      // the page's memory has it
    }
  }

  const catalog = () => recall(CATALOG_KEY, null);
  const usable = () => canQueue() && Boolean(catalog());
  const unsent = () => readList(QUEUE_KEY).filter((entry) => entry.action);

  // --- is the PC there? -------------------------------------------------------------------------------------------

  function since(milliseconds) {
    const minutes = Math.max(1, Math.round(milliseconds / 60000));
    if (minutes < 120) return `${minutes} min`;
    const hours = Math.round(minutes / 60);
    return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
  }

  // The age of the PC's last request, by the gateway's clock plus the time since the phone read it.
  function pcAge() {
    const seen = recall(SEEN_KEY, null);
    if (!seen || !seen.pc_seen_at) return null;
    return Date.parse(seen.now) - Date.parse(seen.pc_seen_at) + (Date.now() - seen.read_at);
  }

  function away() {
    if (offline) return true;
    const age = pcAge();
    return age === null || age > STATUS_STALE_MS;
  }

  function presence() {
    if (offline) return "The gateway is not reachable from this phone";
    const age = pcAge();
    if (age === null) return "The PC has not been seen";
    return age > STATUS_STALE_MS ? `PC last seen ${since(age)} ago` : "The PC is there";
  }

  async function sync() {
    await loadScopes();
    if (!canQueue()) return badge();
    try {
      const data = await api("/api/requests");
      latest = data;
      offline = false;
      keep(SEEN_KEY, { pc_seen_at: data.pc_seen_at, now: data.now, read_at: Date.now() });
      const held = recall(CATALOG_KEY, null);
      if (data.catalog_at && (!held || held.received_at !== data.catalog_at)) {
        const reply = await api("/api/catalog");
        if (reply.catalog) keep(CATALOG_KEY, { ...reply.catalog, received_at: reply.received_at });
      }
    } catch (error) {
      if (!error.status) offline = true; // anything the gateway answered (an older one: 404) is not "offline"
    }
    badge();
  }

  // --- the header and the marks -----------------------------------------------------------------------------------

  function answered() {
    const dismissed = new Set(recall(DISMISSED_KEY, []));
    return (latest ? latest.requests : []).filter((e) => e.state !== "pending" && !dismissed.has(e.record_id));
  }

  function badge() {
    const button = document.getElementById("waiting");
    if (!button) return;
    const pending = (latest ? latest.requests.filter((e) => e.state === "pending").length : 0) + unsent().length;
    const replies = answered().length;
    button.textContent = pending ? `${pending} waiting for PC` : `${replies} from PC`;
    button.hidden = !pending && !replies;
  }

  const waitingOn = (item) => Boolean(item.waiting && item.waiting.length);

  function mark(item) {
    return waitingOn(item) && item.state !== "rework"
      ? el("span", { class: "badge waiting", text: "⌛", title: "A request is waiting for the PC" })
      : null;
  }

  const suffix = (item) => (waitingOn(item) ? " · request waiting for PC" : "");

  // The inbox line for a phone that is not sent the PC's queue.
  function line(status) {
    if (!status || status.pc || !status.pc_seen_at) return null;
    const age = Date.parse(status.now) - Date.parse(status.pc_seen_at);
    return age > STATUS_STALE_MS ? el("p", { class: "muted", text: `PC last seen ${since(age)} ago.` }) : null;
  }

  // Every copy of an item in these lists, including the one a rework result is compared with: "Keep rework" deletes
  // that copy, so it must know what waits for it.
  const copiesOf = (items, entry) =>
    items.flatMap((item) => [item, item.compare]).filter((copy) => copy && key(copy) === key(entry));

  const onScreen = () => [...runItems.values(), triage ? triage.list : []].flat();

  function noteWaiting(copy, action) {
    copy.waiting = [...(copy.waiting || []).filter((other) => other !== action), action];
  }

  // Requests still on this phone, shown on the items they are about.
  function overlay(items) {
    for (const entry of unsent()) {
      for (const copy of copiesOf(items, entry)) noteWaiting(copy, entry.action);
      for (const item of items.filter((i) => key(i) === key(entry))) {
        if (REWORK.has(entry.action) && needsReview(item)) item.state = "rework";
      }
    }
    return items;
  }

  // --- making a request -------------------------------------------------------------------------------------------

  function paramsFor(action, extra) {
    return {
      step: "queue",
      ...(extra.choice ? { choice: extra.choice } : {}),
      ...(extra.text ? { text: extra.text } : {}),
      ...(action === "more_like_this" ? { count: 4 } : {}),
    };
  }

  const alreadyWaiting = (item, action) =>
    (item.waiting || []).includes(action) || unsent().some((e) => e.action === action && key(e) === key(item));

  function add(item, action, extra) {
    const entry = {
      action,
      library_id: item.library_id,
      sha256: item.sha256,
      params: paramsFor(action, extra),
      idempotency_key: idempotencyKey(),
    };
    changeList(QUEUE_KEY, (list) => [...list, entry]);
    for (const copy of [item, ...copiesOf(onScreen(), item)]) noteWaiting(copy, action);
    if (REWORK.has(action)) markRework(item, true);
    flush();
    badge();
    toast("Saved; the PC runs it when it can");
    if (REWORK.has(action)) closeAfterRework(item); // review moves on, as it does for a rework queued online
    else {
      closeSheet();
      updateTriageStatus();
    }
    redraw();
  }

  // The waiting list, redrawn unless a sheet is open over it.
  function redraw() {
    if (location.hash === "#/requests" && !document.getElementById("sheet")) route();
  }

  // The gateway answered (or refused) a saved request.
  async function sent(entry, state) {
    if (state === "rejected") {
      for (const copy of copiesOf(onScreen(), entry)) {
        copy.waiting = (copy.waiting || []).filter((action) => action !== entry.action);
      }
      for (const copy of findItem(key(entry))) {
        if (REWORK.has(entry.action)) markRework(copy, false);
      }
    }
    await sync();
    redraw();
  }

  function sheetFor(item, action, extra = {}, note = "") {
    const known = catalog();
    const label = actionLabel(action);
    let choice = extra.choice || "";
    const picker = Boolean(PICKERS[action]);
    const words = WORDS[action];
    const input = words
      ? el("input", { maxlength: "200", placeholder: words.placeholder, "aria-label": label, autocomplete: "off" })
      : null;
    if (input) input.value = extra.text || "";
    const error = el("p", { class: "error", role: "alert" });
    const warnings = el("div", {});
    const choices = !picker ? [] : action === "another_model" ? known.models : known.ratios;
    if (!choices.some((entry) => entry.id === choice)) choice = "";
    const queue = el("button", { type: "button", class: "primary", text: "Queue when the PC is back" });
    const buttons = choices.map((entry) => {
      const warned = entry.warnings && entry.warnings.length;
      const button = el("button", { type: "button", text: warned ? `${entry.label} ⚠` : entry.label });
      button.addEventListener("click", () => {
        choice = entry.id;
        select();
      });
      return [button, entry];
    });
    function select() {
      for (const [button, entry] of buttons) button.setAttribute("aria-pressed", String(entry.id === choice));
      const entry = choices.find((candidate) => candidate.id === choice);
      const found = entry && entry.warnings ? entry.warnings.map((index) => known.warnings[index]).filter(Boolean) : [];
      warnings.replaceChildren(...found.map(warningBlock));
      queue.disabled = picker && !choice;
    }
    queue.addEventListener("click", () => {
      // One line of plain text: the PC refuses control characters, so they never leave the phone.
      const text = input ? input.value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, 200) : "";
      if (words && words.required && !text) {
        error.textContent = "Type a few words first.";
        return;
      }
      queue.disabled = true;
      add(item, action, { choice, text });
    });
    const asOf = known.models_as_of
      ? ` · list as of ${new Date(known.models_as_of).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}`
      : "";
    const video =
      action !== "make_video"
        ? null
        : known.video.available
          ? el("p", { class: "muted", text: known.video.label || "Make Video" })
          : warningBlock({ title: "The PC had no approved Make Video workflow.", why: "It checks again when it takes the request." });
    sheet(
      el("h2", { text: label }),
      el("p", { class: "muted", text: `${presence()}${picker ? asOf : ""}` }),
      note ? el("p", { text: note }) : null,
      picker ? el("p", { class: "muted", text: PICKERS[action] }) : null,
      words ? el("p", { class: "muted", text: words.hint }) : null,
      action === "more_like_this" ? el("p", { class: "muted", text: "4 new images, each with a new seed." }) : null,
      picker && !choices.length ? el("p", { text: "The PC has not listed any checkpoints yet." }) : null,
      picker ? el("div", { class: "choices", role: "group", "aria-label": "Options" }, buttons.map(([button]) => button)) : null,
      input,
      video,
      warnings,
      alreadyWaiting(item, action) ? warningBlock({ title: "Already waiting. Queue another?" }) : null,
      error,
      el("p", { class: "muted", text: AWAY_SAVE }),
      el("div", { class: "sheet-actions" }, [el("button", { type: "button", text: "Cancel", onclick: closeSheet }), queue]),
    );
    select();
  }

  // Called before asking the PC: with the PC away, the request is made to wait instead.
  function offer(item, action, extra = {}) {
    asked = extra;
    if (!usable() || !away()) return false;
    sheetFor(item, action, extra);
    return true;
  }

  // A prepare refused only because the image backend is not connected can still wait for it.
  function notReady(item, action, answer) {
    const detail = answer.receipt && answer.receipt.detail;
    if (answer.step !== "prepare" || !NOT_READY.has(detail) || !usable()) return false;
    sheetFor(item, action, asked, "Forge is not connected on the PC.");
    return true;
  }

  // The gateway could not be reached at all.
  function unreachable(item, action) {
    if (!usable()) return false;
    offline = true;
    sheetFor(item, action, asked, "The request is saved on this phone and sent when the gateway is reachable.");
    return true;
  }

  // After a while with no answer, offer to leave the request waiting instead. ``step`` is what the PC was asked.
  function watch(node, item, action, recordId, step) {
    const extra = asked;
    setTimeout(() => {
      if (document.getElementById("sheet") !== node || !usable()) return;
      const holder = node.querySelector(".sheet-actions") || el("div", { class: "sheet-actions" });
      if (!holder.parentNode) node.querySelector(".sheet-body").append(holder);
      holder.append(
        el("button", {
          type: "button",
          class: "primary",
          text: "Queue when the PC is back",
          onclick: () => leave(item, action, extra, recordId, step),
        }),
      );
    }, OFFER_AFTER_MS);
  }

  async function leave(item, action, extra, recordId, step) {
    const say = (text) =>
      sheet(
        el("h2", { text: actionLabel(action) }),
        el("p", { text }),
        el("div", { class: "sheet-actions" }, [el("button", { type: "button", text: "Close", onclick: closeSheet })]),
      );
    say("One moment…"); // the online wait ends with its sheet
    let state = "";
    try {
      state = (await api(`/api/actions/${recordId}/cancel`, {})).state;
    } catch {
      // a prepare admits nothing, so one left behind is harmless; a confirm is not converted without knowing
      if (step === "confirm") return say("Could not reach the gateway, so the request was left as it is.");
    }
    if (step !== "confirm") return sheetFor(item, action, extra);
    if (state === "cancelled") return add(item, action, extra);
    if (state === "refused") {
      markRework(item, false);
      return say("The PC has already refused this request. Ask again to see why.");
    }
    say("The PC already has this request. Its result appears when it runs.");
  }

  // --- the waiting list -------------------------------------------------------------------------------------------

  function dismiss(recordId) {
    keep(DISMISSED_KEY, [...recall(DISMISSED_KEY, []), recordId].slice(-500));
  }

  function describe(entry, backendReady) {
    if (entry.state === "pending") {
      if (!entry.delivered) return "Waiting for PC";
      return backendReady === false ? "Waiting for Forge on the PC" : "The PC has it";
    }
    if (entry.state === "cancelled") return entry.delivered ? "Cancel sent" : "Cancelled";
    if (entry.state === "refused") {
      return entry.reason_code === "invalid_record"
        ? "Refused: StableNew on the PC does not take waiting requests. Update it."
        : `Refused: ${refusalText(entry)}`;
    }
    const jobs = ((entry.receipt && entry.receipt.job_ids) || []).length;
    const count = `${jobs} job${jobs === 1 ? "" : "s"}`;
    return entry.too_late ? "Queued (too late to cancel)" : `Queued, ${count}`;
  }

  async function cancel(recordId) {
    try {
      const { state } = await api(`/api/actions/${recordId}/cancel`, {});
      if (state === "cancelled") dismiss(recordId);
      toast(state === "cancelled" ? "Cancelled" : state === "cancel_sent" ? "Cancel sent" : "The PC already answered");
    } catch {
      toast("Could not reach the gateway");
    }
    route();
  }

  function row(entry, text, buttons, warnings = []) {
    return el("section", { class: "run queued" }, [
      el("img", { src: mediaUrl(entry, "thumb"), alt: "", loading: "lazy" }),
      el("div", {}, [
        el("h2", { text: actionLabel(entry.action) }),
        el("p", { class: entry.state === "refused" ? "error" : "muted", text }),
        ...warnings.map((warning) => el("p", { class: "warning-title", text: `⚠ ${warning.title}` })),
        el("div", { class: "tools" }, buttons),
      ]),
    ]);
  }

  const button = (text, onclick) => el("button", { type: "button", text, onclick });

  function entryRow(entry) {
    const forget = () => {
      dismiss(entry.record_id);
      route();
    };
    const buttons =
      entry.state === "pending"
        ? [button("Cancel", () => cancel(entry.record_id))]
        : [
            entry.state === "refused" && usable()
              ? button("Choose again", () => {
                  dismiss(entry.record_id);
                  const item = { library_id: entry.library_id, sha256: entry.sha256, kind: "image" };
                  sheetFor(item, entry.action, { text: entry.text || "" });
                })
              : null,
            button("Dismiss", forget),
          ];
    const summary = entry.state === "applied" && entry.receipt && entry.receipt.action_summary;
    return row(entry, describe(entry, latest.image_backend_ready), buttons, summary ? summary.warnings : []);
  }

  async function show_(serial) {
    const asking = ++listing;
    await sync();
    if (serial !== renderSerial || asking !== listing) return;
    const dismissed = new Set(recall(DISMISSED_KEY, []));
    const local = unsent().map((entry) =>
      row(entry, "Not sent yet", [
        button("Cancel", () => {
          changeList(QUEUE_KEY, without(entry.idempotency_key));
          route();
        }),
      ]),
    );
    const remote = (latest ? latest.requests : []).filter((e) => !dismissed.has(e.record_id)).map(entryRow);
    const rows = [...local, ...remote];
    show(
      "Waiting for the PC",
      true,
      el("p", { class: "muted", text: presence() }),
      ...(rows.length ? rows : [el("p", { class: "muted", text: "Nothing is waiting." })]),
    );
  }

  // Delete archives the file, so what is waiting for it cannot run: say so first.
  function confirmDelete(proceed) {
    sheet(
      el("h2", { text: "Delete this image?" }),
      el("p", { text: "A request for this image is waiting. Deleting cancels it." }),
      el("div", { class: "sheet-actions" }, [
        button("Cancel", closeSheet),
        el("button", {
          type: "button",
          class: "primary",
          text: "Delete",
          onclick: () => {
            closeSheet();
            proceed();
          },
        }),
      ]),
    );
  }

  return {
    sync,
    badge,
    mark,
    suffix,
    line,
    overlay,
    sent,
    offer,
    notReady,
    unreachable,
    watch,
    waitingOn,
    confirmDelete,
    show: show_,
  };
})();
