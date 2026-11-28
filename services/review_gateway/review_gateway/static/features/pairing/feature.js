// The pairing screen, shown when the gateway no longer knows this phone.

import { showPairing } from "./pairing.js";

export default {
  id: "pairing",
  order: 90,
  start({ bus }) {
    bus.on("session:lost", showPairing);
  },
};
