// RG-160: the waiting list (#/requests), and the warning before deleting what has a request waiting.

import { api } from "../../core/api.js";
import { actionLabel, refusalText } from "../../core/catalog.js";
import { closeSheet, el, sheet, show, toast } from "../../core/dom.js";
import { mediaUrl } from "../../core/media.js";
import { QUEUE_KEY, changeList, without } from "../../core/outbox.js";
import { route } from "../../core/router.js";
import { dismiss, dismissed, lastReply, presence, sync, unsent, usable } from "./queued.js";
import { sheetFor } from "./request.js";

let listing = 0;

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
  return el("section", { class: "run request-row" }, [
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
  return row(entry, describe(entry, lastReply().image_backend_ready), buttons, summary ? summary.warnings : []);
}

async function show_(view) {
  const asking = ++listing;
  await sync();
  if (!view.alive() || asking !== listing) return;
  const gone = dismissed();
  const local = unsent().map((entry) =>
    row(entry, "Not sent yet", [
      button("Cancel", () => {
        changeList(QUEUE_KEY, without(entry.idempotency_key));
        route();
      }),
    ]),
  );
  const latest = lastReply();
  const remote = (latest ? latest.requests : []).filter((e) => !gone.has(e.record_id)).map(entryRow);
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

export { confirmDelete, show_ as show };
