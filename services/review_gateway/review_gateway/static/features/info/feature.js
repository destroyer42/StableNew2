// NAME-INFO: the "More info" panel of an item or a compare.

import { infoPanel } from "./moreinfo.js";

export default {
  id: "info",
  order: 80,
  start({ slots }) {
    slots.contribute("item.info", ({ item, other }) => infoPanel(item, other));
  },
};
