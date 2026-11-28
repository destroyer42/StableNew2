// A rework or reprocess result against its original: shown inside the triage in place of the single item.

import { needsReview } from "../../core/store.js";
import { renderCompare } from "./compare.js";

export default {
  id: "compare",
  order: 30,
  start({ slots }) {
    slots.contribute("item.view", (context) => {
      if (!(context.item.compare && needsReview(context.item))) return false;
      renderCompare(context);
      return true;
    });
  },
};
