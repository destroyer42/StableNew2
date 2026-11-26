// StableNew phone review. Everything from the server is put on screen as text (textContent), never as markup.
"use strict";

const TAGS = [
  ["face", "Face"],
  ["hands", "Hands"],
  ["anatomy", "Anatomy"],
  ["artifact", "Artifact"],
  ["prompt_miss", "Prompt miss"],
  ["needs_fix", "Needs fix"],
];
const REASONS = {
  digest_mismatch: "the file changed on the PC",
  unknown_item: "the PC no longer has this item",
  revoked_device: "this phone was revoked",
  not_granted: "not allowed",
  invalid_record: "the PC rejected the request",
  favorite_with_delete: "favorite and delete together",
  archive_failed: "the PC could not move the file",
  admission_refused: "the PC refused the action",
};
const REFRESH_MS = 20000;
const QUEUE_KEY = "rg.unsent";
const REJECTED_KEY = "rg.rejected";
const ANSWERS = new Set(["pending", "applied", "refused"]);
const NOT_SAVED = {
  unknown_item: "the gateway does not have this item",
  not_granted: "this phone is not allowed to review",
  idempotency_conflict: "it clashed with an earlier request",
};

const view = document.getElementById("view");
const title = document.getElementById("title");
const back = document.getElementById("back");

const runItems = new Map(); // run_id -> items
let filter = "todo";
let triage = null; // { runId, list, index, tags, lockedUntil }
let renderSerial = 0;

// --- small helpers ------------------------------------------------------------------------------------------------

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "text") node.textContent = value;
    else if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value);
  }
  node.append(...children.filter(Boolean));
  return node;
}

const key = (item) => `${item.library_id}/${item.sha256}`;
const mediaUrl = (item, variant) =>
  `/media/${encodeURIComponent(item.library_id)}/${encodeURIComponent(item.sha256)}/${variant}`;

function runName(runId) {
  const match = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}_(.*)$/.exec(runId);
  if (!match) return runId;
  const [, year, month, day, hour, minute, name] = match;
  const when = new Date(year, month - 1, day, hour, minute);
  const label = when.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return `${label} · ${name}`;
}

let toastTimer = 0;
function toast(message) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 2500);
}

class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "X-Review-Gateway": "1", "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, data.error || "failed");
  return data;
}

// --- decisions not yet accepted by the gateway --------------------------------------------------------------------
// Kept on the phone and resent with the same idempotency key, so a dropped connection loses nothing. Storage is
// shared by every tab: it is re-read for each change and never overwritten with one tab's older list. A decision
// the gateway will not take is moved to a "not saved" list that stays until the owner deals with it.

const memory = new Map(); // what was last read or written, used if storage becomes unusable
let storageBroken = false;
let sending = false;
let retryTimer = 0;
let retryDelay = 2000;

function readList(name) {
  if (!storageBroken) {
    try {
      const value = JSON.parse(localStorage.getItem(name) || "[]");
      if (Array.isArray(value)) memory.set(name, value);
    } catch {
      storageBroken = true; // private browsing: the lists then live only as long as this page
    }
  }
  return memory.get(name) || [];
}

function changeList(name, change) {
  const next = change(readList(name));
  memory.set(name, next);
  try {
    localStorage.setItem(name, JSON.stringify(next));
  } catch {
    storageBroken = true;
  }
  showBadges();
}

const without = (idempotency) => (list) => list.filter((e) => e.idempotency_key !== idempotency);

function showBadges() {
  const waiting = readList(QUEUE_KEY).length;
  const badge = document.getElementById("unsent");
  badge.textContent = `${waiting} unsent`;
  badge.hidden = waiting === 0;
  const lost = readList(REJECTED_KEY).length;
  const button = document.getElementById("rejected");
  button.textContent = `${lost} not saved`;
  button.hidden = lost === 0;
}

function idempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function queueDecision(item, verdict, favorite, tags) {
  const entry = {
    library_id: item.library_id,
    sha256: item.sha256,
    verdict,
    favorite,
    tags,
    idempotency_key: idempotencyKey(),
  };
  changeList(REJECTED_KEY, (list) => list.filter((e) => key(e) !== key(item)));
  changeList(QUEUE_KEY, (list) => [...list, entry]);
  item.decision = { verdict, favorite, tags };
  item.state = "unsent";
  item.reason_code = null;
  flush();
}

function findItem(wanted) {
  const found = [];
  for (const items of runItems.values()) found.push(...items.filter((i) => key(i) === wanted));
  if (triage) found.push(...triage.list.filter((i) => key(i) === wanted));
  return found;
}

async function send(entry) {
  const { reason, ...body } = entry;
  const { state } = await api("/api/decisions", body);
  if (!ANSWERS.has(state)) throw new Error("unreadable reply"); // keep it and try again
  return state;
}

async function flush() {
  if (sending) return;
  sending = true;
  clearTimeout(retryTimer);
  try {
    let entry;
    while ((entry = readList(QUEUE_KEY)[0])) {
      let state;
      let reason = null;
      try {
        state = await send(entry);
      } catch (error) {
        if (error.status === 401) {
          showPairing();
          return;
        }
        if (!(error instanceof ApiError) || error.status >= 500 || error.status === 429) {
          retryTimer = setTimeout(flush, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 30000);
          return;
        }
        state = "rejected";
        reason = error.code;
        const lost = { ...entry, reason };
        changeList(REJECTED_KEY, (list) => [...without(lost.idempotency_key)(list), lost]);
        toast("A decision was not saved");
      }
      const sent = entry.idempotency_key;
      changeList(QUEUE_KEY, without(sent));
      retryDelay = 2000;
      const target = key(entry);
      if (!readList(QUEUE_KEY).some((e) => key(e) === target)) {
        for (const item of findItem(target)) {
          item.state = state;
          item.reason_code = reason;
        }
        updateTriageStatus();
      }
    }
  } finally {
    sending = false;
  }
}

function overlayUnsent(items) {
  const decisionOf = (e) => ({ verdict: e.verdict, favorite: e.favorite, tags: e.tags });
  for (const entry of readList(REJECTED_KEY)) {
    for (const item of items.filter((i) => key(i) === key(entry) && i.state === "undecided")) {
      item.decision = decisionOf(entry);
      item.state = "rejected";
      item.reason_code = entry.reason;
    }
  }
  for (const entry of readList(QUEUE_KEY)) {
    for (const item of items.filter((i) => key(i) === key(entry))) {
      item.decision = decisionOf(entry);
      item.state = "unsent";
      item.reason_code = null;
    }
  }
  return items;
}

function showRejected() {
  const retry = (entry) => {
    const { reason, ...again } = entry;
    changeList(REJECTED_KEY, without(entry.idempotency_key));
    changeList(QUEUE_KEY, (list) => [...list, again]);
    flush();
    showRejected();
  };
  const dismiss = (entry) => {
    changeList(REJECTED_KEY, without(entry.idempotency_key));
    showRejected();
  };
  const rows = readList(REJECTED_KEY).map((entry) => {
    const choice = entry.favorite ? "Favorite" : entry.verdict === "keep" ? "Keep" : "Delete";
    return el("section", { class: "run" }, [
      el("h2", { text: `${choice} was not saved` }),
      el("p", { class: "muted", text: NOT_SAVED[entry.reason] || "the gateway did not accept it" }),
      el("div", { class: "covers" }, [el("img", { src: mediaUrl(entry, "thumb"), alt: "" })]),
      el("div", { class: "tools" }, [
        el("button", { type: "button", class: "primary", text: "Try again", onclick: () => retry(entry) }),
        el("button", { type: "button", text: "Dismiss", onclick: () => dismiss(entry) }),
      ]),
    ]);
  });
  show("Not saved", true, ...(rows.length ? rows : [el("p", { class: "muted", text: "Nothing is waiting." })]));
}

async function loadRun(runId) {
  const data = await api(`/api/runs/${encodeURIComponent(runId)}`);
  const items = overlayUnsent(data.items);
  runItems.set(runId, items);
  return items;
}

// --- views --------------------------------------------------------------------------------------------------------

function show(heading, canGoBack, ...nodes) {
  title.textContent = heading;
  back.hidden = !canGoBack;
  view.replaceChildren(...nodes);
}

function showPairing() {
  if (view.querySelector(".pair")) return; // never wipe a code that is being typed
  triage = null;
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

function countChip(count, label, kind = "") {
  return count ? el("span", { class: `chip ${kind}`, text: `${count} ${label}` }) : null;
}

function runCard(run) {
  const covers = el(
    "div",
    { class: "covers" },
    run.covers.map((cover) =>
      el("img", { src: mediaUrl(cover, "thumb"), loading: "lazy", decoding: "async", alt: "" }),
    ),
  );
  const open = () => (location.hash = `#/run/${encodeURIComponent(run.run_id)}`);
  const waiting = run.undecided + run.refused; // a refused decision has to be made again
  const review = waiting
    ? el("button", {
        type: "button",
        class: "open primary",
        text: `Review ${waiting}`,
        onclick: (event) => {
          event.stopPropagation();
          filter = "todo";
          location.hash = `#/triage/${encodeURIComponent(run.run_id)}`;
        },
      })
    : null;
  return el("section", { class: "run", tabindex: "0", onclick: open }, [
    el("h2", { text: runName(run.run_id) }),
    el("div", { class: "counts" }, [
      countChip(waiting, "to review", "todo"),
      countChip(run.keep, "kept"),
      countChip(run.favorite, "favorite"),
      countChip(run.delete, "deleted"),
      countChip(run.pending, "waiting for PC"),
      countChip(run.applied, "applied"),
      countChip(run.refused, "refused", "refused"),
    ]),
    covers,
    review,
  ]);
}

const needsReview = (item) => ["undecided", "refused", "rejected"].includes(item.state);

async function showInbox(serial) {
  const { runs } = await api("/api/runs");
  if (serial !== renderSerial) return;
  const content = runs.length
    ? runs.map(runCard)
    : [el("p", { class: "muted", text: "Nothing to review yet. Items appear after the PC syncs." })];
  show("Review", false, ...content);
}

const STATE_BADGES = { unsent: "…", pending: "⏳", applied: "✓", refused: "!", rejected: "!" };

function tile(runId, item) {
  const decision = item.decision;
  const classes = ["tile"];
  if (decision) classes.push(decision.favorite ? "favorite" : decision.verdict);
  const label = decision ? `${decision.verdict}, ${item.state}` : "not decided";
  return el(
    "button",
    {
      type: "button",
      class: classes.join(" "),
      "aria-label": `${item.kind}, ${label}`,
      onclick: () => (location.hash = `#/triage/${encodeURIComponent(runId)}/${item.library_id}`),
    },
    [
      el("img", { src: mediaUrl(item, "thumb"), loading: "lazy", decoding: "async", alt: "" }),
      item.kind === "video" ? el("span", { class: "badge play", text: "▶" }) : null,
      STATE_BADGES[item.state]
        ? el("span", { class: `badge state ${item.state}`, text: STATE_BADGES[item.state] })
        : null,
    ],
  );
}

function renderGrid(runId) {
  const items = runItems.get(runId) || [];
  const todo = items.filter(needsReview);
  const shown = filter === "todo" && todo.length ? todo : items;
  const toggle = (value, text) =>
    el("button", {
      type: "button",
      text,
      "aria-pressed": String(value === (shown === todo ? "todo" : "all")),
      onclick: () => {
        filter = value;
        renderGrid(runId);
      },
    });
  show(
    runName(runId),
    true,
    el("div", { class: "tools" }, [
      toggle("todo", `To review (${todo.length})`),
      toggle("all", `All (${items.length})`),
      el("span", { class: "grow" }),
      items.length
        ? el("button", {
            type: "button",
            class: "primary",
            text: "Review",
            onclick: () => (location.hash = `#/triage/${encodeURIComponent(runId)}`),
          })
        : null,
    ]),
    items.length
      ? el("div", { class: "grid" }, shown.map((item) => tile(runId, item)))
      : el("p", { class: "muted", text: "Nothing here any more." }),
  );
}

async function showRun(runId, serial) {
  await loadRun(runId);
  if (serial === renderSerial) renderGrid(runId);
}

// --- triage -------------------------------------------------------------------------------------------------------

async function showTriage(runId, libraryId, serial) {
  const items = await loadRun(runId);
  if (serial !== renderSerial) return;
  const todo = items.filter(needsReview);
  const useTodo = filter === "todo" && todo.length && (!libraryId || todo.some((i) => i.library_id === libraryId));
  const list = useTodo ? todo : items;
  if (!list.length) {
    renderGrid(runId);
    return;
  }
  const index = Math.max(0, list.findIndex((item) => item.library_id === libraryId));
  triage = { runId, list, index, tags: new Set(), lockedUntil: 0 };
  renderItem();
}

function statusText(item) {
  if (!item.decision) return "Not decided";
  const choice = item.decision.favorite ? "Favorite" : item.decision.verdict === "keep" ? "Keep" : "Delete";
  if (item.state === "unsent") return `${choice} · sending…`;
  if (item.state === "pending") return `${choice} · waiting for PC`;
  if (item.state === "refused") return `${choice} refused: ${REASONS[item.reason_code] || "no reason given"}`;
  if (item.state === "rejected") return `${choice} not saved: ${NOT_SAVED[item.reason_code] || "not accepted"}`;
  return `${choice} · applied`;
}

function updateTriageStatus() {
  const node = document.getElementById("state");
  if (!triage || !node) return;
  const item = triage.list[triage.index];
  node.textContent = statusText(item);
  node.className = item.state === "refused" || item.state === "rejected" ? "refused" : "";
}

function mediaElement(item) {
  const poster = mediaUrl(item, "thumb");
  if (item.kind === "video") {
    const variant = item.variants.includes("video") ? "video" : "original";
    const video = el("video", { src: mediaUrl(item, variant), poster, controls: "", loop: "", playsinline: "", preload: "auto" });
    video.muted = true;
    video.autoplay = true;
    return video;
  }
  const variant = item.variants.includes("preview") ? "preview" : "original";
  return el("img", { src: mediaUrl(item, variant), alt: "", draggable: "false" });
}

function infoPanel(item) {
  const display = item.display;
  const line = (name, value) => (value ? el("p", { text: `${name}: ${value}` }) : null);
  return el("div", { class: "info", hidden: "" }, [
    line("Model", display.model),
    line("Workflow", display.workflow),
    line("Seed", display.seed),
    line("Duration", item.duration_s ? `${item.duration_s} s` : ""),
    line("Prompt", display.prompt_excerpt),
    el("a", { href: mediaUrl(item, "original"), target: "_blank", rel: "noopener", text: "Open full size" }),
  ]);
}

function attachSwipe(stage, media, info) {
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
    else if (Math.abs(dx) < 8 && Math.abs(dy) < 8 && media.tagName === "IMG") info.hidden = !info.hidden;
  });
  stage.addEventListener("pointercancel", () => {
    pointers = Math.max(0, pointers - 1);
    reset();
  });
}

function renderItem() {
  const { list, index, runId } = triage;
  const item = list[index];
  triage.tags = new Set(item.decision ? item.decision.tags : []);
  history.replaceState(null, "", `#/triage/${encodeURIComponent(runId)}/${item.library_id}`);

  const media = mediaElement(item);
  const info = infoPanel(item);
  const stage = el("div", { class: "stage" }, [media, info]);
  attachSwipe(stage, media, info);

  const tags = el(
    "div",
    { class: "tags", role: "group", "aria-label": "Reason tags" },
    TAGS.map(([value, text]) => {
      const button = el("button", { type: "button", text, "aria-pressed": String(triage.tags.has(value)) });
      button.addEventListener("click", () => {
        if (!triage.tags.delete(value)) triage.tags.add(value);
        button.setAttribute("aria-pressed", String(triage.tags.has(value)));
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
    if (triage !== current || current.list[current.index] !== item) return;
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
        el("button", { type: "button", text: `${index + 1} / ${list.length} · info`, onclick: () => (info.hidden = !info.hidden) }),
      ]),
      stage,
      tags,
      el("div", { class: "actions" }, [
        previous,
        ...choices,
        next,
      ]),
    ]),
  );
  updateTriageStatus();
  for (const ahead of list.slice(index + 1, index + 3)) {
    new Image().src = mediaUrl(ahead, ahead.kind === "image" && ahead.variants.includes("preview") ? "preview" : "thumb");
  }
}

function step(direction) {
  const index = triage.index + direction;
  if (index < 0 || index >= triage.list.length) return;
  triage.index = index;
  renderItem();
}

function decide(verdict, favorite) {
  if (!triage || Date.now() < triage.lockedUntil) return;
  if (!triage.ready) {
    toast("Still loading");
    return;
  }
  const item = triage.list[triage.index];
  const tags = [...triage.tags].filter((tag) => !(verdict === "delete" && tag === "needs_fix"));
  queueDecision(item, verdict, favorite, tags);
  if (navigator.vibrate) navigator.vibrate(15);
  toast(favorite ? "★ Favorite" : verdict === "keep" ? "Kept" : "Deleted");
  if (triage.index + 1 < triage.list.length) {
    triage.index += 1;
    renderItem();
    triage.lockedUntil = Date.now() + 250; // a double tap must not decide the next item unseen
  } else {
    toast("End of this run");
    location.hash = `#/run/${encodeURIComponent(triage.runId)}`;
  }
}

// --- routing ------------------------------------------------------------------------------------------------------

async function route() {
  const serial = ++renderSerial;
  const [, page, run, libraryId] = location.hash.split("/");
  triage = null;
  try {
    if (page === "triage" && run) await showTriage(decodeURIComponent(run), libraryId, serial);
    else if (page === "run" && run) await showRun(decodeURIComponent(run), serial);
    else if (page === "rejected") showRejected();
    else await showInbox(serial);
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

async function refresh() {
  if (document.hidden) return;
  flush();
  if (view.querySelector(".pair")) return;
  const [, page, run] = location.hash.split("/");
  const serial = renderSerial;
  const scroll = window.scrollY;
  try {
    if (triage) {
      const fresh = await loadRun(triage.runId);
      if (serial !== renderSerial || !triage) return;
      const latest = new Map(fresh.map((item) => [key(item), item]));
      for (const item of triage.list) {
        const found = latest.get(key(item));
        if (found) Object.assign(item, found);
      }
      updateTriageStatus();
    } else if (page === "run" && run) {
      await showRun(decodeURIComponent(run), serial);
      window.scrollTo(0, scroll);
    } else if (!page) {
      await showInbox(serial);
      window.scrollTo(0, scroll);
    }
  } catch (error) {
    if (error.status === 401) showPairing();
  }
}

back.addEventListener("click", () => {
  const [, page, run] = location.hash.split("/");
  location.hash = page === "triage" && run ? `#/run/${run}` : "";
});
window.addEventListener("hashchange", route);
window.addEventListener("online", () => flush());
window.addEventListener("storage", () => {
  showBadges();
  flush();
});
document.getElementById("rejected").addEventListener("click", () => (location.hash = "#/rejected"));
document.addEventListener("visibilitychange", refresh);
setInterval(refresh, REFRESH_MS);

showBadges();
flush();
route();
