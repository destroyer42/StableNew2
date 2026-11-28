// The home screen, a section's runs, a run's grid, "Keep the rest" and "Delete this run".

import { api } from "../../core/api.js";
import { closeSheet, el, sheet, show, toast } from "../../core/dom.js";
import { mediaUrl } from "../../core/media.js";
import { queueDecision, releaseHeld } from "../../core/outbox.js";
import { route, setSection } from "../../core/router.js";
import { loadScopes } from "../../core/session.js";
import { readSetting, writeSetting } from "../../core/settings.js";
import { slots } from "../../core/slots.js";
import { currentFilter, itemsOf, loadRun, needsReview, setFilter, setGroupName } from "../../core/store.js";
import { SECTIONS, runName } from "../../core/text.js";

const SEEN_KEY = "rg.seen"; // section -> the gateway's time when this phone last opened it
const COUNT_KEY = "rg.count"; // "new" shows what arrived since then; otherwise what is left to review

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
  const warnings = slots.ask("delete.warn", { items: targets }).filter(Boolean);
  sheet(
    el("h2", { text: `Delete ${targets.length}?` }),
    el("p", { text: `The files go to the PC's archive.${stay ? ` ${stay} stay.` : ""}` }),
    ...warnings.map((warning) => el("p", { text: warning.text })),
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
          setFilter("todo");
          location.hash = `#/triage/${encodeURIComponent(run.run_id)}`;
        },
      })
    : null;
  if (run.kind === "batch" && run.name) setGroupName(run.run_id, run.name);
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

function reviewAllButton(count, runId) {
  if (!count) return null;
  const open = () => {
    setFilter("todo");
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
export async function showHome(view) {
  const seen = readSetting(SEEN_KEY, {});
  const query = new URLSearchParams(seen).toString();
  const { sections } = await api(`/api/sections${query ? `?${query}` : ""}`);
  await loadScopes();
  const status = await api("/api/status").catch(() => null); // extra: the home screen shows without it
  await Promise.all(slots.ask("home.prepare"));
  if (!view.alive()) return;
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
  const content = sections.length
    ? [
        el("div", { class: "tools counting" }, [counting("todo", "To review"), counting("new", "New since opened")]),
        ...sections.map((entry) => sectionRow(entry, countNew)),
      ]
    : [el("p", { class: "muted", text: "Nothing to review yet. Items appear after the PC syncs." })];
  // Above the folders: the PC's state, what waits for it, and To rate. Eval clips are rated there, never a folder here.
  const above = slots.render("home.top", { status });
  const below = slots.render("home.bottom");
  show("Review", false, ...[...above, reviewAllButton(waiting, "all"), ...content, ...below].filter(Boolean));
}

export async function showSection(name, view) {
  const clock = await api("/api/status").catch(() => null); // asked first: nothing arriving meanwhile counts as seen
  const { runs } = await api(`/api/runs?source=${encodeURIComponent(name)}`);
  if (!view.alive()) return;
  setSection(name);
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
      ...slots.render("tile.marks", { item }),
    ],
  );
}

export function renderGrid(runId) {
  const items = itemsOf(runId) || [];
  const todo = items.filter(needsReview);
  const shown = currentFilter() === "todo" && todo.length ? todo : items;
  const toggle = (value, text) =>
    el("button", {
      type: "button",
      text,
      "aria-pressed": String(value === (shown === todo ? "todo" : "all")),
      onclick: () => {
        setFilter(value);
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

export async function showRun(runId, view) {
  await loadRun(runId);
  if (view.alive()) renderGrid(runId);
}
