// Image open times (the PHONE-FAST gate). This feature only watches: it draws nothing and takes over nothing.

import { itemShown, leavePage, screenLeft, start, stopWaiting } from "./timing.js";

export default {
  id: "timing",
  order: 15, // before compare's, so item.view asks it about every item, before the item's image element exists
  start({ bus, slots }) {
    slots.contribute("item.view", ({ item }) => {
      itemShown(item);
      return false; // never claimed: it is only told that the item became current
    });
    bus.on("route:start", screenLeft);
    document.addEventListener("visibilitychange", () => document.hidden && stopWaiting());
    window.addEventListener("pagehide", leavePage);
    start();
  },
};
