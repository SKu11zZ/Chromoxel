# Changelog

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
