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
  summary_changed: "the PC's summary changed",
  action_unavailable: "the PC cannot do this for this image",
  prepare_required: "the summary expired; ask again",
};
// RG-140 phone actions. The PC compiles and decides; the phone shows its summary, warnings and receipts as text.
const ACTIONS = [
  ["fix_face", "Fix face"],
  ["fix_hands", "Fix hands"],
  ["fix_both", "Fix both"],
  ["more_like_this", "More like this"],
  ["another_model", "Another model"],
  ["aspect_ratio", "Aspect ratio"],
  ["prompt_tweak", "Tweak prompt"],
  ["make_video", "Make video"],
];
// Slice 2. A picker action first asks the PC for its options; a words action asks the owner first.
const PICKERS = {
  another_model: "Choose a checkpoint on the PC. The image is run through it with img2img.",
  aspect_ratio: "Choose a shape. Outpainting adds space around the image; every original pixel is kept.",
};
const WORDS = {
  prompt_tweak: { required: true, hint: "Words added to this image's prompt, then img2img of the image.", placeholder: "smiling, golden hour" },
  make_video: { required: false, hint: "What should move? Leave it empty to use the image's own prompt.", placeholder: "she turns towards the window" },
};
// PHONE-FAST: actions that replace the image (the gateway holds the same list). The original then counts as reviewed
// until the result arrives and one of the two is kept.
const REWORK = new Set(["fix_face", "fix_hands", "fix_both", "another_model", "aspect_ratio"]);
const SLICE_TWO = new Set(["another_model", "aspect_ratio", "prompt_tweak", "make_video"]);
const DETAILS = {
  not_an_image: "only images can be fixed",
  source_changed: "the image changed on the PC",
  provenance_unverified: "the PC cannot find the job that made this image",
  recipe_not_variable: "this image cannot be re-run with new seeds (it was made from another image, such as a face or hands fix)",
  model_unavailable: "the checkpoint is not available",
  model_family_refused: "the checkpoint cannot run this fix",
  adetailer_unavailable: "ADetailer is not available; connect Forge on the PC",
  detector_unavailable: "Forge lists no detector for this pass",
  operation_unsupported: "the backend cannot run this",
  choice_unavailable: "that option is not on the PC any more; choose again",
  no_change: "that is what the image already has",
  prompt_required: "there are no words to use for the prompt",
  size_unsupported: "the new canvas would be too large",
  video_unavailable: "the PC has no approved Make Video workflow",
  app_busy: "StableNew was busy; try again",
  app_shutting_down: "StableNew is shutting down",
  compile_failed: "the PC could not prepare it",
};
const ACTION_POLL_MS = 1000;
const PREFETCH = 4;
// PHONE-FAST: the last decision stays on the phone this long, so it can be undone.
const UNDO_MS = 8000;
const ACTION_WAIT_MS = 10 * 60 * 1000;
let scopes = null; // the session's grants, read once
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

// A group is a named batch ("batch:<id>", N5) or an output run folder; batch names come from the server.
const groupNames = new Map();

// PHONE-FAST: the review sections, by the category id the PC sends. Evaluation sittings are not a section here.
const SECTIONS = {
  pipeline: "Pipeline runs",
  learning: "Learning runs",
  reprocess: "Reprocess and rework",
  video: "Movie clips",
  testing: "Test runs",
  other: "Other",
};
const SEEN_KEY = "rg.seen"; // section -> the gateway's time when this phone last opened it
const COUNT_KEY = "rg.count"; // "new" shows what arrived since then; otherwise what is left to review
const isStream = (runId) => runId === "all" || runId.startsWith("all:");
let section = ""; // the section being looked in, where "back" from one of its runs returns to

// Per-phone settings; a phone without storage just keeps the default.
function readSetting(name, fallback) {
  try {
    return JSON.parse(localStorage.getItem(name)) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeSetting(name, value) {
  try {
    localStorage.setItem(name, JSON.stringify(value));
  } catch {
    /* private browsing */
  }
}

function runName(runId) {
  if (isStream(runId)) return runId === "all" ? "To review" : `To review: ${SECTIONS[runId.slice(4)] || "Other"}`;
  if (runId.startsWith("batch:")) return groupNames.get(runId) || "Batch";
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

function queueDecision(item, verdict, favorite, tags, heldUntil = 0) {
  const entry = {
    library_id: item.library_id,
    sha256: item.sha256,
    verdict,
    favorite,
    tags,
    idempotency_key: idempotencyKey(),
    ...(heldUntil ? { held_until: heldUntil } : {}),
  };
  changeList(REJECTED_KEY, (list) => list.filter((e) => key(e) !== key(item)));
  changeList(QUEUE_KEY, (list) => [...list, entry]);
  item.decision = { verdict, favorite, tags };
  item.state = "unsent";
  item.reason_code = null;
  flush();
  return entry.idempotency_key;
}

// --- undo (PHONE-FAST) --------------------------------------------------------------------------------------------
// The gateway has no "undecide", so the last decision (one item, or a compare's pair) is held on the phone for a few
// seconds. The next decision, leaving the page or the time running out sends it.

let undoable = null; // { keys, before, at, timer }

function decideUndoably(choices) {
  releaseHeld();
  const until = Date.now() + UNDO_MS;
  const keys = [];
  const before = [];
  for (const [item, verdict, favorite, tags] of choices) {
    const copies = [item, ...findItem(key(item))];
    before.push(...copies.map((copy) => [copy, copy.decision, copy.state, copy.reason_code]));
    keys.push(queueDecision(item, verdict, favorite, tags, until));
    for (const copy of copies) Object.assign(copy, { decision: item.decision, state: item.state, reason_code: null });
  }
  const at = triage ? { runId: triage.runId, libraryId: triage.list[triage.index].library_id } : null;
  undoable = { keys, before, at, timer: setTimeout(releaseHeld, UNDO_MS) };
  showUndo(true);
}

function releaseHeld() {
  if (undoable) clearTimeout(undoable.timer);
  undoable = null;
  showUndo(false);
  changeList(QUEUE_KEY, (list) => list.map(({ held_until, ...entry }) => entry));
  flush();
}

function undo() {
  if (!undoable) return;
  const { keys, before, at, timer } = undoable;
  clearTimeout(timer);
  undoable = null;
  showUndo(false);
  changeList(QUEUE_KEY, (list) => list.filter((entry) => !keys.includes(entry.idempotency_key)));
  for (const [copy, decision, state, reason] of before) {
    Object.assign(copy, { decision, state, reason_code: reason });
  }
  toast("Undone");
  flush();
  const index = triage && at ? triage.list.findIndex((item) => item.library_id === at.libraryId) : -1;
  if (index >= 0 && triage.runId === at.runId) {
    triage.index = index;
    renderItem();
  } else if (at) {
    location.hash = `#/triage/${encodeURIComponent(at.runId)}/${at.libraryId}`;
  }
}

function showUndo(visible) {
  let button = document.getElementById("undo");
  if (!button) {
    if (!visible) return;
    button = el("button", { type: "button", id: "undo", text: "Undo", onclick: undo });
    document.body.append(button);
  }
  button.hidden = !visible;
}

// "Keep the rest" and "Delete this run": one ordinary decision per item, never for one already sent for rework.
function decideAll(runId, items, verdict) {
  releaseHeld();
  for (const item of items) {
    const tags = item.decision ? item.decision.tags : [];
    queueDecision(item, verdict, false, verdict === "keep" ? tags : tags.filter((tag) => tag !== "needs_fix"));
  }
  toast(`${items.length} ${verdict === "keep" ? "kept" : "deleted"}`);
  renderGrid(runId);
}

const isKept = (item) => Boolean(item.decision) && item.decision.verdict === "keep" && item.state !== "refused";
const isDeleted = (item) => Boolean(item.decision) && item.decision.verdict === "delete" && item.state !== "refused";
const deletable = (item) => !isKept(item) && !isDeleted(item) && item.state !== "rework";

function confirmDeleteRun(runId, items) {
  const kept = items.filter(isKept).length;
  const reworked = items.filter((item) => item.state === "rework").length;
  const stay = [kept ? `${kept} kept` : "", reworked ? `${reworked} in rework` : ""].filter(Boolean).join(" and ");
  const targets = items.filter(deletable);
  sheet(
    el("h2", { text: `Delete ${targets.length}?` }),
    el("p", { text: `The files go to the PC's archive.${stay ? ` ${stay} stay.` : ""}` }),
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", text: "Cancel", onclick: closeSheet }),
      el("button", {
        type: "button",
        class: "primary",
        text: `Delete ${targets.length}`,
        onclick: () => {
          closeSheet();
          decideAll(runId, targets, "delete");
        },
      }),
    ]),
  );
}

function findItem(wanted) {
  const found = [];
  for (const items of runItems.values()) found.push(...items.filter((i) => key(i) === wanted));
  if (triage) found.push(...triage.list.filter((i) => key(i) === wanted));
  return found;
}

async function send(entry) {
  const { reason, held_until, ...body } = entry;
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
      const wait = (entry.held_until || 0) - Date.now();
      if (wait > 0) {
        retryTimer = setTimeout(flush, wait); // still undoable; what follows it waits too, to keep the order
        return;
      }
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
  if (data.name) groupNames.set(runId, data.name);
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
      scopes = null;
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
  if (run.kind === "batch" && run.name) groupNames.set(run.run_id, run.name);
  return el("section", { class: "run", tabindex: "0", "data-anchor": run.run_id, onclick: open }, [
    el("h2", { text: runName(run.run_id) }),
    run.kind === "batch" ? el("p", { class: "muted", text: "Batch" }) : null,
    el("div", { class: "counts" }, [
      countChip(waiting, "to review", "todo"),
      countChip(run.keep, "kept"),
      countChip(run.favorite, "favorite"),
      countChip(run.delete, "deleted"),
      countChip(run.rework, "in rework"),
      countChip(run.pending, "waiting for PC"),
      countChip(run.applied, "applied"),
      countChip(run.refused, "refused", "refused"),
    ]),
    covers,
    review,
  ]);
}

const needsReview = (item) => ["undecided", "refused", "rejected"].includes(item.state);

function reviewAllButton(count, runId) {
  if (!count) return null;
  const open = () => {
    filter = "todo";
    location.hash = `#/triage/${runId}`;
  };
  return el("button", { type: "button", class: "primary wide", text: `Review all (${count})`, onclick: open });
}

function sectionRow(entry, countNew) {
  const count = countNew ? entry.new : entry.unreviewed;
  const label = SECTIONS[entry.id] || "Other";
  return el(
    "button",
    {
      type: "button",
      class: "folder",
      "data-anchor": entry.id,
      "aria-label": `${label}, ${count} ${countNew ? "new" : "to review"}`,
      onclick: () => (location.hash = `#/section/${entry.id}`),
    },
    [
      el("span", { class: "folder-icon", "aria-hidden": "true", text: "📁" }),
      el("span", { class: "folder-name", text: label }),
      count ? el("span", { class: "chip todo", text: String(count) }) : null,
    ],
  );
}

// The home screen: one row per source of outputs. The top row is where other review tabs sit.
async function showHome(serial) {
  const seen = readSetting(SEEN_KEY, {});
  const query = new URLSearchParams(seen).toString();
  const { sections } = await api(`/api/sections${query ? `?${query}` : ""}`);
  await loadScopes();
  const status = await api("/api/status").catch(() => null); // extra: the home screen shows without it
  if (serial !== renderSerial) return;
  const countNew = readSetting(COUNT_KEY, "todo") === "new";
  const counting = (value, text) =>
    el("button", {
      type: "button",
      text,
      "aria-pressed": String((value === "new") === countNew),
      onclick: () => {
        writeSetting(COUNT_KEY, value);
        route();
      },
    });
  const waiting = sections.reduce((sum, entry) => sum + entry.unreviewed, 0);
  const update = canUpdate()
    ? el("button", { type: "button", class: "pc-link", text: "Update the PC…", onclick: () => (location.hash = "#/update") })
    : null;
  const content = sections.length
    ? [
        el("div", { class: "tools counting" }, [counting("todo", "To review"), counting("new", "New since opened")]),
        ...sections.map((entry) => sectionRow(entry, countNew)),
      ]
    : [el("p", { class: "muted", text: "Nothing to review yet. Items appear after the PC syncs." })];
  show("Review", false, ...[...statusLines(status), reviewAllButton(waiting, "all"), ...content, update].filter(Boolean));
}

async function showSection(name, serial) {
  const { runs } = await api(`/api/runs?source=${encodeURIComponent(name)}`);
  const clock = await api("/api/status").catch(() => null);
  if (serial !== renderSerial) return;
  section = name;
  if (clock) writeSetting(SEEN_KEY, { ...readSetting(SEEN_KEY, {}), [name]: clock.now });
  const waiting = runs.reduce((sum, run) => sum + run.undecided + run.refused, 0);
  const content = runs.length ? runs.map(runCard) : [el("p", { class: "muted", text: "Nothing here any more." })];
  show(SECTIONS[name], true, ...[reviewAllButton(waiting, `all:${name}`), ...content].filter(Boolean));
}

const STATE_BADGES = { unsent: "…", pending: "⏳", applied: "✓", refused: "!", rejected: "!", rework: "↻" };

function tile(runId, item) {
  const decision = item.decision;
  const classes = ["tile"];
  if (decision) classes.push(decision.favorite ? "favorite" : decision.verdict);
  const label =
    item.state === "rework" ? "sent for rework" : decision ? `${decision.verdict}, ${item.state}` : "not decided";
  return el(
    "button",
    {
      type: "button",
      class: classes.join(" "),
      "data-anchor": item.library_id,
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
    items.some(needsReview) || items.some(deletable)
      ? el("div", { class: "tools bulk" }, [
          todo.length
            ? el("button", { type: "button", text: `Keep the rest (${todo.length})`, onclick: () => decideAll(runId, todo, "keep") })
            : null,
          el("span", { class: "grow" }),
          items.some(deletable)
            ? el("button", { type: "button", text: "Delete this run…", onclick: () => confirmDeleteRun(runId, items) })
            : null,
        ])
      : null,
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
  await loadScopes();
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
  if (item.state === "rework") return "Sent for rework";
  if (!item.decision) return item.compare ? "Rework result: which is better?" : "Not decided";
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
  const batch = item.batch;
  const cell = batch && batch.cell ? [batch.cell.pack, batch.cell.model].filter(Boolean).join(" · ") : "";
  return el("div", { class: "info", hidden: "" }, [
    line("Batch", batch ? batch.name : ""),
    line("Cell", cell),
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
  if (item.compare && needsReview(item)) return renderCompare(item);

  const media = mediaElement(item);
  const info = infoPanel(item);
  const stage = el("div", { class: "stage" }, [media, info]);
  attachSwipe(stage, media, info);

  const tags = el(
    "div",
    { class: "tags", role: "group", "aria-label": "Reason tags" },
    TAGS.map(([value, text]) => {
      const button = el("button", {
        type: "button",
        text,
        "data-tag": value,
        "aria-pressed": String(triage.tags.has(value)),
      });
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
      actionRow(item),
      el("div", { class: "actions" }, [
        previous,
        ...choices,
        next,
      ]),
    ]),
  );
  updateTriageStatus();
  prefetch(list.slice(index + 1, index + 1 + PREFETCH));
}

// --- compare a rework with its original (PHONE-FAST) --------------------------------------------------------------
// Three views, the phone's choice: side by side (tap one to see it alone), flip (tap or swipe) and a before/after
// slider. Picking keeps one and discards the other.
const COMPARE_KEY = "rg.compare";
const COMPARE_MODES = [
  ["side", "Side by side"],
  ["flip", "Flip"],
  ["slider", "Slider"],
];

function renderCompare(item) {
  const { list, index, runId } = triage;
  const original = item.compare;
  const current = triage;
  const sides = [
    ["Original", original],
    ["Rework", item],
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
    if (mode === "slider") {
      if (tap) slide(across(event));
    } else if (mode === "flip") {
      if (tap || swipe) showSide(1 - shown);
    } else if (tap && touched >= 0) {
      shown = touched;
      setMode("flip"); // one alone for a closer look; the saved view stays side by side
    }
  });

  const button = (className, text, onclick) =>
    el("button", { type: "button", class: className, text, "aria-label": text, onclick });
  const choices = [
    button("keep", "Keep original", () => pick(original, item)),
    button("keep", "Keep rework", () => pick(item, original)),
  ];
  const allow = () => {
    if (triage !== current || current.list[current.index] !== item) return;
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
  const info = infoPanel(item);
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
        el("button", { type: "button", text: `${index + 1} / ${list.length} · info`, onclick: () => (info.hidden = !info.hidden) }),
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

function pick(winner, loser) {
  if (!triage || Date.now() < triage.lockedUntil) return;
  if (!triage.ready) {
    toast("Still loading");
    return;
  }
  decideUndoably(
    [
      [winner, "keep"],
      [loser, "delete"],
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
  toast("Picked; the other goes to the archive");
  advance();
}

// Sent for rework: the item counts as reviewed at once; a refusal puts it back.
function markRework(item, sent) {
  for (const copy of [item, ...findItem(key(item))]) {
    if (sent && needsReview(copy)) {
      copy.before = copy.state;
      copy.state = "rework";
    } else if (!sent && copy.state === "rework" && copy.before) {
      copy.state = copy.before;
    }
  }
  updateTriageStatus();
}

function closeAfterRework(item) {
  closeSheet();
  if (triage && key(triage.list[triage.index]) === key(item) && item.state === "rework") advance();
}

// The next few phone renditions, held so the browser does not drop the requests. Originals are never fetched ahead.
let ahead = [];
function prefetch(items) {
  ahead = items.map((item) => {
    const image = new Image();
    image.src = mediaUrl(item, item.kind === "image" && item.variants.includes("preview") ? "preview" : "thumb");
    return image;
  });
}

// --- phone actions (RG-140) ---------------------------------------------------------------------------------------
// Two steps, both outbox requests: "prepare" asks the PC for a summary of exactly what it would queue; "Queue" sends
// "confirm" naming that summary. Nothing is queued until the PC admits it, and its receipt is shown.

async function loadScopes() {
  if (scopes === null) {
    try {
      scopes = (await api("/api/session")).scopes || [];
    } catch {
      return [];
    }
  }
  return scopes;
}

const canQueue = () => Array.isArray(scopes) && scopes.includes("queue");

// Asking for a fix says what is wrong with the image, so the matching reason tags are switched on (and a decision
// already made for it is resent with them).
const FIX_TAGS = { fix_face: ["face"], fix_hands: ["hands"], fix_both: ["face", "hands"] };

function addTags(item, wanted) {
  if (!triage || triage.list[triage.index] !== item) return;
  const before = triage.tags.size;
  for (const tag of wanted) triage.tags.add(tag);
  for (const button of document.querySelectorAll(".tags button[data-tag]")) {
    button.setAttribute("aria-pressed", String(triage.tags.has(button.dataset.tag)));
  }
  const decision = item.decision;
  if (triage.tags.size !== before && decision && decision.verdict === "keep") {
    queueDecision(item, "keep", decision.favorite, [...triage.tags]);
    updateTriageStatus();
  }
}

function actionRow(item) {
  if (item.kind !== "image" || !canQueue()) return null;
  return el(
    "div",
    { class: "fixes", role: "group", "aria-label": "Ask the PC" },
    ACTIONS.map(([action, text]) =>
      el("button", {
        type: "button",
        text,
        onclick: () => {
          if (FIX_TAGS[action]) addTags(item, FIX_TAGS[action]);
          if (WORDS[action]) askWords(item, action);
          else openAction(item, action);
        },
      }),
    ),
  );
}

const actionLabel = (action) => Object.fromEntries(ACTIONS)[action];

function askWords(item, action) {
  const { required, hint, placeholder } = WORDS[action];
  const label = actionLabel(action);
  const input = el("input", { maxlength: "200", placeholder, "aria-label": label, autocomplete: "off" });
  const error = el("p", { class: "error", role: "alert" });
  const go = () => {
    // One line of plain text: the PC refuses control characters, so they never leave the phone.
    const text = input.value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, 200);
    if (required && !text) {
      error.textContent = "Type a few words first.";
      return;
    }
    openAction(item, action, text ? { text } : {});
  };
  input.addEventListener("keydown", (event) => event.key === "Enter" && go());
  sheet(
    el("h2", { text: label }),
    el("p", { class: "muted", text: hint }),
    input,
    error,
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", text: "Cancel", onclick: closeSheet }),
      el("button", { type: "button", class: "primary", text: "Ask the PC", onclick: go }),
    ]),
  );
  input.focus();
}

function showChoices(item, action, choices) {
  const buttons = choices.items.map((choice) =>
    el("button", {
      type: "button",
      text: choice.current ? `${choice.label} (this image)` : choice.label,
      "aria-pressed": String(choice.id === choices.selected),
      onclick: () => openAction(item, action, { choice: choice.id }),
    }),
  );
  return sheet(
    el("h2", { text: actionLabel(action) }),
    el("p", { class: "muted", text: PICKERS[action] }),
    el("div", { class: "choices", role: "group", "aria-label": "Options" }, buttons),
    el("div", { class: "sheet-actions" }, [el("button", { type: "button", text: "Cancel", onclick: closeSheet })]),
  );
}

function closeSheet() {
  const sheet = document.getElementById("sheet");
  if (sheet) sheet.remove();
}

function sheet(...nodes) {
  closeSheet();
  const node = el("div", { id: "sheet", class: "sheet", role: "dialog", "aria-modal": "true" }, [
    el("div", { class: "sheet-body" }, nodes),
  ]);
  node.addEventListener("click", (event) => {
    if (event.target === node) closeSheet(); // a tap outside the sheet closes it
  });
  document.body.append(node);
  return node;
}

function waitFor(recordId, alive) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      if (!alive()) return resolve(null);
      try {
        const answer = await api(`/api/actions/${recordId}`);
        if (answer.state !== "pending") return resolve(answer);
      } catch (error) {
        if (error.status === 401 || error.status === 403 || error.status === 404) return reject(error);
      }
      if (Date.now() - started > ACTION_WAIT_MS) return resolve({ state: "pending" });
      setTimeout(tick, ACTION_POLL_MS);
    };
    tick();
  });
}

function refusalText(answer) {
  // A PC from before RG-140 slice 2 knows only the first four actions: it refuses the others as invalid.
  if (answer.reason_code === "invalid_record" && SLICE_TWO.has(answer.action)) {
    return "StableNew on the PC does not offer this action yet. Update it and try again.";
  }
  const reason = REASONS[answer.reason_code] || "no reason given";
  const detail = answer.receipt && DETAILS[answer.receipt.detail];
  return detail ? `${reason}: ${detail}.` : `${reason}.`;
}

function warningBlock(warning) {
  return el("div", { class: "warning" }, [
    el("p", { class: "warning-title", text: `⚠ ${warning.title}` }),
    warning.why ? el("p", { text: warning.why }) : null,
    warning.fix ? el("p", { class: "muted", text: warning.fix }) : null,
  ]);
}

function summaryView(summary) {
  const where = summary.queue_position === "next" ? "runs next" : "joins the end of the queue";
  const jobs = `${summary.job_count} job${summary.job_count === 1 ? "" : "s"}, ${where}`;
  return [
    el("h2", { text: summary.title }),
    ...summary.lines.map((line) => el("p", { text: line })),
    el("p", { class: "muted", text: jobs }),
    ...summary.warnings.map(warningBlock),
  ];
}

// One request at a time per sheet; the same idempotency key is resent until the gateway answers.
async function sendAction(body) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await api("/api/actions", body);
    } catch (error) {
      if (error.status || attempt >= 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
}

async function openAction(item, action, extra = {}) {
  const label = actionLabel(action);
  const asking = PICKERS[action] && !extra.choice ? "Asking the PC for its options…" : "Asking the PC for a summary…";
  const node = sheet(el("h2", { text: label }), el("p", { class: "muted", text: asking }));
  const alive = () => document.getElementById("sheet") === node;
  const cancel = () =>
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", class: "primary", text: "Close", onclick: closeSheet }),
    ]);
  const fail = (text) => alive() && sheet(el("h2", { text: label }), el("p", { class: "error", text }), cancel());
  const params = { step: "prepare", ...extra };
  if (action === "more_like_this") params.count = 4;
  const body = {
    library_id: item.library_id,
    sha256: item.sha256,
    action,
    params,
    idempotency_key: idempotencyKey(),
  };
  try {
    const { record_id: recordId } = await sendAction(body);
    const answer = await waitFor(recordId, alive);
    if (answer) showAnswer(item, action, recordId, answer, cancel, fail);
  } catch (error) {
    fail(error.status === 429 ? "Too many requests from this phone for now." : `Not sent: ${error.code || "no connection"}.`);
  }
}

function showAnswer(item, action, recordId, answer, cancel, fail) {
  const label = actionLabel(action);
  if (answer.state === "pending") return fail("The PC has not answered yet. It may be off; ask again later.");
  const summary = answer.receipt && answer.receipt.action_summary;
  const choices = answer.receipt && answer.receipt.choices;
  if (answer.state === "applied" && choices && !summary) return showChoices(item, action, choices);
  if (answer.state === "refused" && REWORK.has(action)) markRework(item, false);
  if (answer.state === "refused" && !(answer.reason_code === "summary_changed" && summary)) {
    return fail(`Not possible: ${refusalText(answer)}`);
  }
  if (answer.step === "confirm" && answer.state === "applied") {
    const ids = answer.receipt.job_ids || [];
    const where = summary && summary.queue_position === "next" ? "It runs next." : "It joins the queue.";
    return sheet(
      el("h2", { text: `${label}: queued` }),
      el("p", { text: `${ids.length} job${ids.length === 1 ? "" : "s"} admitted on the PC. ${where}` }),
      el("p", {
        class: "muted",
        text: REWORK.has(action)
          ? "This image counts as reviewed. When the result arrives, compare the two and keep one."
          : "The result appears in the inbox once it is published.",
      }),
      el("div", { class: "sheet-actions" }, [
        el("button", { type: "button", class: "primary", text: "Close", onclick: () => closeAfterRework(item) }),
      ]),
    );
  }
  const node = sheet(
    answer.state === "refused" ? el("p", { class: "error", text: "The PC's summary changed. Check it again." }) : null,
    ...summaryView(summary),
    el("div", { class: "sheet-actions" }, [
      el("button", { type: "button", text: "Cancel", onclick: closeSheet }),
      choices ? el("button", { type: "button", text: "Change", onclick: () => showChoices(item, action, choices) }) : null,
      el("button", {
        type: "button",
        class: "primary",
        text: "Queue",
        onclick: async (event) => {
          event.currentTarget.disabled = true;
          const alive = () => document.getElementById("sheet") === node;
          // This sheet replaced the one the request started on, so a refusal is shown while this one is open.
          const failHere = (text) => alive() && sheet(el("h2", { text: label }), el("p", { class: "error", text }), cancel());
          try {
            const sent = await sendAction({
              library_id: item.library_id,
              sha256: item.sha256,
              action,
              params: { step: "confirm", prepared_record: recordId, summary_revision: summary.revision },
              idempotency_key: idempotencyKey(),
            });
            if (REWORK.has(action)) markRework(item, true);
            node.querySelector(".sheet-actions").replaceChildren(
              el("p", { class: "muted", text: "Waiting for the PC…" }),
              el("button", { type: "button", text: "Close", onclick: () => closeAfterRework(item) }),
            );
            const result = await waitFor(sent.record_id, alive);
            if (result) showAnswer(item, action, sent.record_id, result, cancel, failHere);
          } catch (error) {
            failHere(`Not sent: ${error.code || "no connection"}.`);
          }
        },
      }),
    ]),
  );
  return node;
}

// --- remote update (LAUNCH-UPDATE-2) ------------------------------------------------------------------------------
// Only on a phone paired from the desktop's "Pair for remote update" offer. The phone sends the origin/main commit
// it shows; the PC checks it against its own fetch, waits for the running job, updates, restarts and answers.

const UPDATE_REASONS = {
  remote_update_disabled: "remote update is switched off on the PC (Update dialog, Allow remote update)",
  update_unavailable: "remote update is not available on the PC",
  update_in_progress: "an update is already in progress",
  rate_limited: "the PC updated less than 10 minutes ago",
  request_expired: "the PC saw the request more than an hour after the tap",
  invalid_request: "the request did not name a valid commit",
  wrong_branch: "the PC's checkout is not on main",
  wrong_upstream: "the PC's main does not track origin/main",
  origin_mismatch: "the PC's origin is not the expected repository",
  dirty_checkout: "the PC's checkout has uncommitted changes",
  fetch_failed: "the PC could not fetch origin",
  git_failed: "Git failed on the PC",
  target_moved: "origin/main moved since this screen; check again",
  already_current: "the PC is already up to date",
  not_fast_forward: "origin/main is not a fast-forward of the PC's main",
  not_github_signed:
    "the newest commit on main is not a merge GitHub signed, so the PC did not install it; " +
    "merge the change through a pull request on GitHub, then check again",
  github_unavailable:
    "the PC could not ask GitHub whether it signed the new commit; nothing was changed, try again in a few minutes",
  environment_drift: "the update needs packages the PC does not have; nothing was installed",
  queue_unavailable: "the PC's queue could not be reached",
  busy_timeout: "the running job did not finish within an hour; the queue continues",
  updater_failed: "the updater could not be started",
  updater_lost: "the updater stopped without a result; check the PC at the desk",
  old_app_did_not_exit: "StableNew did not exit, so nothing was changed",
  checkout_changed: "the checkout changed after the check; it was left as it was",
  merge_failed: "the fast-forward failed; the checkout was left as it was",
  rolled_back: "the new version did not start; the PC went back to the previous version",
  rollback_failed: "the new version did not start and going back failed; fix it at the desk",
};
const NOT_SENT = {
  status_changed: "the PC reported a different origin/main; check again",
  update_pending: "the PC is already handling an update request",
  not_granted: "this phone is not allowed to update the PC",
};
const UPDATE_POLL_MS = 5000;
const STATUS_STALE_MS = 3 * 60 * 1000;

const canUpdate = () => Array.isArray(scopes) && scopes.includes("admin");
const shortSha = (sha) => (sha ? sha.slice(0, 10) : "unknown");

function ago(then, now) {
  const minutes = Math.max(0, Math.round((Date.parse(now) - Date.parse(then)) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 120) return `${minutes} min ago`;
  return `${Math.round(minutes / 60)} h ago`;
}

function queueText(queue) {
  const waiting = queue.queued ? `, ${queue.queued} queued` : "";
  const state = { idle: "idle", running: "running a job", paused: "paused", unknown: "unknown" }[queue.state];
  return `Queue: ${state || queue.state}${waiting}`;
}

// PHONE-FAST: every phone sees whether the PC is there, its queue, and a cache that has grown large.
function statusLines(status) {
  if (!status) return [];
  const lines = [];
  const pc = status.pc;
  if (pc) {
    const age = Date.parse(status.now) - Date.parse(pc.received_at);
    const seen = age > STATUS_STALE_MS ? `PC last seen ${ago(age)} ago. ` : "";
    lines.push(el("p", { class: "muted", text: `${seen}${queueText(pc)}` }));
  }
  if (status.cache.over) {
    const gb = (bytes) => `${Math.round(bytes / 1024 ** 3)} GB`;
    lines.push(
      el("p", { class: "error", text: `The phone cache holds ${gb(status.cache.bytes)} (warning level ${gb(status.cache.warn_bytes)}).` }),
    );
  }
  return lines;
}

function ago(milliseconds) {
  const minutes = Math.round(milliseconds / 60000);
  if (minutes < 120) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

function receiptText(update, reasonCode) {
  if (update && update.status === "applied") {
    const health =
      update.health === "confirmed"
        ? "StableNew started."
        : "StableNew was started but did not confirm it is running (health unconfirmed); check it when you can.";
    return `Updated ${shortSha(update.old_sha)} → ${shortSha(update.new_sha)}. ${health}`;
  }
  const reason = (update && update.reason_code) || reasonCode;
  const text = UPDATE_REASONS[reason] || REASONS[reason] || reason || "no reason given";
  return reason === "already_current" ? "Already up to date." : `Not updated: ${text}.`;
}

function requestRow(request) {
  const when = new Date(request.created_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  const text =
    request.state === "pending"
      ? "Waiting for the PC. It waits for the running job, then updates and restarts."
      : request.state === "superseded"
        ? "Replaced by a newer request."
        : receiptText(request.update, request.reason_code);
  const kind = request.state === "refused" ? "error" : request.state === "pending" ? "muted" : "";
  return el("li", {}, [
    el("p", { text: `${when} · update to ${shortSha(request.expected_sha)}` }),
    el("p", { class: kind, text }),
  ]);
}

async function sendUpdate(sha) {
  const body = { action: "update_and_restart", expected_sha: sha, idempotency_key: idempotencyKey() };
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await api("/api/admin/updates", body);
    } catch (error) {
      if (error.status || attempt >= 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
}

let updateTimer = 0;

async function showUpdate(serial) {
  await loadScopes();
  if (!canUpdate()) throw new ApiError(403, "not_granted");
  const data = await api("/api/admin");
  if (serial !== renderSerial) return;
  const status = data.pc_status;
  const nodes = [];
  const pending = data.requests.some((request) => request.state === "pending");
  if (!status) {
    nodes.push(el("p", { class: "muted", text: "The PC has not reported yet. It reports while StableNew runs." }));
  } else {
    const checkout = status.checkout || {};
    const stale = Date.parse(data.now) - Date.parse(data.received_at) > STATUS_STALE_MS;
    const behind = checkout.commits_behind || 0;
    nodes.push(
      el("section", { class: "run pc" }, [
        el("p", { class: stale ? "error" : "muted", text: `PC last reported ${ago(data.received_at, data.now)}.` }),
        el("p", { text: `Running main at ${shortSha(checkout.head_sha)}` }),
        el("p", {
          text: checkout.origin_main_sha
            ? `origin/main is ${shortSha(checkout.origin_main_sha)} (${behind} new commit${behind === 1 ? "" : "s"})`
            : "origin/main is not known yet",
        }),
        checkout.fetched_at
          ? el("p", { class: "muted", text: `Checked ${ago(checkout.fetched_at, data.now)}.` })
          : null,
        el("p", { text: queueText(status.queue) }),
        status.update.state === "in_progress"
          ? el("p", { text: "An update is in progress on the PC." })
          : null,
        status.remote_update_enabled
          ? null
          : el("p", { class: "error", text: "Remote update is switched off on the PC (Update dialog)." }),
        status.last_result
          ? el("p", { class: "muted", text: `Last update: ${receiptText(status.last_result)}` })
          : null,
      ]),
    );
    const ready =
      status.remote_update_enabled &&
      status.update.state === "idle" &&
      !pending &&
      checkout.origin_main_sha &&
      checkout.origin_main_sha !== checkout.head_sha &&
      behind > 0;
    if (ready) {
      const sha = checkout.origin_main_sha;
      const where = status.queue.state === "running" ? "after the running job" : "now";
      nodes.push(
        el("button", {
          type: "button",
          class: "primary",
          text: `Update to ${shortSha(sha)} (${behind} commit${behind === 1 ? "" : "s"})`,
          onclick: async (event) => {
            const question =
              `Update the PC to ${shortSha(sha)} and restart StableNew ${where}? ` +
              "Queued jobs resume after the restart. Nothing is installed.";
            if (!window.confirm(question)) return;
            event.currentTarget.disabled = true;
            try {
              await sendUpdate(sha);
              toast("Sent to the PC");
            } catch (error) {
              toast(`Not sent: ${NOT_SENT[error.code] || error.code || "no connection"}`);
            }
            route();
          },
        }),
      );
    } else if (!pending && checkout.origin_main_sha && behind === 0) {
      nodes.push(el("p", { class: "muted", text: "The PC is up to date with origin/main." }));
    }
  }
  if (data.requests.length) {
    nodes.push(el("h2", { class: "section-title", text: "Requests from this phone" }), el("ul", { class: "updates" }, data.requests.map(requestRow)));
  }
  show("Update the PC", true, ...nodes);
  clearTimeout(updateTimer);
  if (pending || (status && status.update.state === "in_progress")) {
    updateTimer = setTimeout(() => {
      if (serial === renderSerial && !document.hidden) refresh();
    }, UPDATE_POLL_MS);
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
  decideUndoably([[item, verdict, favorite, tags]]);
  if (navigator.vibrate) navigator.vibrate(15);
  toast(favorite ? "★ Favorite" : verdict === "keep" ? "Kept" : "Deleted");
  advance();
}

function advance() {
  if (triage.index + 1 < triage.list.length) {
    triage.index += 1;
    renderItem();
    triage.lockedUntil = Date.now() + 250; // a double tap must not decide the next item unseen
  } else {
    toast(isStream(triage.runId) ? "Nothing more to review" : "End of this run");
    location.hash = leaving(triage.runId);
  }
}

// --- routing ------------------------------------------------------------------------------------------------------

// Where "back" goes from a run or from reviewing it: the grid, else the section it was opened from, else home.
function leaving(runId, fromTriage = true) {
  if (fromTriage && !isStream(runId)) return `#/run/${encodeURIComponent(runId)}`;
  const name = runId.startsWith("all:") ? runId.slice(4) : runId === "all" ? "" : section;
  return name ? `#/section/${name}` : "";
}

async function route() {
  const serial = ++renderSerial;
  const [, page, run, libraryId] = location.hash.split("/");
  triage = null;
  closeSheet();
  try {
    if (page === "triage" && run) await showTriage(decodeURIComponent(run), libraryId, serial);
    else if (page === "run" && run) await showRun(decodeURIComponent(run), serial);
    else if (page === "rejected") showRejected();
    else if (page === "update") await showUpdate(serial);
    else if (page === "section" && SECTIONS[run]) await showSection(run, serial);
    else await showHome(serial);
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

back.addEventListener("click", () => {
  const [, page, run] = location.hash.split("/");
  location.hash = (page === "triage" || page === "run") && run ? leaving(decodeURIComponent(run), page === "triage") : "";
});
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

showBadges();
flush();
route();
