// Named extension points (PHONE-CORE 2.2). A feature contributes; the host renders, asks or claims without knowing
// who answers. Contributions run in the order the features started, which is each feature's "order". Adding a name
// is a core change.

const NAMES = Object.freeze([
  "home.top", // render ({status}): above the review folders
  "home.bottom", // render: below them
  "home.prepare", // ask: promises to wait for before the home screen is drawn
  "header.badges", // render: buttons in the header
  "tile.marks", // render ({item}): marks on a grid tile
  "item.status", // render ({item}): text added to the item's status line
  "item.info", // render ({item, other}): the "More info" panel
  "item.tools", // render ({item}): controls under the item
  "item.view", // claim ({item, ...triage controls}): show this item another way
  "action.open", // claim ({why, item, action, extra, answer}): take over a phone action
  "delete.warn", // ask or claim ({items}): {text, confirm(proceed)} when a delete needs a warning
  "items.overlay", // ask ({items}): lay work not yet sent over rows just read
]);

export function createSlots() {
  const contributions = new Map(NAMES.map((name) => [name, []]));
  const of = (name) => {
    const found = contributions.get(name);
    if (!found) throw new Error(`no slot named ${name}`);
    return found;
  };
  return {
    contribute(name, fn) {
      of(name).push(fn);
    },
    // Everything every contribution gave, in order; what is not there is left out.
    render: (name, context) => of(name).flatMap((fn) => fn(context)).filter(Boolean),
    // Every contribution's answer, in order.
    ask: (name, context) => of(name).map((fn) => fn(context)),
    // The first contribution that takes it; the later ones are not asked.
    claim(name, context) {
      for (const fn of of(name)) {
        const taken = fn(context);
        if (taken) return taken;
      }
      return false;
    },
  };
}

export const slots = createSlots();
