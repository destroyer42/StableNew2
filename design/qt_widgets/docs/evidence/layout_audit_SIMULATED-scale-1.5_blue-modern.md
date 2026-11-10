# Create layout audit (native platform)

Theme `blue-modern` · Qt platform `windows` · scale 1.5 (SIMULATED via QT_SCALE_FACTOR) · 3.14.9

| Layout | State | Requested → actual | Output Display | Form viewport | Form screens | Unreachable | Clipped/overflow | Task scroll actions | Form scroll (viewports) | Summary/preview/primary without scrolling | Tab stops · missing · out of view · preview before actions |
|---|---|---|---|---|---|---|---|---|---|---|---|
| scroll | fresh | 1280x680 → 1280×680 | expanded | 656×400 | 6.86 | none | none | 3 | 2.96 | no: preview_chip, summary | 38 · 0 · 0 · yes |
| scroll | primed | 1280x680 → 1280×680 | expanded | 656×400 | 6.86 | none | none | 3 | 2.96 | no: preview_chip, summary | 42 · 0 · 0 · yes |
| split | fresh | 1280x680 → 1280×680 | expanded | 406×400 | 6.18 | none | none | 3 | 3.27 | yes | 39 · 0 · 0 · yes |
| split | primed | 1280x680 → 1280×680 | expanded | 406×400 | 6.18 | none | none | 3 | 3.27 | yes | 43 · 0 · 0 · yes |
| scroll | fresh | 1280x680 → 1280×680 | collapsed | 980×426 | 6.09 | none | none | 2 | 2.68 | no: preview_chip, summary | 30 · 0 · 0 · yes |
| scroll | primed | 1280x680 → 1280×680 | collapsed | 980×426 | 6.09 | none | none | 2 | 2.68 | no: preview_chip, summary | 34 · 0 · 0 · yes |
| split | fresh | 1280x680 → 1280×680 | collapsed | 647×426 | 4.9 | none | none | 2 | 2.72 | yes | 31 · 0 · 0 · yes |
| split | primed | 1280x680 → 1280×680 | collapsed | 647×426 | 4.9 | none | none | 2 | 2.72 | yes | 35 · 0 · 0 · yes |
| scroll | fresh | 960x600 → 1192×600 (clamped by minimum size) | expanded | 644×320 | 8.63 | none | none | 3 | 3.95 | no: preview_chip, summary | 38 · 0 · 0 · yes |
| scroll | primed | 960x600 → 1192×600 (clamped by minimum size) | expanded | 644×320 | 8.63 | none | none | 3 | 3.95 | no: preview_chip, summary | 42 · 0 · 0 · yes |
| split | fresh | 960x600 → 1192×600 (clamped by minimum size) | expanded | 394×320 | 7.84 | none | none | 3 | 4.39 | yes | 39 · 0 · 0 · yes |
| split | primed | 960x600 → 1192×600 (clamped by minimum size) | expanded | 394×320 | 7.84 | none | none | 3 | 4.39 | yes | 43 · 0 · 0 · yes |
| scroll | fresh | 960x600 → 960×600 | collapsed | 660×320 | 8.57 | none | none | 3 | 3.95 | no: preview_chip, summary | 30 · 0 · 0 · yes |
| scroll | primed | 960x600 → 960×600 | collapsed | 660×320 | 8.57 | none | none | 3 | 3.95 | no: preview_chip, summary | 34 · 0 · 0 · yes |
| split | fresh | 960x600 → 960×600 | collapsed | 410×320 | 7.72 | none | none | 3 | 4.34 | yes | 31 · 0 · 0 · yes |
| split | primed | 960x600 → 960×600 | collapsed | 410×320 | 7.72 | none | none | 3 | 4.34 | yes | 35 · 0 · 0 · yes |
