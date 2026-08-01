# Validation Record

## Blender 5.1.2 — PASS

Date: 2026-08-01

- Factory-startup background import succeeded.
- Add-on `register()` and `unregister()` succeeded.
- IEC 61966-2-1 sRGB decoding regression values passed at black, transfer
  breakpoint, sampled KayKit atlas channel values, and white.
- Blender extension command successfully parsed and validated the 0.3.2
  extension ZIP manifest and archive structure.
- Both release ZIPs are deterministic and have SHA-256 entries in
  `RELEASE_MANIFEST.json` and `SHA256SUMS.txt`.

The repository includes one rendered comparison image produced for Chromoxel.
No comparison `.blend` scene, KayKit assets, source textures, local logs, or
absolute machine paths are included.
