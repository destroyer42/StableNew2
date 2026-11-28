"""The core's two ways for features to meet without importing each other: slots and the bus (PHONE-CORE 2.2).

Run as the page's own modules in the page's browser, so there is no stand-in for either.
"""

from __future__ import annotations

SLOTS = """async () => {
  const version = document.querySelector('script[type="module"]').src.match(/\\/s\\/([0-9a-f]+)\\//)[1];
  const { createSlots } = await import(`/s/${version}/core/slots.js`);
  const slots = createSlots();
  slots.contribute("home.top", (ctx) => `first ${ctx.who}`);
  slots.contribute("home.top", () => null);
  slots.contribute("home.top", () => ["third", "", "fourth"]);
  slots.contribute("delete.warn", () => null);
  slots.contribute("delete.warn", () => "second asked");
  slots.contribute("action.open", () => false);
  slots.contribute("action.open", () => "taken");
  slots.contribute("action.open", () => { throw new Error("asked after it was taken"); });
  let unknown = "";
  try {
    slots.contribute("home.middle", () => null);
  } catch (error) {
    unknown = error.message;
  }
  return {
    rendered: slots.render("home.top", { who: "up" }),
    asked: slots.ask("delete.warn", {}),
    claimed: slots.claim("action.open", {}),
    unclaimed: slots.claim("item.view", {}),
    unknown,
  };
}"""

BUS = """async () => {
  const version = document.querySelector('script[type="module"]').src.match(/\\/s\\/([0-9a-f]+)\\//)[1];
  const { createBus } = await import(`/s/${version}/core/bus.js`);
  const bus = createBus();
  const heard = [];
  const one = (value) => heard.push(`one ${value}`);
  const returned = bus.on("items:changed", one);
  bus.on("items:changed", (value) => heard.push(`two ${value}`));
  bus.emit("items:changed", "a");
  bus.off("items:changed", one);
  const result = bus.emit("items:changed", "b");
  let unknown = "";
  try {
    bus.emit("items:moved");
  } catch (error) {
    unknown = error.message;
  }
  return { heard, unknown, returned: returned === undefined, result: result === undefined };
}"""


def test_slots_keep_feature_order_and_refuse_unknown_names(phone) -> None:
    phone.goto("/")

    assert phone.evaluate(SLOTS) == {
        "rendered": ["first up", "third", "fourth"],
        "asked": [None, "second asked"],
        "claimed": "taken",
        "unclaimed": False,
        "unknown": "no slot named home.middle",
    }


def test_the_bus_only_notifies_in_the_order_subscribed_and_refuses_unknown_topics(phone) -> None:
    phone.goto("/")

    assert phone.evaluate(BUS) == {
        "heard": ["one a", "two a", "two b"],
        "unknown": "no topic named items:moved",
        "returned": True,
        "result": True,
    }
