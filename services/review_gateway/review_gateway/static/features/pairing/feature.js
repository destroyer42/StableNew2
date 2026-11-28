// The pairing screen, shown when the gateway no longer knows this phone, or when the PC's QR link is opened.

import { openPairing, showPairing } from "./pairing.js";

export default {
  id: "pairing",
  order: 90,
  routes: [{ pattern: "#/pair/:code?", render: ({ code }) => openPairing(code) }],
  start({ bus }) {
    bus.on("session:lost", () => showPairing());
  },
};
