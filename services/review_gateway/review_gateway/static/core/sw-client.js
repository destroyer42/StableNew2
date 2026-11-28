// The page's side of the service worker (PHONE-CORE 2.3): registration through the one Trusted Types policy, noticing
// a new version, persistent storage and Repair.

const WORKER = "/sw.js";
const CHECK_MS = 30 * 60 * 1000;
const ANSWER_MS = 3000;

let waiting = null; // a new version's worker: installed, and waiting to be let in
const listeners = [];

// The only script address this page may hand the browser; the CSP allows no other policy (trusted-types rg-sw).
function workerUrl() {
  if (!window.trustedTypes) return WORKER;
  const policy = window.trustedTypes.createPolicy("rg-sw", {
    createScriptURL(url) {
      if (url !== WORKER) throw new TypeError("not the service worker");
      return url;
    },
  });
  return policy.createScriptURL(WORKER);
}

// What a worker says it is: {version, commit}, or null when it does not answer.
export function describe(worker) {
  if (!worker) return Promise.resolve(null);
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => resolve(null), ANSWER_MS);
    channel.port1.onmessage = (event) => {
      clearTimeout(timer);
      resolve(event.data);
    };
    worker.postMessage({ type: "VERSION" }, [channel.port2]);
  });
}

async function offer(worker) {
  if (waiting === worker) return;
  waiting = worker;
  const found = await describe(worker);
  for (const listener of listeners) listener(found);
}

// A worker installed beside an active one is an update; the very first one is not.
function watch(registration, worker) {
  if (!worker) return;
  const check = () => {
    if (worker.state === "installed" && registration.active && registration.active !== worker) offer(worker);
  };
  worker.addEventListener("statechange", check);
  check();
}

// fn({version, commit} or null) is told of a new version waiting.
export function onUpdate(fn) {
  listeners.push(fn);
  if (waiting) describe(waiting).then(fn);
}

export async function register() {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.register(workerUrl(), { scope: "/", updateViaCache: "none" });
  watch(registration, registration.waiting);
  watch(registration, registration.installing);
  registration.addEventListener("updatefound", () => watch(registration, registration.installing));
  // The browser also checks on every opening of the app and at least daily.
  const check = () => registration.update().catch(() => {}); // unreachable: the next check will do
  document.addEventListener("visibilitychange", () => document.hidden || check());
  setInterval(check, CHECK_MS);
  await persist();
}

// Asks the browser not to evict this phone's saved work under storage pressure.
export async function persist() {
  if (!navigator.storage?.persist) return false;
  return (await navigator.storage.persisted()) || navigator.storage.persist();
}

// Lets the waiting version in and reloads onto it. The caller first sends what it still holds.
export function applyUpdate() {
  const worker = waiting;
  let reloading = false;
  const reload = () => {
    if (reloading) return;
    reloading = true;
    location.reload();
  };
  // Already let in (from another tab), or replaced by a newer one: a reload shows where things stand.
  if (!worker || worker.state !== "installed") return reload();
  navigator.serviceWorker.addEventListener("controllerchange", reload);
  worker.addEventListener("statechange", () => worker.state === "activated" && reload());
  worker.postMessage({ type: "SKIP_WAITING" });
}

// The way out of a bad saved copy. The pairing cookie, unsent work and settings are not touched.
export async function repair() {
  const registrations = (await navigator.serviceWorker?.getRegistrations()) || [];
  await Promise.all(registrations.map((registration) => registration.unregister()));
  const saved = (await window.caches?.keys()) || [];
  await Promise.all(saved.filter((name) => /^rg-(shell|media)-/.test(name)).map((name) => caches.delete(name)));
  location.reload();
}
