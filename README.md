# Chromoxel for Unreal Engine 5.8

**Texture-aware editor voxelization with persistent HISM previews.**

**面向 Unreal Engine 5.8、支持 BaseColor 捕获与持久化 HISM 预览的编辑器体素化插件。**

**Version / 版本：** 0.2.0 · **Status / 状态：** Beta / Source Release ·
**Target / 目标平台：** Unreal Engine 5.8, Win64 Editor

[English](#english) · [简体中文](#简体中文)

---

<a id="english"></a>

## English

Chromoxel provides a compact editor pipeline for surface voxelization and
Deferred BaseColor capture. It stores deterministic sparse occupancy blocks and
creates a persistent HISM preview in a copied output map. The source map is
never overwritten.

### Features

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

### Install

#### Source ZIP

1. Download `chromoxel-unreal-0.2.0-UE5.8-source.zip` from [`dist`](dist) or
   the latest GitHub Release.
2. Extract its `Chromoxel` folder to `<YourProject>/Plugins/Chromoxel`.
3. Do not copy generated `Binaries`, `Intermediate`, or `Saved` directories
   from another machine.
4. Regenerate project files and build the project Editor target for Win64.
5. Enable **Chromoxel** if Unreal asks, then restart the editor.

The package contains plugin source only. It does not include Unreal Engine
code, Starter Content, project maps, or third-party asset packs.

### Editor workflow

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

### Commandlet

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

### Current limits

- Surface shell only; no solid-volume fill.
- No Landscape, Skeletal Mesh, PCG, Foliage, or Nanite fallback.
- Static Mesh, ISM, and HISM BaseColor capture only.
- General World Partition support is outside this MVP.
- No incremental bake, clipmap, sparse streaming, or billboard renderer yet.
- Safety caps bound axis size, triangle/voxel candidate tests, and occupied
  voxel count.

### Compatibility identity

The descriptor filename, C++ modules, console command, asset paths, and report
paths retain the `VoxelMapMVP` technical identifier for compatibility with the
existing UE 5.8 implementation. The user-facing plugin name is **Chromoxel**.

### Build and validation

Build the deterministic source package:

```powershell
python tools/build_package.py
```

The source was validated with Unreal Engine 5.8 on Win64. UnrealHeaderTool and
UnrealBuildTool completed the clean host-project build with UBA disabled and
one parallel action. See [VALIDATION.md](VALIDATION.md) for the release record.

### License

Chromoxel is released under the [Apache License 2.0](LICENSE).

---

<a id="简体中文"></a>

## 简体中文

Chromoxel 提供一套紧凑的编辑器流程，用于表面体素化和 Deferred BaseColor 捕获。插件将
占用信息保存为确定性的稀疏 Block，并在复制出的输出地图中生成可持久化的 HISM 预览。
源地图不会被覆盖。

### 功能特点

- 收集可见、静态且启用碰撞的 Static Mesh、ISM 和 HISM 组件。
- 使用 CPU 三角形/AABB 表面体素化，并设置明确的工作量上限。
- 使用 `uint64` 占用掩码存储确定性的 `4 × 4 × 4` Block。
- 从六个正交方向执行 Deferred `SCS_BaseColor` 和线性深度捕获。
- 在 `UVoxelMapDataAsset` 中以规范的 `0x00RRGGBB` sRGB 格式保存颜色。
- 在 HISM 自定义数据进入 BaseColor 前正确执行 sRGB 到线性颜色转换。
- 输出地图和 HISM 预览 Actor 可持久化保存；重复烘焙会原位更新。
- 提供编辑器菜单命令和无人值守 Commandlet 入口。
- 在 `Saved/VoxelMapMVP` 下生成详细 JSON 诊断报告。

### 安装

#### 源码 ZIP

1. 从 [`dist`](dist) 目录或最新 GitHub Release 下载
   `chromoxel-unreal-0.2.0-UE5.8-source.zip`。
2. 将 ZIP 中的 `Chromoxel` 文件夹解压到 `<你的工程>/Plugins/Chromoxel`。
3. 不要从其他机器复制生成的 `Binaries`、`Intermediate` 或 `Saved` 目录。
4. 重新生成工程文件，并构建 Win64 Editor Target。
5. 如果 Unreal 提示，启用 **Chromoxel**，然后重启编辑器。

安装包仅包含插件源码，不包含 Unreal Engine 代码、Starter Content、工程地图或第三方素材包。

### 编辑器流程

打开受支持的关卡，在 **Tools** 菜单中选择：

`Bake Current Level (25 cm)`

该命令会创建或更新：

- `/Game/VoxelMapMVP/Data/VM_<Level>`；
- `/Game/VoxelMapMVP/Maps/<Level>_Voxelized`；
- `/Game/VoxelMapMVP/Materials/M_VoxelMapPreview_BaseColor`；
- 一个可持久化的 HISM 预览 Actor；
- `Saved/VoxelMapMVP` 下的 JSON 烘焙报告。

参与体素化的源 Mesh 只会在复制出的输出地图中被隐藏；原始地图不会被保存或修改。

### Commandlet

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

Commandlet 需要可执行渲染的 Client World、非 Null RHI，以及 Deferred Renderer
（`r.ForwardShading=0`）。如果无法捕获 BaseColor，它会直接失败并停止，不会使用带光照的
SceneColor 作为替代结果。

### 当前限制

- 只生成表面体素壳，不填充实心体积。
- 暂不支持 Landscape、Skeletal Mesh、PCG、Foliage 或 Nanite 回退方案。
- BaseColor 捕获目前只支持 Static Mesh、ISM 和 HISM。
- 通用 World Partition 支持不在当前 MVP 范围内。
- 暂无增量烘焙、Clipmap、稀疏流送或 Billboard Renderer。
- 通过安全上限约束单轴尺寸、三角形/体素候选测试次数和有效体素数量。

### 兼容性标识

描述文件名、C++ Module、控制台命令、资产路径和报告路径继续保留 `VoxelMapMVP` 技术标识，
以兼容已有 UE 5.8 实现。面向用户显示的插件名称为 **Chromoxel**。

### 构建与验证

生成确定性的源码安装包：

```powershell
python tools/build_package.py
```

源码已在 Win64 的 Unreal Engine 5.8 上完成验证。UnrealHeaderTool 与 UnrealBuildTool
在禁用 UBA、限制为单并行动作的干净 HostProject 中成功完成构建。发布验证记录见
[VALIDATION.md](VALIDATION.md)。

### 许可证

Chromoxel 采用 [Apache License 2.0](LICENSE)。
