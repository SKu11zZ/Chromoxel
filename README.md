# Chromoxel

**Texture-aware voxelization for Blender 5.1.**  
为 Blender 5.1 提供保留贴图细节的体素化工具。

![Chromoxel multi-model and multi-level voxelization comparison](docs/images/chromoxel-multi-model-multi-level-preview.png)

> Four source meshes compared against coarse, medium, and fine voxel sizes. The
> preview demonstrates texture-aware colour sampling, symmetry preservation,
> concave NGON handling, and stable edge coverage.

Chromoxel converts a selected mesh into a coloured surface-voxel shell. It
provides a lightweight Geometry Nodes preview for iteration and a realized
**Bake to Mesh** result for rendering, export, and downstream editing.

## Highlights

- Samples BaseColor from a selected UV map and image texture.
- Preserves proven local X/Y/Z reflection symmetry on symmetric source meshes.
- Handles closed meshes, Blender's stock Suzanne, curved surfaces, sharp
  corners, and concave NGON prisms.
- Optionally builds a private watertight repair copy without modifying the
  source object.
- Uses point-domain data and cube instancing for responsive previews.
- Supports debounced live updates for transforms, geometry, voxel size, and
  cube gap changes.
- Produces realized cube geometry with a `voxel_color` attribute when baked.
- Cleans up only data created and tagged by Chromoxel.

## Install

### Blender extension package (recommended)

1. Download `chromoxel-blender-0.3.2-extension.zip` from the [`dist`](dist)
   directory or the latest GitHub Release.
2. In Blender 5.1, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk** and select the downloaded ZIP.
4. Enable **Chromoxel**.
5. In the 3D Viewport, press `N` and open the **Voxelizer** tab.

### Legacy add-on package

Use `chromoxel-blender-0.3.2.zip` when installing through a workflow that
expects the traditional top-level `voxelizer` folder.

## Quick start

1. Create or import a textured Mesh and select it.
2. Open **3D Viewport > Sidebar (`N`) > Voxelizer**.
3. Keep **Auto Watertight Copy** enabled if the source is not closed manifold.
4. Set **Voxel Size** and **Cube Gap**.
5. Select the UV map and BaseColor image, or use the fallback colour.
6. Click **Add / Refresh Preview**.
7. Enable **Start Live** when you want changes to update automatically.
8. Click **Bake to Mesh** to create independent, realized voxel geometry.

## Preview and bake

| Mode | Best for | Output |
| --- | --- | --- |
| Preview | Interactive look development | Point carrier with Geometry Nodes cube instances |
| Bake to Mesh | Cycles rendering, export, and final editing | Realized cubes with a corner-domain colour attribute |

For the current release, use **Bake to Mesh** for final Cycles renders because
colour propagation through unrealized point instances can depend on the
renderer and Blender version.

## Symmetry behavior

Chromoxel tests local X, Y, and Z reflection symmetry independently using
reflected vertices, edges, and polygon boundaries. Only axes proven symmetric
receive a centered sampling lattice and mirrored occupancy closure. An
intentionally asymmetric source is left asymmetric.

## Current limits

- CPU BVH/grid sampling; GPU voxelization is not implemented yet.
- Surface shell only; it does not generate a filled solid volume.
- One UV map and one BaseColor image per operation.
- No UDIM, procedural shader baking, sparse bricks, clipmaps, streaming chunks,
  or automatic LOD hierarchy yet.
- Sampling is capped at 1,500,000 grid cells and 250,000 active voxels.

## Compatibility identity

The extension ID remains `textured_voxelizer_mvp`, and the runtime ownership ID
remains `org.openai.textured_voxelizer_mvp`, so existing saved files and tagged
outputs continue to work. These are compatibility identifiers; the user-facing
product name is **Chromoxel**.

## Build and validate

Build deterministic legacy and extension packages:

```powershell
python tools/build_packages.py
```

Run the portable smoke test with Blender 5.1:

```powershell
blender --background --factory-startup --python tests/release_smoke.py
```

See [VALIDATION.md](VALIDATION.md) for the verified Blender version and release
checks.

## License

Chromoxel is released under the [Apache License 2.0](LICENSE).

