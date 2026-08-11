# Chromoxel large-source benchmark

Date: 2026-08-11

Environment: Blender 5.1.2, Chromoxel 0.8 development branch, CPU sampling,
Uniform mode, inputs normalized to 4 BU height, approximately 2K output target.

## 0.8.1 repaired results

The same sources were rerun after the passive-panel, strict fitter, bulk
signature, fast readiness, conservative symmetry-precheck, and lazy Uniform
colour-sampler changes.

| Stage | Mixamo CH14 | Tripo 214730 | Tripo 220646 |
| --- | ---: | ---: | ---: |
| Source session | 0.210 s | 6.437 s | 6.375 s |
| Occupancy | 0.013 s | 0.014 s | 0.005 s |
| Colour queries | 0.072 s | 0.102 s | 0.067 s |
| Editable carrier | 0.021 s | 0.021 s | 0.017 s |
| Total including import/join, no save | 0.825 s | 12.187 s | 12.492 s |

For Tripo 220646, source preparation fell from 78.833 s to 6.375 s
(12.4x), and the full no-save path fell from 85.154 s to 12.492 s (6.8x).
Its formerly duplicated CLI target fit fell from 185.345 s to 17.7 s
end-to-end, accepted 1,934 voxels for the requested 2,000 +/-5%, and reused one
source session across all eight occupancy attempts plus final colour sampling.

The 1,471,620-face source measured 0.042 ms per passive panel draw. Its first
bounded Preview key took 26.9 ms and repeated keys took 0.125 ms, versus about
12.1 s for the previous full geometry/UV hash. Geometry changes invalidate the
key; object-only transforms retain the sampling cache.

### Repaired source-session breakdown (Tripo 220646)

| Stage | Before | 0.8.1 |
| --- | ---: | ---: |
| Source symmetry | 43.000 s | 0.145 s |
| Original colour sampler | 21.257 s | 1.929 s |
| Watertight helper | 8.713 s | 2.699 s |
| Source readiness/diagnostics | 5.730 s | 1.584 s |
| Total source session | 78.833 s | 6.375 s |

## Source complexity

| Source | Vertices | Faces | Loops | Boundary/non-manifold edges | Components |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mixamo CH14 | 6,109 | 6,162 | 24,498 | 32 | 4 |
| Tripo 214730 | 764,816 | 1,488,721 | 4,466,163 | 40,681 | 115 |
| Tripo 220646 | 767,476 | 1,471,620 | 4,414,860 | 62,660 | 336 |

## Direct UI Preview path

This is the same synchronous `preview.refresh_preview` path used by the panel,
excluding file import and source joining.

| Source | Preview seconds | Output voxels |
| --- | ---: | ---: |
| Mixamo CH14 | 1.195 | 1,978 |
| Tripo 214730 | 95.545 | 1,900 |
| Tripo 220646 | 91.878 | 1,865 |

The two million-face inputs block the UI path for approximately 77-80 times
longer than the Mixamo character at a similar output voxel count.

## Instrumented no-save path

| Stage | Mixamo CH14 | Tripo 214730 | Tripo 220646 |
| --- | ---: | ---: | ---: |
| Import | 0.542 s | 3.936 s | 3.916 s |
| Join evaluated meshes | 0.016 s | 1.694 s | 1.660 s |
| Surface-area estimate | 0.005 s | 0.668 s | 0.652 s |
| Source session | 1.224 s | 80.267 s | 78.833 s |
| Occupancy | 0.014 s | 0.017 s | 0.007 s |
| Colour queries | 0.074 s | 0.106 s | 0.071 s |
| Editable carrier | 0.021 s | 0.021 s | 0.014 s |
| Total | 1.896 s | 86.709 s | 85.154 s |

For both Tripo inputs, source preparation is about 92.6% of the measured
no-save time. The actual voxel occupancy, colour queries, and carrier creation
remain below 0.15 seconds combined.

### Source-session breakdown

| Stage | Tripo 214730 | Tripo 220646 |
| --- | ---: | ---: |
| Exact source symmetry proof | 43.095 s | 43.000 s |
| Original high-poly colour sampler/BVH | 22.375 s | 21.257 s |
| Watertight sampling helper | 9.091 s | 8.713 s |
| BMesh topology diagnostics | 5.487 s | 5.730 s |
| Remaining session work | 0.218 s | 0.133 s |

The UI additionally spends 12.754 s and 12.125 s respectively building its
full geometry/UV preview cache key before sampling.

## Panel-open regression

Before 0.8.1, opening `N > Voxelizer` performed expensive work even before Preview
or Bake is requested. `VOXELIZER_PT_panel.draw()` calls
`core.mesh_diagnostics(source.data)` and then calls
`core.is_closed_manifold(source.data)`, which runs the same full BMesh
diagnostic a second time. One diagnostic pass takes 5.48-5.83 seconds on the
two Tripo inputs, so a single panel redraw can block the main thread for at
least 11 seconds. Blender may redraw the sidebar repeatedly, making the editor
appear to freeze immediately.

0.8.1 makes the panel draw path passive and adds an explicit cached surface
inspection whose result is invalidated after source geometry changes.

## CLI target-fit finding

Tripo 220646 did not enter the requested 2K +/-5% interval in four iterations:
1,192, 2,277, 1,805, and 2,147 voxels. The current fallback selected 1,805
voxels (9.75% below target), still reported PASS, closed the reusable source
session, and then repeated high-poly preparation for the final colour sample.
This raised end-to-end time to 185.345 seconds. The fallback must retain the
session and enforce the requested tolerance.

## Completed 0.8.1 repair order

1. Remove all mesh traversal from panel `draw()` and replace it with an
   explicit cached **Check Surface** action.
2. Keep the source session alive during CLI target-fit fallback and fail when
   the requested tolerance cannot be met.
3. Reuse the existing repaired occupancy proxy independently from the original
   texture-colour source.
4. Add a conservative symmetry precheck and lazy Uniform colour structures.
5. Repeat all three source benchmarks and retain the results above as the
   acceptance record. Cancellable preparation stages remain future work.
