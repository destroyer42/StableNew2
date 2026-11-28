// The triage stream, its item view and the full-resolution viewer.

import { leaving } from "../../core/router.js";
import {
  addTags,
  moveOnAfterRework,
  refreshTriage,
  renderItem,
  showTriage,
  updateTriageStatus,
} from "./triage.js";
import { closeViewer } from "./viewer.js";

export default {
  id: "triage",
  order: 20,
  routes: [
    {
      pattern: "#/triage/:run/:item?",
      render: ({ run, item }, view) => showTriage(decodeURIComponent(run), item, view),
      refresh: (params, view) => refreshTriage(view),
      back: ({ run }) => leaving(decodeURIComponent(run), true),
    },
  ],
  start({ bus }) {
    bus.on("route:start", closeViewer);
    bus.on("items:changed", updateTriageStatus);
    bus.on("item:restored", renderItem);
    bus.on("tags:wanted", addTags);
    bus.on("rework:closed", moveOnAfterRework);
  },
};
