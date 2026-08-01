# Chromoxel for Unreal Engine 5.8

**Texture-aware editor voxelization with persistent HISM previews.**  
面向 Unreal Engine 5.8 的一键场景体素化与 BaseColor 烘焙插件。

**Version:** 0.2.0  
**Status:** Beta / source release  
**Target:** Unreal Engine 5.8, Win64 Editor

Chromoxel provides a compact editor pipeline for surface voxelization and
Deferred BaseColor capture. It stores deterministic sparse occupancy blocks and
creates a persistent HISM preview in a copied output map. The source map is
never overwritten.

## Features

- Collects visible, static, collision-enabled Static Mesh, ISM, and HISM
  components.
- CPU triangle/AABB surface voxelization with bounded work limits.
- Deterministic `4 × 4 × 4` blocks using a `uint64` occupancy mask.
- Six-axis orthographic Deferred `SCS_BaseColor` and linear-depth capture.
- Canonical `0x00RRGGBB` sRGB storage in `UVoxelMapDataAsset`.
- Correct sRGB-to-linear conversion before HISM custom data reaches BaseColor.
- Persistent copied output map and preview actor; repeated bakes update in
  place.
- Editor menu command and unattended commandlet entry point.
- Detailed JSON diagnostics under `Saved/VoxelMapMVP`.

## Install

### Source ZIP

1. Download `chromoxel-unreal-0.2.0-UE5.8-source.zip` from [`dist`](dist) or
   the latest GitHub Release.
2. Extract its `Chromoxel` folder to `<YourProject>/Plugins/Chromoxel`.
3. Do not copy generated `Binaries`, `Intermediate`, or `Saved` directories
   from another machine.
4. Regenerate project files and build the project Editor target for Win64.
5. Enable **Chromoxel** if Unreal asks, then restart the editor.

The package contains plugin source only. It does not include Unreal Engine
code, Starter Content, project maps, or third-party asset packs.

## Editor workflow

Open a supported level, open the **Tools** menu, and choose:

`Bake Current Level (25 cm)`

The command creates or updates:

- `/Game/VoxelMapMVP/Data/VM_<Level>`;
- `/Game/VoxelMapMVP/Maps/<Level>_Voxelized`;
- `/Game/VoxelMapMVP/Materials/M_VoxelMapPreview_BaseColor`;
- one persistent HISM preview actor; and
- a JSON bake report under `Saved/VoxelMapMVP`.

Included source meshes are hidden only in the copied output map. The original
map is not saved or modified.

## Commandlet

```text
UnrealEditor-Cmd.exe <YourProject>.uproject \
  -run=VoxelMapBake \
  -Map=/Game/Maps/<InputLevel> \
  -OutputMap=/Game/VoxelMapMVP/Maps/<InputLevel>_Voxelized \
  -DataAsset=/Game/VoxelMapMVP/Data/VM_<InputLevel> \
  -VoxelSize=25 \
  -Report=VoxelMapMVP/BakeReport.json \
  -unattended -nop4 -nosplash -AllowCommandletRendering
```

The commandlet requires a rendering-capable client world, a non-Null RHI, and
the Deferred renderer (`r.ForwardShading=0`). It fails closed instead of
substituting lit SceneColor when BaseColor capture is unavailable.

## Current limits

- Surface shell only; no solid-volume fill.
- No Landscape, Skeletal Mesh, PCG, Foliage, or Nanite fallback.
- Static Mesh, ISM, and HISM BaseColor capture only.
- General World Partition support is outside this MVP.
- No incremental bake, clipmap, sparse streaming, or billboard renderer yet.
- Safety caps bound axis size, triangle/voxel candidate tests, and occupied
  voxel count.

## Compatibility identity

The descriptor filename, C++ modules, console command, asset paths, and report
paths retain the `VoxelMapMVP` technical identifier for compatibility with the
existing UE 5.8 implementation. The user-facing plugin name is **Chromoxel**.

## Build and validation

Build the deterministic source package:

```powershell
python tools/build_package.py
```

The source was validated with Unreal Engine 5.8 on Win64. UnrealHeaderTool and
UnrealBuildTool completed the clean host-project build with UBA disabled and
one parallel action. See [VALIDATION.md](VALIDATION.md) for the release record.

## License

Chromoxel is released under the [Apache License 2.0](LICENSE).

