// NAME-INFO: the lines "More info" shows for one item, and for each side of a compare. The PC says how the item was
// made (item.info); an item published without that shows what it already has. app.js draws the lines as text.
"use strict";

const MoreInfo = (() => {
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

  return { lines };
})();
