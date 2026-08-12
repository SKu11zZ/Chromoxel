# Changelog

## 0.9.0 - 2026-08-12

- Added real GPU Uniform occupancy prefiltering in normal interactive Blender
  sessions. A coarse triangle-brick index and conservative triangle-AABB
  shader reject empty candidates in bounded batches; Blender's CPU BVH still
  confirms every positive, preserving exact CPU voxel coordinates.
- Added reusable interactive Source Sessions across Preview and direct Bake.
  Evaluated source/sampling snapshots, symmetry proof, BVHs, texture state,
  uploaded triangles, and up to two resolution indexes stay warm until the
  source changes or the user clears the cache.
- Added stage-level diagnostics for source preparation, lattice, candidates,
  occupancy, colour/adaptive work, carrier creation, Bake, export, save, BVH
  query counts, GPU fallback reasons, and memory/index usage. The Blender
  Advanced panel and CLI JSON report expose these measurements.
- Replaced large sparse-candidate Python expansion with exact NumPy
  chunked-mask rasterization when the canonical lattice is bounded. Full-grid
  candidates also use a lazy, sliceable sequence instead of materializing all
  Python coordinate tuples.
- Added a no-sort fast path for newly sampled editable carriers while keeping
  stable deterministic IDs and the conservative path for existing/external
  carriers.
- Kept the 512 MiB default GPU ceiling, bounded 65,536-candidate dispatches,
  automatic CPU fallback, passive N-panel, 100,000-point per-model ceiling,
  and exact symmetry behavior.
- Validated CPU/GPU coordinate equality for both 1.47-1.49-million-face Tripo
  sources at roughly 2K, 20K, and 97K voxels. Warm 97K samples measured 3.75 s
  and 5.46 s; cold samples measured 3.97 s and 6.25 s after source preparation.

## 0.8.2 - 2026-08-12

- Added an opt-in **Remove Enclosed Voxels** Bake setting and matching
  `--remove-enclosed-voxels` CLI flag. Existing workflows remain unchanged
  because pruning defaults to off.
- Added deterministic O(N) six-neighbour pruning for Uniform point carriers.
  Kept voxel colour, UV, palette/material IDs, PBR attributes, stable IDs, and
  all exterior or partially exposed cells intact.
- Added conservative Adaptive filtering on the minimum-cell lattice with a
  two-million-cell expansion ceiling. Oversized or ambiguous jobs report a
  safe skip instead of deleting uncertain cells.
- Kept the original occupancy mask while constructing Surface and Greedy
  outputs, preventing a removed internal voxel from generating cavity faces.
- Added Blender 5.1.2 regression coverage for closed/open occupancy, Realized,
  Surface, Greedy, direct-sample, UI default, and CLI behavior.

## 0.8.1 - 2026-08-11

- Made the `N > Voxelizer` panel passive. Opening or redrawing it no longer
  traverses source topology; the new **Check Surface** action performs one
  explicit full inspection and caches the result until geometry changes.
- Replaced full geometry/UV Preview-key hashing with depsgraph-revision-aware,
  bounded fingerprints. A 1.47-million-face source now builds its first key in
  26.9 ms instead of approximately 12.1 seconds.
- Added a conservative axis-distribution rejection before exact reflection
  proof, shared coordinate/topology state across axes, and retained exact
  vertex/edge/polygon proof for every possible symmetry axis.
- Made Uniform colour sampling lazy: adaptive edge features and global loop
  triangle maps are no longer built when they cannot affect the result.
- Replaced scalar geometry signatures with bulk `foreach_get` buffers and
  added a first-blocking-condition readiness scan for Bake. The explicit
  surface inspector still reports complete defect and component counts.
- Tightened CLI target fitting so every success is inside the requested
  tolerance, all attempts reuse one source session, and an out-of-range result
  is never saved or reported as PASS.
- On the 1.47-million-face Tripo acceptance source, SourceSession preparation
  fell from 78.83 s to 6.38 s. The previously duplicated 2K CLI run fell from
  185.35 s to 17.7 s end-to-end, including import, eight fit attempts, colour,
  editable carrier creation, and save; the accepted result contained 1,934
  voxels for a 2,000 +/-5% request.

## 0.8.0 - 2026-08-11

- Added Auto/GPU/CPU compute backends for batched image sampling. Interactive
  sessions use a real Blender compute shader; background/headless work and
  unsupported contexts fall back to the colour-equivalent CPU path.
- Added configurable GPU batch and VRAM limits. Oversized source textures fall
  back safely instead of exceeding the selected memory budget.
- Added reusable source sessions for evaluated meshes, diagnostics, symmetry
  proofs, repair helpers, BVHs, triangle/UV state, and image buffers.
- Changed target-count fitting to use occupancy-only trials and sample texture
  colour once at the accepted voxel size.
- Replaced scalar image reads and per-element Blender RNA writes with bulk
  `foreach_get`/`foreach_set` buffers.
- Replaced the quadratic greedy-face seed search with one deterministic sorted
  scan and batched all baked face attributes.
- Added Blender 5.1 GPU nearest/bilinear parity tests, CPU fallback tests, and
  three Mixamo benchmarks at approximately 2K/20K/100K voxels.
- Reduced the measured three-level sampling workload from 156-428 seconds per
  character to 6.7-10.0 seconds on the validated workstation GPU workflow.

## 0.7.0 - 2026-08-11

- Upgraded Preview carriers into durable editable point models with stable IDs,
  minimum-grid coordinates, spatial chunk IDs, sampled UVs, palette/material
  references, and editable PBR attributes.
- Added selection, add/delete/move, mirror, copy/paste, eyedropper/paint, flood
  fill, linked palette editing, and exact-coordinate edit replay after source
  re-voxelization.
- Added editable-point, realized-cube, internal-face-culled surface, and
  material-aware greedy Bake outputs.
- Added MagicaVoxel `.vox` v150/v200 import/export with adaptive-cell
  flattening, deterministic 255-colour quantization, material subset mapping,
  and multi-block scene transforms.
- Added English/Chinese UI support and deterministic release packaging for all
  new modules.
- Validated textured `source_uv` capture, four Bake attributes, exact edit
  replay, the 100,000-point per-model ceiling, 32³ chunks, VOX block replay,
  and palette quantization in Blender 5.1.2.

## 0.6.0 - 2026-08-06

- Added budget-bounded, power-of-two adaptive surface refinement driven by
  filtered texture-footprint error and nearby sharp geometry edges.
- Added exact refinement-orbit closure over every proven symmetry axis so
  variable voxel sizes cannot make symmetric source geometry asymmetric.
- Added automatic per-material Base Color image discovery, active/named UV
  fallback, bilinear reconstruction, and nine-tap footprint analysis.
- Kept footprint variance as the refinement signal while preserving the centre
  sample as voxel colour, and added an adaptive AABB-overlap guard so thin
  decals are not blurred or hidden by circumsphere-only outer cells.
- Added variable-size Geometry Nodes preview instances and realized Bake support
  through the `voxel_size` and `voxel_level` attributes.
- Preserved the legacy Uniform mode and the four-value sampling-result unpacking
  contract for existing scripts and saved workflows.
- Added a synthetic high-contrast bullseye regression covering diagonal ring
  retention, material auto-detection, adaptive budgets, symmetry, Preview, and
  Bake.
- Added a bilingual four-panel KayKit training-range acceptance render that
  isolates old Uniform 0.16 BU, new Uniform 0.16 BU, and adaptive 0.04 BU
  minimum results under one Cycles pipeline.
- Fixed the comparison caption compositor so a 72-DPI Cycles image cannot be
  enlarged and cropped by a 96-DPI GDI+ canvas, and added an outside-caption
  pixel-preservation audit.
- Added adaptive Bake regression coverage proving that display gaps scale with
  each refinement level instead of remaining a fixed absolute distance.
- Added surface-preserving 2D refinement for grid-aligned flat faces. Mixed
  adaptive levels now retain a shared normal thickness instead of creating
  depth steps on walls, floors, tables, or flat decals.
- Added the per-axis `voxel_extent` attribute to Preview and Bake while keeping
  `voxel_size` as the adaptive sampling-resolution compatibility attribute.
- Repaired the bilingual README and documented the remaining procedural-shader,
  UDIM, alpha-occupancy, GPU, and camera-LOD limits.

## 0.5.0 - 2026-08-02

- Added a modifier-style, non-destructive Geometry Nodes preview workflow with
  Active, Selected, and Collection source scopes.
- Added Coarse, Medium, and Fine size presets, repeatable Object/Custom grid
  origins, work and memory estimates, and an advanced limits panel.
- Added modal progress and bounded cancellation checks for Preview and Bake.
- Added exact sparse triangle-AABB candidates with an adaptive small-grid
  fallback and symmetry fundamental-domain sampling.
- Added a bounded LRU sampling cache shared by Preview and Bake; colour inputs
  and image edits are included in cache invalidation.
- Added multi-model, concave NGON, stock Suzanne repair, strict symmetry,
  sparse/full equivalence, cache, and performance regression coverage.

## 0.3.2 - 2026-08-01

- Renamed the user-facing product to Chromoxel while preserving legacy
  technical identifiers for saved-file compatibility.
- Relicensed the repository and packaged source under Apache-2.0.
- Corrected image-sampled BaseColor from normalized sRGB channels to
  scene-linear `FLOAT_COLOR` attributes using the IEC 61966-2-1 EOTF.
- Added public-release documentation, portable smoke coverage, deterministic
  packages, and third-party notices.

## 0.3.1 - 2026-07-28

- Added conservative local X/Y/Z reflection proof using one-to-one vertex
  correspondence and reflected edge/polygon connectivity.
- Added topology-based disambiguation for coincident reflected vertices.
- Centered integer sampling lattices on proved reflection planes and closed
  occupancy only over proved-axis reflection orbits.
- Preserved proved axes through private Auto Watertight helper repair and
  exposed source/helper/sampling diagnostics.
- Added cube, UV sphere, stock open Suzanne, and intentionally asymmetric
  Blender 5.1 regression coverage.
- Preserved the v0.3 Geometry Nodes point carrier, fast paths, Live lifecycle,
  source immutability, and realized Bake contract.
- Added consistent extension metadata and deterministic-package preparation.

## 0.3.0

- Introduced the lightweight POINT/FLOAT_COLOR Preview carrier.
- Added reusable-cube Geometry Nodes instancing without Realize Instances.
- Added transform/display fast paths, debounced Live Update, collision
  refusal, owned-only Clear, and realized Bake compatibility.
