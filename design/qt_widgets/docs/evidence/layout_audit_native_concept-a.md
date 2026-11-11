# Create layout audit (native platform)

Theme `concept-a` · Qt platform `windows` · scale 1.0 (native display scale) · 3.14.9

| Layout | State | Requested → actual | Output Display | Form viewport | Form screens | Unreachable | Clipped/overflow | Task scroll actions | Form scroll (viewports) | Summary/preview/primary without scrolling | Tab stops · missing · out of view · preview before actions |
|---|---|---|---|---|---|---|---|---|---|---|---|
| scroll | fresh | 1280x680 → 1280×680 | expanded | 656×402 | 6.77 | none | none | 2 | 2.89 | no: preview_chip, summary | 38 · 0 · 0 · yes |
| scroll | primed | 1280x680 → 1280×680 | expanded | 656×402 | 6.77 | none | none | 2 | 2.89 | no: preview_chip, summary | 42 · 0 · 0 · yes |
| split | fresh | 1280x680 → 1280×680 | expanded | 407×402 | 6.05 | none | none | 3 | 3.19 | yes | 39 · 0 · 0 · yes |
| split | primed | 1280x680 → 1280×680 | expanded | 407×402 | 6.05 | none | none | 3 | 3.19 | yes | 43 · 0 · 0 · yes |
| scroll | fresh | 1280x680 → 1280×680 | collapsed | 980×427 | 6.0 | none | none | 2 | 2.63 | no: preview_chip, summary | 30 · 0 · 0 · yes |
| scroll | primed | 1280x680 → 1280×680 | collapsed | 980×427 | 6.0 | none | none | 2 | 2.63 | no: preview_chip, summary | 34 · 0 · 0 · yes |
| split | fresh | 1280x680 → 1280×680 | collapsed | 647×427 | 4.86 | none | none | 2 | 2.7 | yes | 31 · 0 · 0 · yes |
| split | primed | 1280x680 → 1280×680 | collapsed | 647×427 | 4.86 | none | none | 2 | 2.7 | yes | 35 · 0 · 0 · yes |
| scroll | fresh | 960x600 → 1192×600 (clamped by minimum size) | expanded | 644×322 | 8.51 | none | none | 3 | 3.91 | no: preview_chip, summary | 38 · 0 · 0 · yes |
| scroll | primed | 960x600 → 1192×600 (clamped by minimum size) | expanded | 644×322 | 8.51 | none | none | 3 | 3.91 | no: preview_chip, summary | 42 · 0 · 0 · yes |
| split | fresh | 960x600 → 1192×600 (clamped by minimum size) | expanded | 395×322 | 7.66 | none | none | 3 | 4.29 | yes | 39 · 0 · 0 · yes |
| split | primed | 960x600 → 1192×600 (clamped by minimum size) | expanded | 395×322 | 7.66 | none | none | 3 | 4.29 | yes | 43 · 0 · 0 · yes |
| scroll | fresh | 960x600 → 960×600 | collapsed | 660×322 | 8.45 | none | none | 3 | 3.86 | no: preview_chip, summary | 30 · 0 · 0 · yes |
| scroll | primed | 960x600 → 960×600 | collapsed | 660×322 | 8.45 | none | none | 3 | 3.86 | no: preview_chip, summary | 34 · 0 · 0 · yes |
| split | fresh | 960x600 → 960×600 | collapsed | 411×322 | 7.56 | none | none | 3 | 4.23 | yes | 31 · 0 · 0 · yes |
| split | primed | 960x600 → 960×600 | collapsed | 411×322 | 7.56 | none | none | 3 | 4.23 | yes | 35 · 0 · 0 · yes |
