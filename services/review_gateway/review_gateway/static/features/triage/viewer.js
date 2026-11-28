// Full resolution with pinch zoom and pan, and the double tap that opens it.

import { el } from "../../core/dom.js";
import { mediaUrl } from "../../core/media.js";

// --- full resolution (PHONE-FAST) ---------------------------------------------------------------------------------
// A double tap on a picture shows the original with pinch zoom and pan. A double tap returns to fit, and from fit
// closes it. The rendition stays the default.

const DOUBLE_TAP_MS = 300;
const TAP_REACH = 40; // px between the two taps

// Tell one tap from two on the same spot; the single tap waits to see whether a second one comes.
export function doubleTaps() {
  let last = null;
  return (x, y, single, double) => {
    if (last && Math.hypot(x - last.x, y - last.y) < TAP_REACH) {
      clearTimeout(last.timer);
      last = null;
      double();
      return;
    }
    const timer = setTimeout(() => {
      last = null;
      single();
    }, DOUBLE_TAP_MS);
    last = { x, y, timer };
  };
}

export function closeViewer() {
  document.querySelector(".viewer")?.remove();
}

export function openViewer(item) {
  closeViewer();
  const image = el("img", { src: mediaUrl(item, "original"), alt: "Full resolution", draggable: "false" });
  const status = el("p", { class: "viewer-status", role: "status", text: "Loading full resolution…" });
  const close = el("button", { type: "button", class: "viewer-close", text: "Close", onclick: closeViewer });
  const node = el("div", { class: "viewer", role: "dialog", "aria-modal": "true" }, [image, status, close]);
  image.addEventListener("load", () => (status.hidden = true), { once: true });
  image.addEventListener("error", () => (status.textContent = "Could not load the full-resolution image."), {
    once: true,
  });
  attachZoom(node, image);
  document.body.append(node);
}

function attachZoom(node, image) {
  const view = { scale: 1, x: 0, y: 0 }; // the picture's zoom and its offset from the middle
  const fingers = new Map();
  const taps = doubleTaps();
  let from = null; // the view and fingers a gesture started from
  let moved = false;
  const clamp = (value, limit) => Math.min(limit, Math.max(-limit, value));
  const apply = () => {
    const box = node.getBoundingClientRect();
    const most = Math.max(4, (2 * (image.naturalWidth || 0)) / (image.offsetWidth || 1));
    view.scale = Math.min(most, Math.max(1, view.scale));
    view.x = clamp(view.x, Math.max(0, (image.offsetWidth * view.scale - box.width) / 2));
    view.y = clamp(view.y, Math.max(0, (image.offsetHeight * view.scale - box.height) / 2));
    image.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  };
  const gesture = () => {
    const box = node.getBoundingClientRect();
    const points = [...fingers.values()];
    const [a, b = a] = points;
    return {
      x: (a.x + b.x) / 2 - box.left - box.width / 2,
      y: (a.y + b.y) / 2 - box.top - box.height / 2,
      spread: Math.hypot(a.x - b.x, a.y - b.y),
    };
  };
  const begin = () => (from = fingers.size ? { scale: view.scale, left: view.x, top: view.y, at: gesture() } : null);
  node.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".viewer-close")) return;
    if (!fingers.size) moved = false;
    fingers.set(event.pointerId, { x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY });
    if (fingers.size > 1) moved = true;
    node.setPointerCapture?.(event.pointerId);
    begin();
  });
  node.addEventListener("pointermove", (event) => {
    const finger = fingers.get(event.pointerId);
    if (!finger || !from) return;
    finger.x = event.clientX;
    finger.y = event.clientY;
    if (Math.hypot(finger.x - finger.startX, finger.y - finger.startY) >= 8) moved = true;
    const now = gesture();
    const factor = fingers.size > 1 && from.at.spread ? now.spread / from.at.spread : 1;
    view.scale = from.scale * factor;
    // The spot under the fingers stays under them.
    view.x = now.x - ((from.at.x - from.left) / from.scale) * view.scale;
    view.y = now.y - ((from.at.y - from.top) / from.scale) * view.scale;
    apply();
  });
  const lift = (event) => {
    if (!fingers.delete(event.pointerId)) return;
    begin();
    if (fingers.size || moved || event.type === "pointercancel") return;
    taps(
      event.clientX,
      event.clientY,
      () => {},
      () => {
        if (view.scale > 1.01) {
          Object.assign(view, { scale: 1, x: 0, y: 0 });
          apply();
        } else {
          closeViewer();
        }
      },
    );
  };
  node.addEventListener("pointerup", lift);
  node.addEventListener("pointercancel", lift);
}
