// The PC's state on the home screen, and the admin "Update the PC" screen.

import { showUpdate, statusLines, updateLink } from "./status.js";

const update = (params, view) => showUpdate(view);

export default {
  id: "status",
  order: 50,
  routes: [{ pattern: "#/update", render: update, refresh: update }],
  start({ slots }) {
    slots.contribute("home.top", ({ status }) => statusLines(status));
    slots.contribute("home.bottom", () => updateLink());
  },
};
