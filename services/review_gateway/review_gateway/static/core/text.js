// Shared wording: reasons, section names, run names and ages.

import { groupName } from "./store.js";

export const REASONS = {
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

// PHONE-FAST: the review sections, by the category id the PC sends. Evaluation sittings are not a section here.
export const SECTIONS = {
  pipeline: "Pipeline runs",
  learning: "Learning runs",
  reprocess: "Reprocess and rework",
  video: "Movie clips",
  testing: "Test runs",
  other: "Other",
};

export const isStream = (runId) => runId === "all" || runId.startsWith("all:");

export function runName(runId) {
  if (isStream(runId)) return runId === "all" ? "To review" : `To review: ${SECTIONS[runId.slice(4)] || "Other"}`;
  if (runId.startsWith("batch:")) return groupName(runId) || "Batch";
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

export function ago(then, now) {
  const minutes = Math.max(0, Math.round((Date.parse(now) - Date.parse(then)) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 120) return `${minutes} min ago`;
  return `${Math.round(minutes / 60)} h ago`;
}

export function duration(milliseconds) {
  const minutes = Math.round(milliseconds / 60000);
  if (minutes < 120) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

export function since(milliseconds) {
  const minutes = Math.max(1, Math.round(milliseconds / 60000));
  if (minutes < 120) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}
