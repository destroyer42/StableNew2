# Native Operator Site Output Library

## Scope and execution profile

LIBRARY-100 delivers the native index and preview operations. LIBRARY-110 owns
the browser UI and hosted allowlist changes. The execution class is Standard.
For this persistence and authorization work, use Claude Code Sonnet 5.5 High
or Codex GPT-6.1 Sol High on local Windows. Both tiers can review the complete
change in one session, and Windows provides the junction, playback and process
containment fixtures.

The Site catalog owns the browsing projection. AppController, JobService,
queue admission, NJR compilation and PipelineRunner keep their existing
ownership. Site composition reads the existing runner's active-job signal
to defer speculative work.

## Capabilities and transport

Probe the authenticated native output status at GET
`/v1/output/status`. An absent or false `library_index_v2` capability means
use the existing Library operations. The new actions use the same POST
`/v1/output/library` route and current catalog `scope`. They are read
operations. Local loopback and the Windows phone connector recognize them.
LIBRARY-110 must allow the exact action and field sets in the hosted desktop
relay and phone Worker before its clients request them. The native connection
protocol stays at version 2.

| Client and Windows combination | Library behavior |
| --- | --- |
| Existing Site client and indexed Windows | Existing search, JPEG thumbnails, inspection, playback, albums and Review. Search orders each selected kind globally by date. |
| LIBRARY-110 Site and older Windows | Probe capability and use the existing operations. |
| LIBRARY-110 Site and indexed Windows on loopback | Use the v2 operations with the active scope. |
| LIBRARY-110 Site and indexed Windows through hosted transport | Enable v2 after the matching hosted action allowlists are present. |

Requests and responses remain grant-scoped. Keep using the existing inspection,
media delivery, album, rating and Review contracts. Closed-field validation
remains in effect at each transport boundary. A new connection or a changed
Output folder requires discarding saved page revisions and media IDs.

## Query and facets

Send `action: "query_v2"` with optional fields below. `facets_v2` accepts
the same fields and adds `facets` to the response.

| Field | Values and default |
| --- | --- |
| `kind` | `all` (default), `image`, `video` |
| `sort` | `newest` (default), `oldest`, `filename_asc`, `filename_desc` |
| `field` | `all` (default), `name`, `prompt`, `tag`, `seed`, `model` |
| `query` | Case-insensitive substring, except exact decimal seed. At most 240 characters. |
| `filters` | Optional object of fields below. All supplied filters apply together. |
| `offset`, `revision` | Start at 0. Send the returned revision and next offset for subsequent pages. |
| `refresh` | Boolean, default false. True schedules full reconciliation. |

Filter fields are `after` (inclusive), `before` (exclusive), `source`,
`model_family`, `model`, `workflow`, `dimensions`,
`aspect_ratio` and `orientation`. Dates are ISO 8601 with an explicit UTC
offset or `Z`. They compare to the effective timestamp for each item. Source
values are `pipeline`, `learning`, `reprocess`, `movie_clips`,
`svd`, `video_eval` and `other`. Model, family and workflow match
exact returned values. Dimensions are an ordered integer pair [width, height].
Ratio is a positive `width:height` string, reduced before matching.
Orientation is `portrait`, `landscape` or `square`. Send null for
Unknown dimensions, ratio, orientation, model, family or workflow. Rating
filtering is deferred. Existing digest-bound ratings remain available.

Each page has up to 24 items. Filtering and sorting precede pagination.
Chronology uses a recorded timestamp with an explicit offset or falls back to
filesystem modification. Filename sorting casefolds names. Both use a stable
internal tie-breaker. A revision binds the grant, index incarnation, indexed
rows and normalized query. On `stale_library_page`, restart at offset 0.
`next_offset` is null at the end. `total` is the count in the indexed
snapshot. Show a partial-results state for `partial: true`, including a cold
inventory, pending metadata, a scan error, or a record withheld because the
file changed during reconciliation.

`state` is `incomplete`, `reconciling`, `complete` or `error`.
Use `scan_error` and `limited` for retry or capacity messaging.
`metadata_limited` indicates pending enrichment in the indexed snapshot.
A warm page can return before filesystem reconciliation. Refreshing the browser
does not require a forced native refresh.

Facets are derived from the full indexed query result. Each facet returns
`values` as an array of `{value,count}` and a `limited` flag when more
than 64 values exist. Facet keys are `source`, `model_family`, `model`,
`workflow`, `dimensions`, `aspect_ratio` and `orientation`. Request
facets separately when filters change. For a selector which should still offer
other choices in its dimension, omit that selector's filter in its facets call.

## Media records and previews

Each v2 row includes the legacy ID, filename, MIME type, size, source, bounded
prompt and tags, seed and metadata provenance. It adds:

- `kind`, `width`, `height`, `aspect_ratio` and `orientation`.
  Unknown dimensions are null. Video dimensions use the reported display
  orientation where rotation metadata is available.
- `timestamp`, `timestamp_basis` (`recorded` or `modified`),
  `recorded_at` and `modified_at`. Dates are serialized in UTC. Local
  timestamps without a recorded offset use the filesystem fallback.
- `model_family`, `model` and `workflow`. Family and workflow values
  come from recorded metadata. A missing family stays null.
- `duration` in seconds and `fps` for video when the container can be
  inspected. Values are reported metadata.
- `preview` of `pending`, `ready` or `placeholder`. It is a cache
  availability hint, and eviction may change it between requests.

`provenance` is `manifest` for image metadata verified against the
original SHA-256, `embedded` for recorded image or video metadata,
`legacy` for supported older image metadata, or `unknown`. Native gallery
records, canonical artifact linkage, ratings and Review continue to verify
digest identity at their authoritative entry points.

For grid media, send `{action:"previews_v2",scope,ids:[...]}` with up to eight
IDs. The response maps IDs under `previews`. Ready entries have `state`,
`mime` and base64 `image`. The longest edge is at most 320 pixels.
Images use WebP with JPEG fallback. Posters use JPEG. Pending video entries
have `state:"pending"` and `kind:"video"`. Retry visible pending IDs with
bounded backoff. Placeholders have `state:"placeholder"` and `kind` so
the client can render an appropriate fallback. Missing entries are unavailable
under the caller's current scope or file version. Keep playback behind the
operator's existing play operation. Grid calls transfer derivative bytes
only. The legacy `thumbnails` operation retains JPEG and its score field.
The score overlay reads the current rating record separately from preview
bytes. The inspection endpoints continue to use the original.

The cache lives under the per-user StableNew application data directory in
`output-library`. An explicit `STABLENEW_SITE_LIBRARY_CACHE_DIR` must be an
absolute dedicated empty directory on first use, outside Output. The index
stores one rebuildable projection per pinned root. One installation-wide
preview database keys derivatives by root, path, file fingerprint and
encoding version. `STABLENEW_SITE_LIBRARY_CACHE_BYTES` configures the
recency-based budget, default 2 GiB. The budget charges derivative bytes
and per-record overhead. SQLite allocation and journal space contribute
additional disk overhead.

Discovery polls known directory changes and periodically reconciles the full
tree. A brief settling interval avoids publishing actively written files.
In-place external changes may wait for periodic reconciliation. Speculative
preparation targets the newest 200 indexed artifacts and pauses while native
generation is active. Foreground video misses use a bounded queue. Poster
extraction requires a supported local FFmpeg build with seekable file
descriptor input and remains inside the native playback size limit.
Unavailable decoders and unsupported clips yield placeholders.

## Validation and Library-110 handoff

Run the scoped library/index/preview, transport and existing ratings, albums,
Review, playback, pairing, and phone regression suites in `tests/controller/`.
Run the native PR gate once after the aggregate review. Compare both revisions
with `tools/test_helpers/site_library_profile.py`, from each checkout, using
the same temporary location and optional tiny CPU-encoded video fixture.
The benchmark reports distributions and work counts without CI wall-clock
thresholds.

### Controlled Windows measurements

The fixture uses 60 directories, duplicate names, multiple image resolutions,
recorded and missing metadata, and a tiny CPU-encoded video. It contains at
most 120 real media files. Other entries represent synthetic inventory load.
The matched query and thumbnail timings use 20 runs per size. The first warm
page and new-file discovery use one observation each.

| Items | First warm page | Legacy filter p95 before → after | Cached 8-thumbnail p95 before → after | New file |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 52.0 ms | 0.46 → 27.80 ms | 129.4 → 88.5 ms | 1.93 s |
| 10,000 | 27.0 ms | 10.72 → 28.33 ms | 132.2 → 75.5 ms | 1.61 s |
| 50,000 | 28.7 ms | 62.06 → 32.30 ms | 124.1 → 63.5 ms | 1.44 s |

Indexed sorting with a source and text filter returned in 33–37 ms p95.
At 50,000 entries, a cold first page took 222 ms after the change, compared
with 20 ms for the old progressive inventory publication. Initial inventory
took 18.8 seconds versus 13.2 seconds. Full enrichment finished in 79.7 seconds
versus 140.8 seconds. Traced Python allocations for the inventory pass fell
from 37.5 MB to 18.4 MB. Baseline scan media opens fell from 40,000 to 120.
Across 20 warm batches, original stream opens, full reads and image encodes
fell from 160 each to zero. Application-observed original bytes read fell
from 113,120 to zero. The benchmark counts Python stream reads and does not
instrument reads inside FFprobe.

LIBRARY-110 can consume the contract above to implement sorting, filters,
facets, paging, image and video grid previews, partial state, and fallbacks.
The package closeout records the exact native branch, SHA and performance
evidence. Physical desktop load, installed browser acceptance, and deployed
relay behavior require separate acceptance evidence.
