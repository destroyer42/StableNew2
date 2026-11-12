# Asset Library layout audit (native platform, simulated scaling)

Theme `blue-modern` · Qt platform `windows` · requested scale 1.5 · screen DPR 1.5 · Python 3.14.9

| Layout | State | View | Catalog | Requested → actual | Tiles (rows) | Media area | Filters h | Inspector w | Clipped | Text clipped | Actions reachable | Tab stops · missing | Refresh ms | Page flip ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gallery | browse | grid | small (148) | 1280x680 → 1280×680 | 4 (2) | 501×214 | 150 | 320 | none | 0 | yes | 22 · none | 8.6 | 4.3 |
| gallery | selected | grid | small (148) | 1280x680 → 1280×680 | 4 (2) | 501×214 | 150 | 320 | none | 0 | yes | 27 · none | 52.8 | 51.7 |
| adaptive | browse | grid | small (148) | 1280x680 → 1280×680 | 9 (3) | 724×348 | 0 | 320 | none | 0 | yes | 17 · none | 6.2 | 5.9 |
| adaptive | selected | grid | small (148) | 1280x680 → 1280×680 | 9 (3) | 724×348 | 0 | 320 | none | 0 | yes | 22 · none | 28.3 | 44.4 |
| gallery | browse | grid | small (148) | 1920x1080 → 1709×947 (clamped) | 24 (4) | 889×561 | 96 | 320 | none | 0 | yes | 22 · none | 21.7 | 12.6 |
| gallery | selected | grid | small (148) | 1920x1080 → 1709×947 (clamped) | 24 (4) | 889×561 | 96 | 320 | none | 0 | yes | 27 · none | 54.9 | 40.0 |
| adaptive | browse | grid | small (148) | 1920x1080 → 1709×947 (clamped) | 24 (4) | 1112×615 | 0 | 320 | none | 0 | yes | 17 · none | 21.1 | 20.9 |
| adaptive | selected | grid | small (148) | 1920x1080 → 1709×947 (clamped) | 24 (4) | 1112×615 | 0 | 320 | none | 0 | yes | 22 · none | 48.9 | 39.2 |
