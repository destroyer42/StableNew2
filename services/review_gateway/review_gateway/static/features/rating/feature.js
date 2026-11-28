// The To rate tab (RG-170).

import { flush } from "./answers.js";
import { entry, route } from "./rating.js";

export default {
  id: "rating",
  order: 70,
  routes: [
    {
      pattern: "#/rate/:task?/:item?",
      render: ({ task, item }, view) => route(task, item, view),
      back: ({ task }) => (task ? "#/rate" : "#/"),
    },
  ],
  start({ slots }) {
    window.addEventListener("online", () => flush()); // answers saved while the gateway was unreachable
    slots.contribute("home.top", () => {
      const button = entry(() => button.remove());
      return button;
    });
  },
};
