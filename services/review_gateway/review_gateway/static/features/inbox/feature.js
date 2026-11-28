// The home screen, the sections and the run grids.

import { leaving } from "../../core/router.js";
import { SECTIONS } from "../../core/text.js";
import { renderGrid, showHome, showRun, showSection } from "./inbox.js";

const home = (params, view) => showHome(view);
const run = ({ run }, view) => showRun(decodeURIComponent(run), view);
const section = ({ id }, view) => showSection(id, view);

export default {
  id: "inbox",
  order: 10,
  routes: [
    { pattern: "#/", render: home, refresh: home },
    { pattern: "#/run/:run", list: true, render: run, refresh: run, back: ({ run }) => leaving(decodeURIComponent(run), false) },
    { pattern: "#/section/:id", list: true, accepts: ({ id }) => Boolean(SECTIONS[id]), render: section, refresh: section },
  ],
  start({ bus }) {
    bus.on("grid:wanted", renderGrid);
  },
};
