// NAME-INFO: the lines "More info" shows for one item, and for each side of a compare. The PC says how the item was
// made (item.info); an item published without that shows what it already has. The lines are drawn as text.

import { el } from "../../core/dom.js";
import { mediaUrl } from "../../core/media.js";

function lines(item) {
  const info = item.info || {};
  const display = item.display || {};
  const batch = item.batch || {};
  const cell = batch.cell || {};
  const full = info.model_name || display.model || display.workflow || cell.model || "";
  const model = info.model && full && info.model !== full ? `${info.model} (${full})` : full || info.model;
  const prompt = [
    info.prompt_number ? `prompt ${info.prompt_number}` : "",
    info.variant ? `variant ${info.variant}` : "",
  ];
  const made = info.made_at || item.created_at;
  return [
    ["Path", info.stage_path],
    ["Model", model],
    ["Prompt pack", info.pack || cell.pack],
    ["Prompt", prompt.filter(Boolean).join(", ")],
    ["Made", made ? new Date(made).toLocaleString() : ""],
    ["Seed", info.seed || display.seed],
    ["Batch", info.batch || batch.name],
    ["Duration", item.duration_s ? `${item.duration_s} s` : ""],
    ["File", info.file_name],
  ].filter(([, value]) => value);
}

// NAME-INFO: "More info" for one item, or for both sides of a compare (the lines come from above).
export function infoPanel(item, other) {
  const sides = other ? [["Original", other], [other.desk ? "Reprocess" : "Rework", item]] : [["", item]];
  const about = ([heading, side]) => {
    const prompt = side.display && side.display.prompt_excerpt;
    return [
      heading ? el("h2", { text: heading }) : null,
      ...lines(side).map(([name, value]) => el("p", { text: `${name}: ${value}` })),
      prompt ? el("p", { text: `Prompt text: ${prompt}` }) : null,
      el("a", { href: mediaUrl(side, "original"), target: "_blank", rel: "noopener", text: "Open full size" }),
    ];
  };
  return el("div", { class: "info moreinfo", hidden: "" }, [
    ...sides.flatMap(about),
    item.kind === "image" ? el("p", { class: "muted", text: "Double-tap the picture for full resolution." }) : null,
  ]);
}
