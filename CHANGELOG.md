# Changelog

## 0.3.0 - 2026-08-02

- Added World, Selected Actors, and selected Volume bounds bake scopes.
- Added Fine (10 cm), Standard (25 cm), and Coarse (50 cm) editor presets.
- Added cancellable `FScopedSlowTask` progress across collection,
  voxelization, six-view BaseColor capture, incremental reconciliation, and
  saving.
- Added stable per-block geometry+color hashes and persisted reused, changed,
  and removed block diagnostics.
- Split persistent previews into independently reusable 16 x 16 x 16-cell
  HISM chunks; unchanged chunks retain their instance data on repeated bakes.
- Floor-divide signed chunk coordinates so negative and positive grid regions
  remain evenly partitioned, and expose preview reuse/rebuild/removal counts.
- Added all-material-slot diagnostics for multi-material Static Mesh, ISM, and
  HISM components while retaining Deferred `SCS_BaseColor` capture.
- Extended the commandlet and JSON report with presets, scope parameters,
  material counts, and incremental block metadata.
- Fixed unquoted comma-separated Bounds parsing and added strict numeric
  validation for all three vector components.
- Suppressed the expected missing-asset probe warning on a first bake.

## 0.2.0 - 2026-07-24

- Renamed the user-facing plugin to Chromoxel while preserving the existing
  `VoxelMapMVP` technical identifiers for compatibility.
- Relicensed the repository and source package under Apache-2.0.
- Added deterministic CPU surface voxelization and sparse `4 x 4 x 4` blocks.
- Added strict six-axis Deferred BaseColor and linear depth capture.
- Added canonical sRGB voxel color storage and linear HISM preview input.
- Added persistent copied-map preview updates and source-map safety.
- Added render-client, non-Null-RHI, scene-proxy, PSO, and capture diagnostics.
- Added commandlet rendering contract and fail-closed output behavior.
- Added JSON reports and bounded-work safety caps.
