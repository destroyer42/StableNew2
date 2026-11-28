// Notifications between the core and the features: never a return value. Adding a topic is a core change.

const TOPICS = Object.freeze([
  "app:started", // the first screen is on its way
  "app:refresh", // the periodic, or back-on-the-page, refresh
  "route:start", // a new screen is about to be drawn
  "session:lost", // the gateway no longer knows this phone
  "items:changed", // item rows changed under the screen
  "item:restored", // Undo put the triage back on an item
  "grid:wanted", // (runId) there is nothing to triage: show the run's grid
  "outbox:sent", // (entry, state) the gateway answered a saved action request
  "tags:wanted", // (item, tags) an action says what is wrong with the item
  "rework:closed", // (item) the sheet of a rework was closed: review moves on
  "action:asked", // ({node, item, action, recordId, step}) the PC was asked and has not answered
]);

export function createBus() {
  const listeners = new Map(TOPICS.map((topic) => [topic, []]));
  const of = (topic) => {
    const found = listeners.get(topic);
    if (!found) throw new Error(`no topic named ${topic}`);
    return found;
  };
  return {
    on(topic, fn) {
      of(topic).push(fn);
    },
    off(topic, fn) {
      const found = of(topic);
      const at = found.indexOf(fn);
      if (at >= 0) found.splice(at, 1);
    },
    // At once and in the order subscribed: a listener has run when emit returns.
    emit(topic, ...values) {
      for (const fn of [...of(topic)]) fn(...values);
    },
  };
}

export const bus = createBus();
