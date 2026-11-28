// Phone actions (RG-140): the row under an item.

import { actionRow } from "./actions.js";

export default {
  id: "actions",
  order: 40,
  start({ slots }) {
    slots.contribute("item.tools", ({ item }) => actionRow(item));
  },
};
