# Changelog

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
