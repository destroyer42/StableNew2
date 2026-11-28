# PHONE-CORE: the phone review page as modules, an installable app, and offline use

Status: **design approved with owner answers (section 8, 2026-11-27), not built.** The direction was approved by the owner on 2026-11-27: "Build out a
robust design and plan to best: structure, organize, architecture, and build out the installable web-app with offline
support." This package is documentation only. Each slice in section 7 is its own work package, PR and session.

Related: [RG-100](RG-100_phone_review_gateway.md) (decisions, invariants, S1 to S13),
[REVIEW_GATEWAY.md](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md) (living behaviour),
[PHONE-FAST](PHONE-FAST_phone_review_speed.md), [RG-170](RG-170_phone_rating_tab.md),
[DEPLOY-PROXMOX](DEPLOY-PROXMOX_containers.md), RG-160 (`RG-160_offline_phone_queue.md` on branch `claude/rg-160-2`)
and NAME-INFO (`NAME-INFO_output_names_and_more_info.md` on branch `claude/name-info-e73186`).

## 0. Repository identity and evidence

- Repository `destroyer42/StableNew2`. Branch `claude/phone-core-design-207a07`, fast-forwarded to `origin/main`
  `76b9ddcd` (PR #488, PHONE-FAST k, merged).
- Open branches read, not merged: `claude/rg-160-2` at `a4bd7be1` and `claude/name-info-e73186` at `5d24db0a`, both
  local and not pushed.
- Read: `AGENTS.md`, `docs/ai/workflows/DESIGN_REVIEW.md`, `REVIEW_GATEWAY.md`, RG-100, the DEPLOY-PROXMOX deployer
  design, `.github/workflows/ci.yml`, `phone_app.py` and `web.py`, all of `static/` on main, and the static and
  `phone_app.py` diffs of both open branches.
- Evidence limits:
  - No browser was run (this session was told not to).
  - Browser facts in section 2.2 come from vendor documentation and one public user report. Where they are not
    verified on the owner's phone, they say so.
  - Nothing here was measured on the live gateway.

What the current page is (main `76b9ddcd`):

| File | Lines | Shape |
|---|---|---|
| `static/app.js` | 1,924 | One classic script with about 130 top-level functions and about 40 top-level mutable bindings. It holds the router, API, outbox, every screen, compare, actions and the update screen. |
| `static/rating.js` | 532 | A classic script with the global `Rating`. It calls app.js globals (`el`, `show`, `api`, `toast`, `idempotencyKey`) at run time. |
| `static/app.css`, `rating.css` | 331, 55 | Global stylesheets. |
| `static/index.html` | 26 | Two `<link>` and two `<script defer>` tags. Every static file is listed by hand in `phone_app.py` `_PAGES` and served `Cache-Control: no-cache`. |

The open branches add the same pattern again:

- RG-160 adds `queued.js` (466 lines, global `Queued`). It reads app.js's `readList`, `QUEUE_KEY`, `STATUS_STALE_MS`,
  `canQueue` and `loadScopes`, and is called from 14 places inside app.js.
- NAME-INFO adds `moreinfo.js` (32 lines, global `MoreInfo`).

Both edit app.js in the same functions (`infoPanel`, `renderCompare`, `actionRow`, `showHome`), which is why the four
parallel sessions of 2026-11-27 conflicted.

One merge artefact on main shows the cost. `app.js` declares `function ago` twice (lines 1625 and 1657). In a classic
script the second silently wins, so the Update screen shows "NaN days" (RG-160 reported this). In an ES module the
duplicate is a `SyntaxError`, so slice PC-1 must rename it first.

## 1. Problem, invariants and alternatives

### 1.1 The decision

How to structure, ship and test the phone page so that:

- parallel sessions stop colliding;
- the page installs as an app;
- the page opens and queues work with no network;
- a real browser proves it in CI;
- a change can be tried on the phone before production.

All of this keeps RG-100's server, security model and sync contract.

### 1.2 Invariants that bind every slice

1. RG-100 invariants 1 to 6 are unchanged. The gateway is a projection and outbox. The phone page never decides,
   admits or applies anything. The PC stays authoritative.
2. The security controls S1 to S13 are unchanged:
   - an HttpOnly device cookie;
   - the `X-Review-Gateway` header on every JSON API;
   - CSP `default-src 'self'` with `require-trusted-types-for 'script'`;
   - text only through `textContent`;
   - originals `private, no-store`;
   - no CDN.
3. No build step. The files in `static/` are the files the phone runs. There is no bundler, transpiler or `node_modules`
   in the gateway, and nothing is generated into the repository.
4. One outbox model on the phone (section 3.5). No second queue authority. The gateway outbox and the PC ledger keep
   their roles.
5. Phone API changes stay additive for at least one release, because an installed app can keep running the previous
   shell until its owner reloads it.
6. Warn, don't block (N1). An update, a full cache or a stale view is a notice, never a lock-out.

### 1.3 Alternatives considered

| | Approach | For | Against | Verdict |
|---|---|---|---|---|
| A | **Minimal.** Keep classic scripts and add more namespaced globals (the RG-160 and NAME-INFO pattern). Add a service worker. | Smallest change. | Nothing enforces boundaries. Load order is coupling. Globals collide (`ago`). The features still edit app.js's functions to hook in. | Rejected. It is the cause of the conflicts. |
| B | **Native ES modules, no build.** A small core, one directory per feature, named extension slots so features never edit each other, and versioned module URLs written by the server. | No toolchain. CSP-compatible as is. The import graph is checkable by a cheap test. It migrates in slices. | Needs a server change to version URLs, and some discipline (slot registry). | **Recommended.** |
| C | **A framework and bundler** (for example Preact and Vite). | Components, hot reload. | A build step and a large dev-dependency tree (supply chain, S10). Generated assets must be committed or built at deploy. It is a big-bang rewrite. | Rejected. |

The service worker, offline queue and e2e tests are the same under A and B. B is chosen for the module structure.

## 2. Architecture

### 2.1 Module layout and loading

```
services/review_gateway/review_gateway/static/
  index.html               template: the server writes the version and the feature list into it
  sw.js                    the service worker (served at /sw.js, scope /)
  manifest.webmanifest     served at /manifest.webmanifest
  icons/                   icon.svg, icon-192.png, icon-512.png, maskable-512.png (committed binaries)
  core/                    the core: one owner at a time (section 2.4)
    main.js                boot: start the core, import every feature, start the router
    dom.js  api.js  session.js  router.js  store.js  bus.js  settings.js  media.js
    outbox.js  idb.js  status.js  slots.js  sw-client.js  text.js  core.css
  features/
    inbox/      home, sections, run grid, scroll restore, "keep the rest", "delete this run"
    triage/     the triage stream, swipes, undo, item view, full-resolution viewer and zoom
    compare/    rework and desk-input compare (flip, side by side, slider), Keep original / rework / both
    actions/    the action row, words, pickers, summary sheet, receipts (RG-140)
    queued/     RG-160: queue when the PC is back, the waiting list, the choice catalog
    rating/     RG-170: the To rate tab
    info/       NAME-INFO: More info lines
    status/     PC status lines and the admin Update the PC screen (LAUNCH-UPDATE-2)
    pairing/    the pairing screen and re-pair (section 4)
    offline/    the offline review pack (PO-2)
  each feature: feature.js (entry), any helper .js files, an optional <id>.css
```

**Loading under the current CSP.**

- `index.html` loads one module: `<script type="module" src="/s/<v>/core/main.js">`. `script-src 'self'` allows it,
  so no CSP change is needed for modules. Module scripts are deferred and strict by default.
- Import maps cannot be used. An inline `<script type="importmap">` is inline script, and external import maps are not
  supported. Every import is a relative specifier (`../../core/api.js`). Because every file of a version lives under
  the same `/s/<v>/` prefix, relative imports resolve inside that version and cannot mix versions.
- `main.js` imports the features named in `<meta name="rg-features" content="inbox,triage,...">` with dynamic
  `import()` at boot, before the first route renders. `import()` is not a Trusted Types sink and is allowed by
  `script-src 'self'`. The server writes the meta tag from the directories it finds (2.2). No shared registry file
  exists for parallel sessions to collide on.
- Feature stylesheets are `<link>` tags the server writes into the template, in feature order.
- `index.html` keeps static text in `<main id="view">` ("Loading. If this stays, pull down to reload."). The text is
  replaced once the core boots, so a failed module load is never a blank page (CSP forbids an inline error handler).

**Cache-busting without a build step.**

- At process start, the phone app walks `static/` once. It builds a closed table from published path to
  (file, media type, SHA-256), allowing only `.js`, `.css`, `.png`, `.svg` and `.webmanifest`.
- The version `<v>` is the first 12 hex digits of a SHA-256 over the sorted (path, file digest) pairs, so it changes
  exactly when a static byte changes.
- The commit comes from the release's `source.json` (written by the DEPLOY-1 installer), or `dev` when none exists.
- `GET /s/<v>/<path>` is answered only from that table, never by joining the request path to the filesystem (no path
  traversal). Its headers are `Cache-Control: public, max-age=31536000, immutable`. Any other `<v>` gets 404.
- `GET /` renders `index.html` with the version, feature list and stylesheet links, served `no-cache`.
- `GET /s/<v>/files.json` lists every published path with its SHA-256, for the service-worker precache.
- `GET /sw.js` is `sw.js` with one line put in front of it, `const VERSION = "<v>", COMMIT = "<sha12>";`, served
  `no-cache` with a JavaScript media type. Its bytes therefore change on every static change, which is what triggers the
  browser's update check (2.3).
- `GET /api/session` gains `static_version` and `commit` (additive).

This is string substitution in the server, computed once at start. It is not a build. Development, tests, staging and
production all use the same code path. The previous hand-listed `_PAGES` table is removed.

Every feature module is imported at boot (no lazy loading after start). A running page therefore never asks for a file
of a version the server no longer has. The service worker's precache (2.3) also covers an installed app across a
deploy.

### 2.2 The core and its public interface

`core/main.js` builds one `core` object and hands it to each feature's `start(core)`. Features never construct core
pieces themselves.

| Module | Public interface | Owns |
|---|---|---|
| `dom.js` | `el(tag, options, children)` (text only, no markup sink), `show(heading, canGoBack, ...nodes)`, `toast(text)`, `sheet(...nodes)`, `closeSheet()` | The header, view, toast and sheet nodes |
| `api.js` | `api.get(path)`, `api.post(path, body)` resolve to JSON or throw `ApiError {status, code, kind}`. `kind` is `offline` (no response), `unpaired` (401), `forbidden` (403), `retry` (429 other than `too_many_pending`, 5xx, unreadable reply) or `refused` (other 4xx, `code` from `{"error"}`). | The only `fetch` of JSON. It always sends `X-Review-Gateway: 1`, `credentials: "same-origin"` and `cache: "no-store"`. A 401 is reported once to `session`. |
| `session.js` | `state`, `scopes`, `can(scope)`, `pair(code, label)`, `onChange(fn)` | The pairing state machine below |
| `router.js` | `route(pattern, render)`, `go(hash)`, `current()`; `render(params, view)` gets `view.alive()` (the existing render-serial guard) | Hash routing, back, the render serial, scroll save and restore (moved from inbox) |
| `store.js` | `items(groupId)`, `item(key)`, `setGroup(groupId, items, name)`, `groupName(id)`, `patch(key, fields)`; emits `items:changed` | Item rows read from the gateway, with the outbox overlay applied (`overlayUnsent` today) |
| `bus.js` | `on(topic, fn)`, `off`, `emit`; topics are a frozen list in `bus.js` | Notifications only, never return values |
| `slots.js` | `contribute(slot, fn)`, `render(slot, ctx)` returns nodes in feature order; `ask(hook, ctx)` returns every feature's answers in order; `claim(hook, ctx)` returns the first feature that took it | Named extension points (table below) |
| `settings.js` | `settings.for(featureId)` returns `{read(name, fallback), write(name, value)}` | Per-phone settings in `localStorage` under `rg.<feature>.<name>`, with a memory fallback |
| `media.js` | `url(item, variant)`, `best(item)` (rendition choice), `element(item)`, `prefetch(items)` | Media URLs and the loader. The service worker does the caching (2.3). |
| `outbox.js` | `enqueue({kind, path, body, target, heldUntil, coalesce})`, `release(keys)`, `undo(keys)`, `retry(key)`, `dismiss(key)`, `counts()`, `entries()`, `onChange(fn)` | The phone outbox (section 3). It is the only writer of unsent work. |
| `status.js` | `latest()`, `refresh()`, `pcAway()`, `reachable()` | `GET /api/status` (one route, per PHONE-FAST and RG-160), gateway reachability, PC last seen |
| `sw-client.js` | `register()`, `onUpdate(fn)`, `applyUpdate()`, `persist()`, `repair()` | Service-worker registration through a Trusted Types policy (2.3), the update banner, storage persistence |
| `text.js` | `runName`, `ago`, `since`, plural helpers | Shared wording (one `ago`) |

**Session and pairing state machine** (`session.js`):

```
unknown --GET /api/session ok--> paired(scopes)
unknown --401--> unpaired --pair ok--> paired
unknown --no network, last snapshot paired--> paired_offline(scopes from IndexedDB snapshot)
paired <--reachability--> paired_offline        (status.reachable())
paired | paired_offline --401 from any call--> revoked_or_lost --> unpaired
any --403 not_granted on /api/session--> forbidden
```

- On `revoked_or_lost` the core emits `session:lost`. The service worker deletes the media cache and the offline pack
  (section 4.3). The outbox is kept, and goes again under the next pairing.
- `paired_offline` is what makes an offline cold start work. The last session (device id, label, scopes, static
  version) is kept in IndexedDB `meta`, never the cookie, which stays HttpOnly.

**Extension slots and hooks.** These replace every place where one feature calls another today:

| Name | Kind | Host (renders it) | Contributors today |
|---|---|---|---|
| `home.top` | slot | inbox | status (PC lines), queued (waiting line), rating (To rate button), offline (offline pack) |
| `home.bottom` | slot | inbox | status (Update the PC…) |
| `header.badges` | slot | core | queued ("N from PC") |
| `tile.marks` | slot | inbox | queued (waiting mark) |
| `item.status` | slot | triage, compare | queued (suffix) |
| `item.info` | slot | triage, compare | info (More info lines) |
| `item.tools` | slot | triage, compare | actions (the action row) |
| `item.view` | claim | triage | compare claims an item with a parent or desk input |
| `action.open` | claim | actions | queued claims the action when the PC is away or a prepare times out (RG-160 `offer`, `unreachable`) |
| `delete.warn` | ask | inbox, triage, compare | queued ("N have a request waiting. Deleting cancels it.") |
| `items.overlay` | ask | core store | queued (RG-160 `overlay`) |

The slot table is in `core/slots.js`. Adding a slot is a core change. PC-1b defines every slot above, so the feature
extractions in PC-2 need no core edit.

**Feature interface.** Every feature has one entry file:

```js
// features/<id>/feature.js
export default {
  id: "compare",               // equals the directory name
  order: 40,                   // slot and stylesheet order
  routes: [],                  // [{ pattern: "#/rate/:task/:item?", render }]
  start(core) {                // subscribe, contribute to slots, claim hooks
    core.slots.claim("item.view", (ctx) => (ctx.item.parent || ctx.item.input ? renderCompare(core, ctx) : null));
  },
};
```

**Route ownership.**

| Route | Owner |
|---|---|
| `#/`, `#/section/:id`, `#/run/:id` | inbox |
| `#/triage/:run/:item?` | triage (compare renders inside it through `item.view`) |
| `#/rejected`, `#/waiting` | core (one outbox screen, section 3.6) |
| `#/requests` | queued |
| `#/rate/...` | rating |
| `#/update` | status |
| `#/pair/:code?` | pairing |
| `#/offline` | offline |

**The one boundary rule.** A file under `features/<a>/` may import only from `features/<a>/` and `core/`. It never
imports from another feature. Features talk only through `core.bus`, `core.slots` and `core.store`.

A pytest check (`tests/review_gateway_service/test_static_rules.py`, cheap, regex over `import` statements) enforces:

- the import boundary rule;
- no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` or `new Function`;
- no `on*=` attributes in HTML;
- the file-size caps (2.4).

During the migration, a feature may name temporary cross-imports in its own `feature.js`
(`export const legacyImports = [...]`). The check accepts those, and each PC-2 slice must remove its own. The list sits
in the feature's own file so that no shared allowlist exists.

### 2.3 Installable app: manifest and service worker

**Manifest** (`/manifest.webmanifest`, `application/manifest+json`, public like the rest of the shell):

```json
{"id": "/", "name": "StableNew Review", "short_name": "Review", "start_url": "/#/", "scope": "/",
 "display": "standalone", "orientation": "portrait", "background_color": "#101216", "theme_color": "#101216",
 "icons": [{"src": "/s/<v>/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
           {"src": "/s/<v>/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
           {"src": "/s/<v>/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
```

`index.html` adds `<link rel="manifest" href="/manifest.webmanifest">`. `manifest-src` falls back to
`default-src 'self'`, so the CSP needs no change. The PNG icons are committed binaries, drawn once from `icon.svg`.
Chrome needs raster icons of at least 144 px to mint a WebAPK.

**Install path on Android Chrome.**

1. With Tailscale on, open the gateway's tailnet HTTPS name in Chrome.
2. Pair (the cookie is set in Chrome's profile).
3. Choose ⋮ › **Install app**, or tap the install banner. Chrome mints a WebAPK: an app icon, its own task in Recents,
   standalone display.
4. Links and QR codes inside the scope then open in the app.

**DuckDuckGo, honestly.** Unverified on the owner's phone. Slice PC-0 asks for one five-minute check.

- DuckDuckGo for Android does not install web apps. Its "Add to Home screen" makes a shortcut that opens the page in
  DuckDuckGo, with no WebAPK and no standalone window. The evidence is a public user report that DuckDuckGo offered a
  shortcut where Chrome offered Install, and its shortcut-install permission. No DuckDuckGo document says it installs
  web apps.
- The shortcut does not protect anything. DuckDuckGo's Fire button and automatic clearing delete cookies and site
  storage for every site that is not Fireproofed. That is why the pairing was lost on 2026-11-27: the cookie and the
  localStorage outbox went together.
- DuckDuckGo renders with Android System WebView. WebView runs service workers but has no Background Sync, so even
  where the shell works there, queued work goes only while the page is open (the section 3.3 fallback).

**Does an installed Chrome app keep its storage?**

- A WebAPK stores its data in Chrome's profile and is not separated from Chrome. Clearing Chrome's site data for the
  gateway, or the whole Chrome profile, clears the app's cookie, IndexedDB and caches too.
- `navigator.storage.persist()` protects only against eviction under storage pressure, not against the owner clearing
  data. Chrome grants it without a prompt using signals such as installation.
- Chrome never clears site data on its own schedule, which DuckDuckGo does. So installing in Chrome removes the cause,
  not the possibility. Recommended default: owner decision OD-1.

**Service worker: registration, scope and the security model.**

- `/sw.js` at scope `/`, registered with `updateViaCache: "none"`, so the browser asks the network for `sw.js` on every
  navigation and at least every 24 hours.
- Under `require-trusted-types-for 'script'`, `navigator.serviceWorker.register()` requires a `TrustedScriptURL`.
  `sw-client.js` creates the one policy, `rg-sw`, whose `createScriptURL` accepts exactly `/sw.js` and throws
  otherwise.
- The CSP gains `trusted-types rg-sw`, so no other policy can be created. That is the only CSP change. `worker-src`
  falls back to `script-src 'self'`.
- **The cookie.** The service worker cannot read it (HttpOnly). Requests it passes through, and requests it makes
  itself, are same-origin, so the browser attaches `rg_session` (SameSite=Lax is satisfied). The token never enters
  JavaScript, IndexedDB or a cache.
- **The header.** The service worker never adds `X-Review-Gateway` to a request it did not create. It sets the header
  only on the outbox sends it makes itself (3.3). CSRF protection is unchanged: a cross-site form still cannot send
  the header.
- **The CSP.** `sw.js` is served through the same `_Guard`, so the worker runs under the same `connect-src 'self'`.

**Cache strategy, per resource class.**

| Class | Requests | Strategy | Stored |
|---|---|---|---|
| App shell | navigations to `/`, `GET /s/<v>/*` (modules, CSS, icons), `/manifest.webmanifest` | **Precached** at install from `/s/<v>/files.json`, each file checked against its listed SHA-256 before the cache is committed. Cache-first. A navigation is answered with the precached `index.html` of the active worker's version, so page, modules and worker always share one version. | `rg-shell-<v>`. The previous version's cache is deleted when the new worker activates. |
| Authenticated JSON | `/api/*`, `/rating-media/*` | **Network only**: the worker does not call `respondWith`, so the browser fetches normally. Never in any cache. The page keeps its own app data in IndexedDB where offline needs it (3.1, 3.4). | none |
| Renditions | `GET /media/<lib>/<sha>/thumb` and `/preview` | **Cache-first, bounded LRU.** Stored only when the response is a same-origin `basic` 200 with an `image/*` type. The URL names the original's SHA-256 and the server serves these as immutable (PHONE-FAST), so a URL never changes meaning. | `rg-media-1`, with an LRU index in IndexedDB `media` (url, bytes, stored_at, used_at, decided) |
| Mobile video | `/media/.../video` | Network only (browser HTTP cache as today, `max-age=3600`). Video uses Range requests, which the Cache API does not serve without synthesising 206 replies. That is deferred (OD-4). | none |
| Originals | `/media/.../original` | **Never cached**: network only, `no-store` as today (S6). The worker refuses to `put` any URL ending in `/original`, and a test holds that. | none |

**Rendition cache cap and eviction.**

- Cap 1 GB (OD-2, owner), or half of `navigator.storage.estimate().quota` when that is smaller. A phone rendition is
  at most 1,080 px WebP, typically 150 to 400 KB, so 1 GB holds about 4,000 renditions: several walk-away batches.
- Eviction runs after each `put`, and on activate:
  - entries older than the lifetime (14 days, OD-2, owner) go first. The Cache API does not apply HTTP `max-age`, so
    the gateway's 7-day header does not shorten it; the worker's own lifetime is the rule;
  - then renditions of items already decided;
  - then the least recently used, until the cache is under 90 % of the cap.
- "Matches PHONE-FAST's cap", stated honestly: PHONE-FAST's cap is on the gateway (`cache_warn_gib`, 20 GiB, warn
  only). The phone cap is a separate, smaller bound with the same lifetime. Like the gateway, it never refuses
  anything: when full, the oldest goes.
- The page asks the worker through `postMessage` to mark an item decided, and to prefetch (PHONE-FAST's next 4, and the
  offline pack of 3.4).

**Update flow.**

1. A deploy changes `<v>`, so `/sw.js` changes. On the next navigation, `visibilitychange` or 30-minute timer,
   `registration.update()` finds it.
2. The new worker precaches `rg-shell-<newv>` and waits. It does not `skipWaiting` on its own.
3. The page shows a banner (core, not a feature): **"Update available · Reload"**, with the new commit's first 7
   characters. Nothing is forced (N1).
4. On Reload, the page:
   - releases any held undo (sends it now, as `pagehide` does today);
   - posts `SKIP_WAITING`;
   - reloads on `controllerchange`.
5. If the owner ignores the banner, the new version starts the next time every window of the app is closed.

The version is tied to the deployed commit two ways: `<v>` is derived from the installed files, and `COMMIT` from the
release's `source.json`. The banner and **Settings › About** show both. `review-gateway-deploy status` already reports
the commit, so the PC tool and the phone agree.

**Repair.** **Settings › Repair this app**:

- unregisters the worker;
- deletes `rg-shell-*` and `rg-media-*`;
- reloads.

It keeps the cookie, the outbox and settings. It is the owner's recovery from a bad shell. A broken worker is also
replaced by the next deploy, because the browser checks `sw.js` at least daily and bypasses caches.

## 3. Offline support

### 3.1 What works with no network

| | Works offline | Notes |
|---|---|---|
| Open the app | yes | Precached shell. `session` comes up `paired_offline` from the IndexedDB snapshot. |
| Home | yes, from the snapshot | Last-known sections and counts, marked "as of 14:02". The offline pack line: "42 ready to review offline". |
| Review the offline pack | yes | The next N items to review (3.4): triage, swipes, tags, Keep, Delete, Favorite, Undo. |
| Other lists and grids | the last-seen copy of what the pack holds | Nothing outside the pack is shown offline. "Not available offline" for the rest. |
| Full resolution, video | no | Originals are never cached; videos are not cached (OD-4). |
| Actions | queue only | RG-160 deferred requests (`params.step = "queue"`) with the cached choice catalog. A two-step prepare needs the PC. |
| Ratings | answer, and submit queued | Answers coalesce per (task, item, clip). Submit is queued (OD-9). |
| Update the PC | no | The screen says the gateway is not reachable. |

### 3.2 The outbox store (IndexedDB)

The outbox moves from `localStorage` (`rg.unsent`, `rg.rejected`, `rg.rating.unsent`) to IndexedDB, because a service
worker cannot read `localStorage`.

Database `rg`, version 1:

| Store | Key | Record |
|---|---|---|
| `outbox` | `seq` (auto-increment), unique index `idempotency_key`, index `coalesce` | `{seq, idempotency_key, kind: "decision" \| "action" \| "rating_answer" \| "rating_submit", path, body, target: {library_id, sha256} \| {task_id}, held_until, created_at, attempts, coalesce}` |
| `rejected` | `idempotency_key` | the entry plus `reason` and `rejected_at` ("not saved") |
| `meta` | name | the session snapshot, the RG-160 catalog and PC last seen, the offline pack index |
| `media` | url | the rendition LRU index (2.3) |
| `pack` | item key | the item rows of the offline pack (3.4) |

Rules:

- **Order.** FIFO by `seq`, as today: a held (undoable) entry holds the ones behind it, and RG-160's `too_many_pending`
  is set aside rather than blocking.
- **Coalesce.** A rating answer replaces the waiting entry with the same `coalesce` (task, item, clip); latest wins,
  as RG-170 does now.
- **One sender at a time.** Page tabs and the worker flush under `navigator.locks.request("rg-outbox")`. Changes are
  announced on `BroadcastChannel("rg-outbox")`, which replaces the `storage` event.
- **Migration.** On every boot, and on `storage` events (an old tab may still write), the core moves any
  `rg.unsent`, `rg.rejected` or `rg.rating.unsent` content into IndexedDB in one transaction. It keeps idempotency keys
  and skips keys already present, then deletes the `localStorage` key after the transaction commits. Nothing is sent
  twice (same key, so the gateway answers with the first record) and nothing is dropped.
- **Unusable storage.** If IndexedDB cannot be opened (a private window), the outbox lives in memory for the page's
  life, as today. The header says "not saved on this phone".

### 3.3 Sending: Background Sync and its fallback

- Every `enqueue`, a failed send of kind `offline` or `retry`, and `pagehide` register a one-off sync
  (`registration.sync.register("rg-outbox")`).
- The worker's `sync` handler flushes under the lock. It uses `fetch(path, {method: "POST", credentials: "same-origin",
  headers: {"X-Review-Gateway": "1", "Content-Type": "application/json"}})`, and applies the page's exact answer
  mapping (it shares `core/outbox-send.js`, a module both import):
  - 2xx: done;
  - 401: stop, and mark the session lost;
  - `retry` or `offline`: reject the sync promise, so the browser retries;
  - `refused`: move the entry to `rejected`.
- A held entry whose `held_until` is still in the future is not sent. `pagehide` sets `held_until` to now first, so an
  undo window cut short by closing the app is still sent by the worker after the page is gone.
- **Fallback, always on.** Background Sync is Chrome-only, fires on *connectivity* and not on *gateway reachability*,
  and gives up after a few attempts. A phone with mobile data but Tailscale off has connectivity and no gateway. So the
  page also flushes:
  - at boot;
  - on `online`;
  - on `visibilitychange` to visible;
  - on `focus`;
  - on every 20-second refresh;
  - with backoff from 2 to 30 s while open (today's behaviour).

  WebView browsers (DuckDuckGo) use only this path.

### 3.4 The offline review pack

- While online and idle, the offline feature keeps the next N items of "Review all" (300 images, OD-3, owner; about 75 to 120 MB).
- It stores their rows in IndexedDB `pack` and asks the worker to cache their `preview` renditions (and `thumb` for
  grids).
- The pack refreshes on each home load and drops items that were decided.
- It shares the media cache's lifetime and cap, so it is not a second cache. The rows hold `display` text (prompt
  excerpts, model names), so they are wiped with the media (4.3).
- This is app data under the page's control, not a cached API response. It is the only authenticated data at rest
  besides renditions.

### 3.5 One queue model: phone-offline and PC-away are layers of one outbox

| Layer | Where | Holds | Leaves it when | The owner sees |
|---|---|---|---|---|
| **L1 phone outbox** | IndexedDB `outbox` | Everything the gateway has not accepted yet: decisions, RG-160 deferred actions, rating answers and submits | The gateway answers 2xx (to L2), or refuses (to `rejected`: "not saved") | **"3 waiting to send"** |
| **L2 gateway outbox** | Gateway SQLite (unchanged) | Records the PC has not answered. PC-away is simply L2 waiting. RG-160's `step: "queue"` requests live here and never expire. | The PC acknowledges `applied` or `refused`, or the phone cancels (RG-160) | **"5 waiting for the PC"** (from `/api/status`'s waiting count and per-item states) |
| **L3 PC ledger** | StableNew (unchanged) | Receipts, job ids, refusals | n/a | ✓ applied, or ! refused with the PC's reason, per item and in the RG-160 receipts list |

- One identity runs through all three: the `idempotency_key` is made once on the phone at the tap, kept through L1
  retries, and is the gateway's unique key per device. The `record_id` is assigned at L2 and carried in the PC's
  receipt.
- RG-160 already puts deferred actions into the same `rg.unsent` list as decisions (its `Queued.add` writes
  `QUEUE_KEY`). PHONE-CORE moves that list to IndexedDB and adds the worker sender. It changes nothing in L2 or L3 and
  nothing in RG-160's contract.
- The waiting-for-PC decision ("is the PC away?") stays RG-160's `pc_seen_at` rule, read through `core/status.js`.

### 3.6 What the owner sees

- One header pill, owned by the core, with the most urgent line: "1 not saved" (tap: the list with Try again and
  Dismiss, as today), else "3 waiting to send", else "5 waiting for the PC".
- Offline banner: "Offline: decisions are kept on this phone and sent when the gateway is back."
- `#/waiting` lists L1 and L2 together, grouped by layer, with cancel where RG-160 allows it.
- If storage is not persistent (`navigator.storage.persisted()` false), **Settings** says "This phone may clear saved
  work under storage pressure. Install the app in Chrome to keep it." This is a warning, not a block.

### 3.7 Conflicts: an item that changed meanwhile

- **Gone or changed on the PC.** The existing refusals cover this (`unknown_item`, `digest_mismatch`, purged). The entry
  goes to "not saved" with its reason, or shows the PC's refusal, never silently.
- **Re-decided elsewhere** (a second phone, or this phone in another tab, while this one was offline). Today the later
  arrival at the gateway wins (rule 6), so a decision made hours ago offline can overwrite a newer one. Proposed, an
  additive phone-API field (no sync schema change): a decision carries `based_on`, the item's `latest_record_id` (or
  `null`) as the phone last saw it.
  - The gateway refuses with 409 `decision_changed` only when the item's latest record differs and came from another
    device.
  - The phone shows "Changed on another phone: Use mine / Keep theirs".
  - Default on (OD-8). It is rare for a single owner, but offline windows make it likelier.
- **Actions.** RG-160 and RG-140 already re-check device, grant, item and digest on the PC at arrival. Nothing new.

## 4. Pairing robustness and threat review

### 4.1 Recovery when storage is cleared

The cookie is the device's only credential. When the browser clears site data, the phone is a stranger. Nothing on the
phone can survive that clearing (an IndexedDB key, a non-extractable WebCrypto key, or a cache would go with it), so
recovery means pairing again, made quick:

1. **Remove the cause:** install in Chrome (OD-1). Chrome does not clear on a schedule.
2. **QR re-pair** (slice PP-1, small):
   - The desktop pairing dialog shows the code and a QR of `https://<gateway tailnet name>/#/pair/<CODE>`.
   - The code sits in the fragment, which is never sent to the server and never logged.
   - The pairing feature reads it, puts it in the form, and removes it with `history.replaceState`. The owner taps
     **Pair**.
   - A scan opens the installed app, because a WebAPK takes the links in its scope.
   - The code keeps every RG-100 property: single use, 5 minutes, attempt caps.
3. **Keep the outbox.** Unsent work survives a 401 and is sent under the new pairing. It cannot survive clearing
   (residual R2).
4. **Stale device rows.** Each pairing is a new device. The desktop list should show each device's last-seen time, so
   the owner revokes the ones that lost their cookie. That needs a `last_seen_at` in `enrolled_devices`, which is
   additive.

**A longer-lived credential: not recommended** (OD-5).

| Option | Why not |
|---|---|
| A longer cookie | The cookie already lasts a year. Expiry is not the failure. |
| A recovery secret the owner keeps in a password manager | A new bearer secret that works from any tailnet device, can be phished and is long-lived. It weakens S1 and D5 (enrolment only from a desktop code). |
| A passkey (WebAuthn) registered at pairing, used to re-enrol | Phishing-resistant and survives clearing. But a synced passkey works on every device signed in to the owner's Google account, and it enrols without the PC, which changes D5. Worth reconsidering only if a Chrome-installed app still loses pairing. |

### 4.2 Threat review (security-review checklist)

Trust boundaries:

- the phone's browser profile (page, worker, caches, IndexedDB);
- the tailnet path to the gateway;
- the gateway's phone listener;
- the root deployer;
- CI.

Attacker capabilities considered:

- someone holding the owner's phone (locked, or unlocked);
- a page script injected through rendered metadata (XSS attempt);
- a compromised gateway service user;
- a session or contributor handing over a branch or SHA;
- CI dependencies.

| # | Class | Severity | Precondition | Affected | Control (required) |
|---|---|---|---|---|---|
| T1 | Media at rest | Medium | Lost or seized phone, unlocked or forensically read | `rg-media-1`, IndexedDB `pack` | Originals and video never cached. Renditions bounded (OD-2: 14 days, 1 GB). Wiped on 401 (4.3). Android file-based encryption and the lock screen are the at-rest protection. No authenticated JSON in any HTTP cache. |
| T2 | Revocation of a lost phone | Medium | Phone lost | session, caches | Revoke on the desktop or console (S11). The owner removes the phone from the tailnet, so the gateway is unreachable at all. At the next contact the 401 wipes caches. **Residual R1:** a phone that never reconnects keeps its renditions until their 14-day lifetime runs out, and only while the app is opened (eviction is local, clock-based and can be defeated by changing the clock). No web platform offers remote wipe. Accepted by the owner (OD-6). |
| T3 | Cache poisoning | Low | A wrong or partial response stored as a rendition or shell file | `sw.js` put rules | Only same-origin `basic` 200 responses with an `image/*` type, for the two rendition URL patterns. Shell files are verified against `files.json` SHA-256 before the precache commits. URLs are content-addressed and immutable. Nothing is stored from a redirect or error. |
| T4 | A persistent malicious worker after a gateway compromise | Medium (no new exposure) | Gateway code execution | worker lifetime | A compromised gateway already controls the page. The worker adds persistence until the next check: `updateViaCache: "none"`, at most 24 h, Repair, and the fixed deploy replaces it. The deployer installs only GitHub-signed `main` commits (DEPLOY-PROXMOX decisions 3 and 4). |
| T5 | Worker registration hijack through injected script | Low | XSS despite CSP | `register()` | The Trusted Types policy `rg-sw` allows only `/sw.js`. CSP `trusted-types rg-sw`. `sw.js` is served only by its fixed route with a JavaScript type. Media routes send image types with `nosniff`, so they cannot be registered. Text still goes only through `textContent`. |
| T6 | Credential exposure | Low | n/a | cookie | HttpOnly, never readable by page or worker. Nothing token-like in IndexedDB, caches, logs or the fragment. The pairing code in a QR fragment is single-use and expires in 5 minutes. |
| T7 | Forged requests (CSRF) | Low | A cross-site page | `/api/*` | Unchanged: the header is required. The worker never adds it to requests it did not create. |
| T8 | Data loss: outbox migration or clearing | Medium | A boot during the migration, or the owner clearing data | `outbox` | The copy-then-delete migration is idempotent by key. `persist()`. The header shows unsent counts. **Residual R2:** clearing site data with unsent work loses it (the gateway never saw it). |
| T9 | Path traversal on versioned static routes | Low | A crafted `/s/<v>/../...` | server static table | Lookups only in the closed table built at start. No filesystem join. A test sends traversal and encoded forms. |
| T10 | CI supply chain and secret scope | Low | A compromised dev dependency | e2e job | Playwright pinned by hash in a separate `requirements-e2e.txt`. The browser is downloaded by Playwright's pinned version and cached by that key. The e2e job has `contents: read` and no secrets. The page itself still loads nothing from a CDN (S10). |
| T11 | Staging crosses into production | Medium | A shared host or cookies | section 6 | A separate container and tailnet name: cookies are per host, not per port. Its own sync secret and pairing. No Immich key. Fixture data only; it is never synced from the real PC. |
| T12 | Deployer target injection | Low | A crafted `--target` | deploy tool | A closed set (`production`, `staging`). Never a path, shell string or ref. Argument-list calls only, as DEPLOY-PROXMOX T3. |

Required fixes are the controls in the table. Defense in depth, not required:

- a page-visible "Wipe this phone's cached media" button in **Settings**;
- a `Clear-Site-Data: "cache"` reply on a successful re-pair, to drop anything left from before.

### 4.3 What a 401 does

1. `api.js` reports it.
2. `session` goes to `revoked_or_lost` and emits `session:lost`.
3. The worker deletes `rg-media-*` and the `pack` and `media` stores.
4. The pairing screen shows.
5. The outbox, `rejected` and settings stay.

A 401 is authoritative because only the gateway says it. A network failure never wipes anything.

## 5. Testing

### 5.1 Browser e2e (Playwright, headless Chromium)

**Toolchain.**

- Playwright for Python, so the tests are pytest tests next to `tests/review_gateway_service/`, reusing its fixtures.
- In `tests/phone_e2e/` with a `phone_e2e` marker. `pyproject.toml` deselects it by default, so the ordinary census and
  the Windows lane are unaffected.
- Pins in `requirements-e2e.txt` (hash-pinned).

**The test gateway (fixture).**

- The real phone app and real sync app run under uvicorn on loopback, on random ports, with a temporary data
  directory. No container and no network.
- `http://127.0.0.1` is a secure context, so service workers run. Chromium accepts `Secure` cookies from localhost. If
  a pinned version does not, the fixture serves TLS with a throwaway certificate and the context uses
  `ignore_https_errors`.
- The fixture stops and restarts the server to make the gateway unreachable (realistic for "Tailscale off").

**Seeding.** A seeder module posts fixtures through the real sync API with the fixture's sync secret:

- manifests;
- 12 small generated images with thumb and preview renditions;
- one video;
- a batch;
- a rework parent and child;
- a desk input;
- a rating task;
- a pairing offer with a known code.

It plays the PC through the sync API: list the outbox, acknowledge records, answer action prepares with a canned
summary, publish a catalog, send `pc_status`. The same seeder feeds staging (section 6).

**Device emulation.** A Pixel-class context: 412×915, `is_mobile`, `has_touch`, device scale 2.6. Swipes go through
CDP `Input.dispatchTouchEvent`, which produces the pointer events (`pointerType: "touch"`) the page listens for.

**Journeys.**

PC-0 covers today's page:

- pair;
- home sections and badges;
- Review all, with swipe Keep, Delete and Favorite, tags and Undo;
- run grid with Keep the rest and Delete this run;
- compare flip, side by side and slider, then Keep original and Keep rework;
- an action, from prepare through summary and Queue to the receipt;
- Not saved, with Try again;
- To rate, answering an item;
- the admin Update screen (which catches the `ago` bug);
- a 401 shows pairing.

Later slices add:

- install criteria (manifest valid, worker controls the page);
- offline cold start from the precached shell;
- offline swipe of 5 items, then back online: sent once, with the same idempotency keys (asserted on the gateway's
  store);
- held undo plus closing the page, then sent by the worker;
- Background Sync through CDP `ServiceWorker.dispatchSyncEvent`;
- the update banner (deploy a changed static tree into the fixture, then Reload: the new version is active);
- the rendition cap (a small cap in the fixture: oldest and decided evicted, originals never stored);
- a 401 wipes caches but keeps the outbox;
- RG-160 PC away, queue, PC back, applied;
- the `localStorage` to IndexedDB migration with a pre-seeded old list.

**Offline switch.** Playwright's `context.set_offline(True)` plus stopping the server. Whether `set_offline` covers
service-worker fetches in the pinned Chromium is checked in PC-0. If it does not, the server stop alone is the offline
switch.

### 5.2 Cheap checks kept outside the browser

- `test_static_rules.py` (2.2) covers the import boundary, banned sinks and file-size caps. It is pure Python and runs
  in the census and on Windows.
- Server tests for the new routes go in `tests/review_gateway_service/` (ASGI client):
  - `/s/<v>/` table and traversal refusal;
  - template substitution;
  - `files.json` digests;
  - `/sw.js` prefix;
  - CSP `trusted-types`;
  - `static_version` in `/api/session`;
  - `based_on`.
- Pure logic (outbox ordering, coalescing, LRU choice, route parsing) is tested in the same headless Chromium with
  `page.evaluate(() => import("/s/<v>/core/outbox.js"))`. It needs no DOM stand-in.
- The Node stand-in checks used by RG-160 and PHONE-FAST were scratch harnesses, never committed. They are replaced,
  not kept: one browser toolchain is cheaper to maintain than a hand-written DOM stand-in.

### 5.3 CI and runtime budget

- A new job `phone-e2e` on `ubuntu-latest`:
  - `needs: required`;
  - runs when the validation plan's new output `phone` is true (any change under `services/review_gateway/` or
    `tests/phone_e2e/`), and on the nightly schedule;
  - Python 3.11, the gateway's production floor;
  - `timeout-minutes: 10`;
  - `permissions: contents: read`;
  - caches `~/.cache/ms-playwright` keyed by the Playwright version.
- It needs no new branch-protection identity: `full-suite` gains `phone-e2e` in `needs`, and fails when `phone-e2e`
  failed (it passes when `phone-e2e` was skipped). Branch protection is unchanged, so no owner settings step is needed.
- Budget: under 4 minutes of wall time warm (install about 30 s from cache, the suite under 120 s). The PC-0
  acceptance records the real numbers. A test is serial per server fixture, with one shared seeded gateway per module.
- Locally: `python -m pytest -m phone_e2e tests/phone_e2e` needs `playwright install chromium` once. It is not part of
  `run_pr_gate.py`, which stays browser-free.

## 6. Staging gateway (deferred, OD-7)

**Deferred by the owner on 2026-11-27 ("Not now").** PS-1 is not scheduled. The design below is kept for when it is
wanted. Until then, pre-merge evidence is CI's `phone-e2e` and changes land on production directly, as today.

**Topology: a second container, not a second instance** (OD-7). Cookies are scoped by host, not port.

- A second instance on the production container, published on another `tailscale serve` port, would receive the
  production `rg_session` cookie. Unreviewed staging code could read the token and use it against production.
- A second instance would also share the root deployer, the data disk and the Immich key file's host.

| | Production (CT 120, today) | Staging (new CT 121) |
|---|---|---|
| Tailnet name | the existing gateway name | its own, for example `review-staging` (owner chooses) |
| Data | real items synced from the PC | fixtures only, from the e2e seeder. The PC's sync worker is never pointed at it. |
| Immich | the configured key | none (`immich_url` unset). Keeps wait, as designed. |
| Sync secret, pairing | its own | its own. A phone pairs separately. On the phone it is a second installed app with a different origin, so storage is separate. |
| Deployer | `review-gateway-deploy`, main commits only | the same deployer and rules (OD-7) |

**How the deployer targets it.**

- `python -m tools.review_gateway_deploy --target staging request <sha>`. `--target` is a closed set, default
  `production`.
- The staging address, pinned certificate and sync secret are stored with DPAPI in a separate settings file that only
  the tools read (`GatewaySettingsStore(name="staging")`). The app's own sync settings are untouched, so the app can
  never sync to staging.
- `python -m tools.review_gateway_stage seed` loads the fixture set through staging's sync API. `... reset` purges it
  through the admin CLI over the console. Both refuse `--target production`.

**Landing and promotion.**

1. A phone PR goes green in CI, including `phone-e2e`, then merges to `main`.
2. Deploy the merge SHA to **staging**.
3. The owner opens the staging app on the phone: it shows "Staging" in the header, from config.
4. If it looks right, deploy the **same SHA** to production (`--target production`).
5. If it is wrong, a revert PR. Production never got it.

This keeps DEPLOY-PROXMOX's rule that only signed `main` commits are installed as root (F1). Pre-merge evidence comes
from CI's browser. The alternative of letting staging take heads of branches in this repository is OD-7(b): it puts
unreviewed code under root on CT 121, acceptable only because CT 121 holds no secret worth having.

**Owner steps on Proxmox** (the owner does these; a guided session can prepare the commands):

1. Create unprivileged CT 121 from the same pinned template as CT 120. No GPU, small disk (8 GB).
2. Install Tailscale and join it with a tag. `tailscale serve --bg --https=443 http://127.0.0.1:8443`.
3. Install the gateway release with the DEPLOY-1 archive procedure. Run `review-gateway-deploy remote on`.
4. Firewall: the sync port reachable only from the PC, as for CT 120.
5. In StableNew: enter staging's address, certificate fingerprint and sync secret in the tool's staging settings, once
   (`python -m tools.review_gateway_deploy --target staging configure`).

## 7. Migration plan

Ordered slices, each one PR from one session. The core lane is serial; the rest says where parallel work is safe.
Nothing starts in `static/` until **RG-160 (`claude/rg-160-2`) and NAME-INFO (`claude/name-info-e73186`) have merged**.
PC-0 adds only tests and CI, so it can start now on `main`.

| Slice | Scope | Acceptance | Risks | Size | Depends / parallel |
|---|---|---|---|---|---|
| **PC-0 e2e harness** | `tests/phone_e2e/` (fixture gateway, seeder, pairing, device context, swipe helper), the PC-0 journeys of 5.1 against today's page, `requirements-e2e.txt`, the `phone-e2e` CI job wired into `full-suite`, the `phone_e2e` marker in `pyproject.toml`. The one-line `ago` rename if RG-160 has not fixed it. One owner check: install attempt in Chrome and DuckDuckGo (5 min, notes in the PR). | Every journey passes in CI on Linux. Warm runtime recorded under budget. The census and Windows lanes unchanged. `set_offline` versus worker behaviour recorded. | Flaky touch timing (use the page's own state, never sleeps). Python 3.11 wheel for Playwright. | M | Now, on main. Parallel with the RG-160 and NAME-INFO merges. Rebase its journeys once they merge (queued, More info). |
| **PC-1a versioned modules** | Server: static table, `/s/<v>/`, template `/`, `files.json`, `static_version`, removal of `_PAGES`. Page: `app.js`, `rating.js`, `queued.js`, `moreinfo.js` become modules with explicit imports, behaviour-identical. `test_static_rules.py` (banned sinks, traversal). | PC-0 e2e unchanged and green. Server tests for the table and traversal. The module graph loads under the unchanged CSP. | Module semantics: duplicate declarations, implicit globals between files, `this`. Mechanical but must be complete. | M | After RG-160 and NAME-INFO merge. Serial (core lane). |
| **PC-1b core extraction** | Create `core/*` (2.2) and `features/*/feature.js` by moving code verbatim from the modules into their feature directories. Cross-feature calls become slot, hook or bus calls where the slot exists, else `legacyImports`. All slots of 2.2 defined. File caps enforced (core ≤ 300 lines a file, features ≤ 400, hard 500; a temporary exemption list for oversized files must shrink). | PC-0 e2e green with no journey edited. The boundary check passes with only declared `legacyImports`. `git diff --color-moved` shows mostly moves. | The largest change. Hidden coupling through shared mutable state (`triage`, `runItems`) moved into `store`. | L | After PC-1a. Serial. |
| **PC-2 features, one per PR** | (a) inbox, (b) triage and viewer, (c) compare, (d) actions, (e) queued, (f) rating, info, status and pairing (small ones together). Each removes its `legacyImports`, splits oversized files and moves its CSS into `<id>.css`. | e2e green. That feature's `legacyImports` empty. Its files under the caps. It touches only its own directory, plus at most one new test. | Hook semantics drifting from today's call order (keep order numbers). | S each, (b) M | After PC-1b. **All six in parallel**, one session per feature directory. |
| **PW-1 installable shell** | Manifest, icons, `sw.js` (shell precache with digest check, network-only rules for JSON and originals), `sw-client.js` with the Trusted Types policy, CSP `trusted-types rg-sw`, the update banner, Repair, `persist()`, Settings › About. | e2e: installability (manifest parsed, worker controls), offline cold start shows the shell and "offline", update banner then Reload activates the new version, originals and `/api` never in caches. Server tests for `/sw.js` and CSP. | Trusted Types API differences across Chromium versions. A broken worker on the live phone (Repair and daily check). | M | After PC-1b. Parallel with PC-2 (it touches `core/sw-client.js`, `sw.js` and the server only). |
| **PW-2 rendition cache** | The `rg-media-1` LRU, its IndexedDB index, decided-first eviction, cap and lifetime from settings, prefetch through the worker, wipe on 401. | e2e with a small cap: eviction order, lifetime, no original ever stored, 401 wipe. PHONE-FAST's next-4 prefetch now served from cache (second view causes no network request). | Quota surprises on low-storage phones (cap = min(setting, quota/2)). | M | After PW-1. Parallel with PC-2. |
| **PO-1 one outbox, offline sending** | IndexedDB `rg` database, the outbox store and migration, Web Locks, BroadcastChannel, the shared `outbox-send.js`, Background Sync, fallback triggers, the header pill and `#/waiting`, rating answers and submit through the outbox. | e2e: offline queue then online sends once (keys asserted on the gateway), migration from a pre-seeded `localStorage`, two tabs never double-send, held undo after `pagehide` sent by the worker, `dispatchSyncEvent` path, RG-160 PC-away journey unchanged. | Concurrency between tabs and the worker (one lock). Migration data loss (idempotent copy-then-delete). | M-L | After PW-1 and PC-2(e). Serial in the core lane. |
| **PO-2 offline review** | The offline feature (pack rows and renditions), `paired_offline` boot from the snapshot, "as of" home, `based_on` on decisions with gateway 409 `decision_changed` and the phone's Use mine / Keep theirs. | e2e: cold start offline, review 5 from the pack, back online, applied. A conflict from a second device shows the choice. Gateway ASGI tests for `based_on`. | Stale snapshot confusion (always labelled "as of"). Gateway change must stay additive. | M | After PO-1 and PW-2. |
| **PS-1 staging (deferred, OD-7)** | `--target` in `tools.review_gateway_deploy`, separate staging settings, `tools.review_gateway_stage seed/reset` reusing the PC-0 seeder, the "Staging" header label from gateway config, a runbook section, the owner steps of section 6. | Tool tests (closed target set, settings isolation: the app's sync settings are never read or written). After the owner's Proxmox steps: one deploy to staging and one promotion of the same SHA, recorded. | Owner time on Proxmox. Settings mix-up (separate file and name, tests). | M | Deferred by the owner. When wanted: after PC-0 (seeder), parallel with everything. |
| **PP-1 QR re-pair** | Desktop pairing dialog QR (`src/app` dialog, no new dependency if a QR encoder is already pinned, else a tiny vendored one, owner check), phone `#/pair/<code>` prefill and fragment removal, `last_seen_at` in `enrolled_devices` and the desktop list. | A Tk test that the dialog renders the QR. e2e: the fragment prefills and is removed from history. Sync contract test for the additive field. | QR library supply chain. | S-M | After PC-2(f). Parallel with PW and PO. |

Order on the critical path:

```
PC-0 → (RG-160, NAME-INFO merge) → PC-1a → PC-1b → { PC-2 a-f ∥ PW-1 → PW-2 } → PO-1 → PO-2
PS-1 deferred (OD-7); when wanted, any time after PC-0
PP-1 after PC-2(f)
```

**Ownership convention for parallel sessions.**

- A session's brief names exactly one feature directory, or `core/`, as its write scope, plus its tests. The
  orchestrator gives the core lane to one session at a time.
- Server static serving (`phone_app.py` static table and template) is part of the core lane.
- A feature PR that needs a new slot stops and asks for a small core PR first. It does not edit `core/`.
- CSS is per feature. `core/core.css` holds only the shared tokens (colours, spacing, header, sheet, toast).
- The size caps are checked by `test_static_rules.py`. They keep any one file small enough that two features never need
  the same file.

## 8. Owner decisions

Answered 2026-11-27: OD-1, OD-2, OD-3, OD-6 and OD-7 by the owner in chat, relayed by the orchestrator; OD-4, OD-5 and
OD-8 to OD-11 adjudicated by the orchestrator with the recommended defaults.

| # | Decision | Recommended default | Answer (2026-11-27) |
|---|---|---|---|
| OD-1 | Which browser runs the installed app | **Chrome, installed as an app** (WebAPK). DuckDuckGo stays the everyday browser. It cannot install and clears data unless the gateway is Fireproofed. | **Chrome app for review** (owner). DuckDuckGo stays for everyday browsing. |
| OD-2 | How long renditions stay on the phone, and the cap | **7 days** (the gateway's own `max-age`), **500 MB** or half the quota if smaller. The oldest and decided go first. Originals never. | **Larger: 14 days, 1 GB** (owner). Decided items dropped first. |
| OD-3 | Size of the offline review pack | **The next 100 images** to review (about 25 to 40 MB), refreshed when online. | **The next 300** (owner). |
| OD-4 | Cache videos for offline viewing | **No** for now (Range requests, size). Revisit after PO-2. | No offline video (orchestrator, default). |
| OD-5 | A longer-lived or recoverable device credential | **No.** Fix the cause (OD-1) and make re-pairing a QR scan (PP-1). Passkeys only if a Chrome install still loses pairing. | QR re-pair, no longer-lived credential (orchestrator, default). |
| OD-6 | Cached media on a lost and revoked phone | **Wipe at the next contact (401)**, and accept residual R1: a phone that never reconnects keeps renditions until their lifetime ends. Removing it from the tailnet is the first step when a phone is lost. | **Accept, wipe on next contact** (owner). Recorded: a phone that never reconnects keeps images until expiry, which with OD-2 is 14 days. |
| OD-7 | Staging topology, and what may be deployed there | **(a) A separate CT 121, signed `main` commits only, promote the same SHA.** (b) is optional: also allow heads of branches in this repository on staging only. | **Not now** (owner). PS-1 deferred; section 6 kept, marked deferred. |
| OD-8 | Offline decisions that conflict with a newer one | **Ask** ("Changed on another phone: Use mine / Keep theirs") through `based_on`. The alternative is last arrival wins, as today. | Ask on conflict (orchestrator, default). |
| OD-9 | Queue a rating Submit made offline | **Yes**, sent when back. The PC still checks and may refuse as today. | Queue an offline rating Submit (orchestrator, default). |
| OD-10 | The update prompt | **A banner with Reload, never forced.** The new version otherwise starts when the app is next fully closed. | Banner, never forced (orchestrator, default). |
| OD-11 | Browser e2e as a merge gate | **Yes, through `full-suite`** for any gateway change (no branch-protection change). Nightly as well. | `phone-e2e` gates merges through `full-suite`, plus nightly (orchestrator, default). |

## 9. Self-critique (one model; not an independent review)

- **The weakest assumption is that PC-0's journeys catch PC-1b's behaviour changes.** A mechanical split of about
  2,900 lines can change a timing (undo hold, prefetch order) that no journey asserts. Mitigation: PC-0 must assert
  outcomes on the gateway's store (records, keys, order), not only on the screen. PC-1b may not edit any journey. Its
  reviewer reads `--color-moved` output.
- **Background Sync matters less than it looks.** On this phone the gateway is reachable only with Tailscale up, which
  connectivity events do not report. The page fallback carries most of the load. Background Sync's real value is
  sending a held undo, or the last decisions, after the owner swipes the app away.
- **The browser facts about DuckDuckGo come from one user report**, plus platform facts about WebView. PC-0's
  five-minute owner check settles it before PW-1. Nothing in the plan depends on DuckDuckGo working, only on Chrome.
- **Server-side substitution is a small templating step.** It is honest to call it no build, because it is computed at
  start from the installed files and nothing is generated into the repository. But it is new gateway logic to test
  (5.2).
- **Slots can grow into a framework.** The cap is the fixed table in 2.2. A new slot is a reviewed core change.

## 10. Execution class and model recommendation

- This package: Architectural docs (new structure, a new offline persistence model, a new deploy target). Local.
- Model recommendation (this package): Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- Per slice:

| Slice | Claude Code | Codex |
|---|---|---|
| PC-0 | Sonnet 5.5 High | GPT-6.1 Sol High |
| PC-1a | Sonnet 5.5 High | GPT-6.1 Sol High |
| PC-1b | Opus 5.5 High | GPT-6 Astra High |
| PC-2 (a) to (f) | Sonnet 5.5 Medium/High | GPT-6.1 Sol Medium/High |
| PW-1 (security boundary) | Opus 5.5 High | GPT-6 Astra High |
| PW-2 | Sonnet 5.5 High | GPT-6.1 Sol High |
| PO-1 (persistence and concurrency) | Opus 5.5 High | GPT-6 Astra High |
| PO-2 | Sonnet 5.5 XHigh | GPT-6.1 Sol XHigh |
| PS-1 | Sonnet 5.5 High, plus an owner-guided Proxmox session | GPT-6.1 Sol High |
| PP-1 | Sonnet 5.5 High | GPT-6.1 Sol High |

## 11. Exact start state and authorities

- Task start was not recorded when the session began. The design was written at 2026-11-27T18:34-05:00. Session started by orchestrator
  `local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`.
- Base `origin/main` `76b9ddcdccd75e9d31b758fd45cc594479bcb605`. Open branches read: `claude/rg-160-2` `a4bd7be1`,
  `claude/name-info-e73186` `5d24db0a`.
- Authorities: `AGENTS.md`, `docs/ai/workflows/DESIGN_REVIEW.md`, RG-100, `REVIEW_GATEWAY.md`, DEPLOY-PROXMOX,
  `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, `docs/AI_MODEL_SELECTION.md`.

## 12. Surface assessment

- This package: this file only.
- Later slices touch:
  - `services/review_gateway/review_gateway/static/**` and `phone_app.py` (static serving, CSP, `based_on`);
  - `tests/review_gateway_service/` and the new `tests/phone_e2e/`;
  - `.github/workflows/ci.yml`, `pyproject.toml` (marker), `requirements-e2e.txt`;
  - `tools/review_gateway_deploy.py` and a new `tools/review_gateway_stage.py`;
  - for PP-1, the desktop pairing dialog under `src/app`.
- Controller surface: none. No `src/controller` file changes.
- Architecture authority: `REVIEW_GATEWAY.md` gains a "Phone app structure and offline" section when PC-1b and PW-1
  land. RG-100's invariants are unchanged.

## 13. Acceptance and evidence

- Accepted outcome of this package: the owner approves the design, or amends the decisions in section 8.
- Evidence mode: documentation inspection and reading code at the SHAs in section 0. No runtime evidence.
- Qualification claim: N/A.
- Not demonstrated: no browser, no phone, no deployed gateway, nothing run.

### 13.1 PC-0 owner phone check (partial, 2026-11-27)

The owner's answers, read from his screenshots and relayed by the orchestrator. Identifiers are left out.

| # | Question | Answer |
|---|---|---|
| 1 | Phone, Android, free storage | Samsung Galaxy S23+, Android 16, about 33 GB free (8 GB RAM). The 1 GB rendition cap (OD-2) is about 3 % of the free space. |
| 2 | Chrome version | Chrome 158 |
| 3 | Chrome on the gateway: Install app, or only Add to Home screen | Not answered yet |
| 4 | DuckDuckGo on the gateway: an Install item? Fireproofed? | The gateway site **is Fireproofed**. The DuckDuckGo main menu he showed has no Install item, but it was not opened on the gateway page, so whether the page itself offers one is still unchecked. |
| 5 | DuckDuckGo automatic data clearing | Not answered yet |
| 6 | Tailscale Always-on VPN | Not answered yet. The Tailscale app does not show it; it is in Android's own VPN settings (Settings › Connections › More connection settings › VPN on Samsung). |

**What it changes so far.** Nothing in the plan. Answer 4 means a Fireproofed site is still the setup that lost the
pairing on 2026-11-27, unless it was Fireproofed only afterwards. Answer 5 decides which. OD-1 (Chrome app for review)
stands either way.

## 14. Token-efficient validation plan (for the slices)

1. Focused: the slice's ASGI tests and `test_static_rules.py`.
2. `python -m pytest -m phone_e2e tests/phone_e2e` locally once per slice (headless, no app start).
3. `python tools/ci/run_pr_gate.py` in an isolated worktree (no browser).
4. CI `phone-e2e` as the browser verdict. Reuse a green exact-SHA run when static and test files are unchanged.

## 15. Stop conditions

- A design step needs a build step, a CDN, an inline script, or a CSP relaxation other than `trusted-types rg-sw`.
- Authenticated JSON or an original would be stored in an HTTP cache.
- A second outbox or queue authority appears on the phone or the gateway.
- A phone API change cannot be made additive.
- Staging would share cookies, secrets, data or the Immich key with production.
- PC-1b cannot stay behaviour-identical without editing a PC-0 journey.

## 16. Documentation impact

- PC-1b and PW-1: `REVIEW_GATEWAY.md` (structure, cache rules, update flow), `docs/CODEX_MAP.md` row (module paths).
- PS-1: `docs/runbooks/review_gateway.md` (staging, promotion).
- PO-1 and PO-2: `REVIEW_GATEWAY.md` section 3 (the phone's outbox, offline).
- PC-0: the testing guidance line for `phone_e2e`.

## 17. Completion report

Filled in at closeout per `AGENTS.md` section 8.
