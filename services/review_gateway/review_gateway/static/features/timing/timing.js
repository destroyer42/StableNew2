// How long the phone takes to open an image: from the item becoming current to its rendition's load event, and
// whether the bytes were asked for then, came from the cache or were fetched ahead. Nothing sent names an item.
// Times that cannot be sent are dropped: no outbox, and one retry of a batch that failed.

import { idempotencyKey } from "../../core/api.js";
import { mediaUrl } from "../../core/media.js";

const SEND_AFTER_MS = 45000; // one batch at most this often; leaving the page also sends
const BATCH = 100; // the gateway's bound on one batch
const LIMIT_MS = 10 * 60 * 1000; // and on one time
const KEPT_ADDRESSES = 500;

let current = ""; // the rendition the screen is on, so drawing it again is not opening it again
let opening = null; // {url, start} until it has loaded
let measured = []; // {url, start, ms, again}, not sent yet
let retry = null; // a batch that failed once
let timer = 0;
let observer = null;
const opened = new Set(); // renditions already opened since the page loaded
const fetches = new Map(); // rendition address -> its resource timing entries

export function itemShown(item) {
  const rendition = item.kind === "image" && item.variants.includes("preview");
  const url = rendition ? new URL(mediaUrl(item, "preview"), location.href).href : "";
  if (url === current) return;
  current = url;
  opening = url && !document.hidden ? { url, start: performance.now() } : null;
}

// A hidden page loads when it likes, so what was being opened is not timed.
export function stopWaiting() {
  opening = null;
}

export function screenLeft() {
  current = "";
  opening = null;
}

// Load and error do not bubble, but a capturing listener hears them. Images fetched ahead are not in the document.
function settled(event) {
  if (!opening || event.target.tagName !== "IMG" || event.target.src !== opening.url) return;
  if (event.type === "load") {
    const ms = Math.round(performance.now() - opening.start);
    if (ms <= LIMIT_MS && measured.length < BATCH) {
      measured.push({ ...opening, ms, again: opened.has(opening.url) });
    }
    opened.add(opening.url);
    schedule();
  }
  opening = null;
}

function note(entries) {
  for (const entry of entries) {
    if (!entry.name.endsWith("/preview")) continue;
    const found = [...(fetches.get(entry.name) || []), entry].slice(-4);
    fetches.delete(entry.name);
    fetches.set(entry.name, found);
    if (fetches.size > KEPT_ADDRESSES) fetches.delete(fetches.keys().next().value);
  }
}

// An answer from the browser's cache moves no bytes, or only the headers that revalidated it.
const fromCache = (entry) => entry.transferSize === 0 || entry.transferSize < entry.encodedBodySize;

// The browser's own record is read when the batch is made: it can arrive after the load event.
function sample({ url, start, ms, again }) {
  const found = fetches.get(url) || [];
  const own = found.find((entry) => entry.startTime >= start - 1 && entry.startTime <= start + ms);
  const earlier = found.find((entry) => entry.startTime < start - 1);
  let source = "unknown";
  if (own && !fromCache(own)) source = "network";
  else if (earlier && !again) source = "prefetch";
  else if (own || earlier) source = "cache";
  const size = (own || earlier)?.encodedBodySize;
  return { ms, source, bytes: size > 0 ? size : null };
}

function takeBatch() {
  note(observer?.takeRecords() || []);
  const samples = measured.map(sample);
  measured = [];
  return samples.length ? { idempotency_key: idempotencyKey(), samples } : null;
}

async function send(batch, mayRetry) {
  if (!batch || !navigator.onLine) return;
  try {
    const response = await fetch("/api/timings", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true, // it still arrives when the page is being left
      headers: { "X-Review-Gateway": "1", "Content-Type": "application/json" },
      body: JSON.stringify(batch),
    });
    if (response.status < 500) return; // stored, or refused for good
  } catch {
    // No answer is treated like a server error.
  }
  if (mayRetry) {
    retry = batch; // the same key, so a batch the gateway did store is not stored twice
    schedule();
  }
}

function schedule() {
  if (!timer && (measured.length || retry)) timer = setTimeout(tick, SEND_AFTER_MS);
}

function tick() {
  timer = 0;
  if (retry) {
    const failed = retry;
    retry = null;
    send(failed, false);
  } else {
    send(takeBatch(), true);
  }
  schedule();
}

export function leavePage() {
  const failed = retry;
  retry = null;
  send(failed, false);
  send(takeBatch(), true);
}

export function start() {
  document.addEventListener("load", settled, true);
  document.addEventListener("error", settled, true);
  if (!window.PerformanceObserver) return; // times are still sent, from an "unknown" source
  observer = new PerformanceObserver((list) => note(list.getEntries()));
  observer.observe({ type: "resource", buffered: true });
}
