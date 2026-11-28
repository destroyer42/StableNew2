// The service worker (PHONE-CORE 2.3). The server puts `const VERSION = "<v>", COMMIT = "<sha12>";` in front of this
// file, so its bytes change with every deploy, which is how the browser finds a new one.
//
// It keeps the app shell and nothing else. Whatever it does not name here (/api/, /rating-media/, /media/ with its
// originals, anything else) it leaves alone: no respondWith, so the browser fetches as if there were no worker, and
// none of it is ever put in a cache. It reads no cookie and adds no header.

const SHELL = `rg-shell-${VERSION}`;
const PREFIX = `/s/${VERSION}/`;
const PAGES = ["/", "/manifest.webmanifest"]; // the two files of the shell that are not under the prefix

// Only this gateway's own, successful, direct answer is accepted. "reload" goes past the HTTP cache.
async function fetched(path) {
  const response = await fetch(path, { cache: "reload", redirect: "error" });
  if (!response.ok || response.type !== "basic") throw new Error(`not fetched: ${path}`);
  return response;
}

async function verified(path, digest) {
  const response = await fetched(path);
  const body = await response.clone().arrayBuffer();
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", body));
  const hex = Array.from(hash, (byte) => byte.toString(16).padStart(2, "0")).join("");
  if (hex !== digest) throw new Error(`wrong bytes: ${path}`);
  return [path, response];
}

// A listed name must stay below this version's prefix: nothing else can be named into the shell.
function versioned(name) {
  const { pathname } = new URL(PREFIX + name, self.location.origin);
  if (pathname !== PREFIX + name) throw new Error(`not a page file: ${name}`);
  return pathname;
}

// Every file is fetched and checked before the first one is stored, so a shell is whole or absent.
async function precache() {
  const listing = await (await fetched(`${PREFIX}files.json`)).json();
  if (listing.version !== VERSION) throw new Error("another version's list");
  const wanted = [
    ...Object.entries(listing.files).map(([name, digest]) => [versioned(name), digest]),
    ...PAGES.map((path) => [path, listing.shell[path]]),
  ];
  const checked = await Promise.all(wanted.map(([path, digest]) => verified(path, digest)));
  // A deploy that changed no page file has the running worker's cache name: that cache is never dropped on failure.
  const existed = await caches.has(SHELL);
  try {
    const cache = await caches.open(SHELL);
    await Promise.all(checked.map(([path, response]) => cache.put(path, response)));
  } catch (error) {
    if (!existed) await caches.delete(SHELL);
    throw error;
  }
}

// No skipWaiting here: a new version waits until the owner taps Reload or closes the app.
self.addEventListener("install", (event) => event.waitUntil(precache()));

async function takeOver() {
  const old = (await caches.keys()).filter((name) => name.startsWith("rg-shell-") && name !== SHELL);
  await Promise.all(old.map((name) => caches.delete(name)));
  await self.clients.claim();
}

self.addEventListener("activate", (event) => event.waitUntil(takeOver()));

// The shell's address for a request, or null: every other request is the browser's own business.
function shellPath(request) {
  if (request.method !== "GET") return null;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return null;
  if (request.mode === "navigate") return url.pathname === "/" ? "/" : null;
  if (url.search) return null;
  return url.pathname === "/manifest.webmanifest" || url.pathname.startsWith(PREFIX) ? url.pathname : null;
}

// Cache first, so the page, its modules and this worker are one version. Nothing is stored here.
async function fromShell(path, request) {
  const hit = await caches.match(path, { cacheName: SHELL });
  return hit || fetch(request);
}

self.addEventListener("fetch", (event) => {
  const path = shellPath(event.request);
  if (path) event.respondWith(fromShell(path, event.request));
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
  if (event.data?.type === "VERSION") event.ports[0]?.postMessage({ version: VERSION, commit: COMMIT });
});
