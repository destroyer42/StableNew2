// The PC's status lines and the admin "Update the PC" screen.

import { ApiError, api, idempotencyKey } from "../../core/api.js";
import { el, show, toast } from "../../core/dom.js";
import { refresh, route } from "../../core/router.js";
import { canUpdate, loadScopes } from "../../core/session.js";
import { STATUS_STALE_MS } from "../../core/status.js";
import { REASONS, ago, duration } from "../../core/text.js";

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

const shortSha = (sha) => (sha ? sha.slice(0, 10) : "unknown");

function queueText(queue) {
  const waiting = queue.queued ? `, ${queue.queued} queued` : "";
  const state = { idle: "idle", running: "running a job", paused: "paused", unknown: "unknown" }[queue.state];
  return `Queue: ${state || queue.state}${waiting}`;
}

// PHONE-FAST: every phone sees whether the PC is there, its queue, and a cache that has grown large.
export function statusLines(status) {
  if (!status) return [];
  const lines = [];
  const pc = status.pc;
  if (pc) {
    const age = Date.parse(status.now) - Date.parse(pc.received_at);
    const seen = age > STATUS_STALE_MS ? `PC last seen ${duration(age)} ago. ` : "";
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

export async function showUpdate(view) {
  await loadScopes();
  if (!canUpdate()) throw new ApiError(403, "not_granted");
  const data = await api("/api/admin");
  if (!view.alive()) return;
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
      if (view.alive() && !document.hidden) refresh();
    }, UPDATE_POLL_MS);
  }
}

// Only a phone paired for remote update is offered it.
export const updateLink = () =>
  canUpdate()
    ? el("button", { type: "button", class: "pc-link", text: "Update the PC…", onclick: () => (location.hash = "#/update") })
    : null;
