# Chromoxel for Blender 5.1

**Texture-aware, symmetry-safe voxelization for Blender.**

**面向 Blender、能够保留贴图细节与模型对称性的体素化工具。**

**Version / 版本：** 0.5.0 · **Status / 状态：** Beta · **Target / 目标版本：** Blender 5.1

[English](#english) · [简体中文](#简体中文)

![Chromoxel multi-model and multi-level voxelization comparison](docs/images/chromoxel-multi-model-multi-level-preview.png)

> Four source meshes compared at coarse, medium, and fine voxel sizes. The
> image demonstrates texture-aware colour sampling, symmetry preservation,
> concave NGON handling, and stable edge coverage.
>
> 四种源模型在粗、中、细三种体素尺寸下的对比，展示贴图颜色采样、对称性保持、凹 NGON
> 处理和稳定的边缘解析能力。

---

<a id="english"></a>

## English

Chromoxel converts a selected mesh into a coloured surface-voxel shell. It
provides a lightweight Geometry Nodes preview for iteration and a realized
**Bake to Mesh** result for rendering, export, and downstream editing.

### Highlights

- Samples BaseColor from a selected UV map and image texture.
- Preserves proven local X/Y/Z reflection symmetry on symmetric source meshes.
- Handles closed meshes, Blender's stock Suzanne, curved surfaces, sharp
  corners, and concave NGON prisms.
- Optionally builds a private watertight repair copy without modifying the
  source object.
- Uses point-domain data and cube instancing for responsive previews.
- Processes the active mesh, all selected meshes, or a chosen collection.
- Provides Coarse/Medium/Fine presets and repeatable Object/Custom grid origins.
- Estimates candidate work and memory before fine-resolution jobs.
- Reports progress and supports cancellation between bounded task chunks.
- Reuses a bounded sampling cache between Preview and Bake.
- Uses adaptive sparse surface candidates and samples only a proved symmetry
  fundamental domain before exact orbit closure.
- Supports debounced live updates for transforms, geometry, voxel size, and
  cube gap changes on the active source.
- Produces realized cube geometry with a `voxel_color` attribute when baked.
- Cleans up only data created and tagged by Chromoxel.

### Install

#### Blender extension package (recommended)

1. Download `chromoxel-blender-0.5.0-extension.zip` from the [`dist`](dist)
   directory or the latest GitHub Release.
2. In Blender 5.1, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk** and select the downloaded ZIP.
4. Enable **Chromoxel**.
5. In the 3D Viewport, press `N` and open the **Voxelizer** tab.

#### Legacy add-on package

Use `chromoxel-blender-0.5.0.zip` when installing through a workflow that
expects the traditional top-level `voxelizer` folder.

### Quick start

1. Create or import a textured Mesh and select it.
2. Open **3D Viewport > Sidebar (`N`) > Voxelizer**.
3. Choose **Active**, **Selected**, or **Collection** source scope.
4. Apply **Coarse**, **Medium**, or **Fine**, or enter a custom **Voxel Size**.
5. Keep **Object Origin** for a stable local grid, or choose a custom origin.
6. Keep **Auto Watertight Copy** enabled if a source is not closed manifold.
7. Select the UV map and BaseColor image, or use the fallback colour.
8. Click **Estimate Work**, then **Add / Update Chromoxel**.
9. Use **Start Live** for active-source iteration, or **Bake to Mesh** for
   independent, realized voxel geometry.

### Preview and bake

| Mode | Best for | Output |
| --- | --- | --- |
| Preview | Interactive look development | Point carrier with Geometry Nodes cube instances |
| Bake to Mesh | Cycles rendering, export, and final editing | Realized cubes with a corner-domain colour attribute |

The preview object carries the editable Geometry Nodes modifier; original
source meshes and modifiers are not rewritten. Preview and Bake share cached
occupancy and colour samples when all geometry, grid, repair, UV, image, and
fallback-colour inputs still match. **Clear Sampling Cache** frees that memory
without deleting outputs.

For the current release, use **Bake to Mesh** for final Cycles renders because
colour propagation through unrealized point instances can depend on the
renderer and Blender version.

### Symmetry behavior

Chromoxel tests local X, Y, and Z reflection symmetry independently using
reflected vertices, edges, and polygon boundaries. Only axes proven symmetric
receive a centered sampling lattice and mirrored occupancy closure. An
intentionally asymmetric source is left asymmetric.

### Current limits

- CPU BVH/grid sampling; GPU voxelization is not implemented yet.
- Surface shell only; it does not generate a filled solid volume.
- One UV map and one BaseColor image per operation.
- No UDIM, procedural shader baking, sparse bricks, clipmaps, or automatic LOD
  hierarchy yet.
- Default per-source limits are 1,500,000 candidates and 250,000 active
  voxels; Advanced settings can change limits, chunk size, and cache budget.

### Compatibility identity

The extension ID remains `textured_voxelizer_mvp`, and the runtime ownership ID
remains `org.openai.textured_voxelizer_mvp`, so existing saved files and tagged
outputs continue to work. These are compatibility identifiers; the user-facing
product name is **Chromoxel**.

### Build and validate

Build deterministic legacy and extension packages:

```powershell
python tools/build_packages.py
```

Run the portable smoke test with Blender 5.1:

```powershell
blender --background --factory-startup --python tests/release_smoke.py
blender --background --factory-startup --python tests/blender_v050_regression.py
blender --background --factory-startup --python tests/blender_v050_performance.py
```

See [VALIDATION.md](VALIDATION.md) for the verified Blender version and release
checks.

### License

Chromoxel is released under the [Apache License 2.0](LICENSE).

---

<a id="简体中文"></a>

## 简体中文

Chromoxel 可将选中的模型转换为带颜色的表面体素壳。插件提供轻量级 Geometry Nodes
实时预览用于反复调整，也可通过 **Bake to Mesh** 生成实体化网格，用于渲染、导出和后续编辑。

### 功能特点

- 从指定 UV Map 和图片贴图中采样 BaseColor。
- 对源模型已确认的局部 X/Y/Z 镜像轴保持精确对称。
- 支持闭合模型、Blender 默认猴头、曲面、锐利棱角和凹 NGON 棱柱。
- 对非流形模型可创建内部水密修复副本，不修改源对象。
- 使用点域数据和立方体实例，保持预览响应速度。
- 支持处理当前活动对象、全部选中对象或指定集合。
- 提供粗/中/细三档预设，以及可重复的对象原点/自定义原点网格。
- 可在细粒度任务前预估候选工作量和内存。
- 长任务按有界 Chunk 报告进度，并可在 Chunk 之间取消。
- 预览与烘焙共享受内存上限约束的采样缓存。
- 使用自适应稀疏表面候选；对已证明对称的模型只采样基本域，再精确闭合镜像轨道。
- 支持变换、几何体、体素尺寸和立方体间隙的防抖实时更新。
- 烘焙后生成实际立方体几何体，并写入 `voxel_color` 颜色属性。
- 清理操作只删除由 Chromoxel 创建并标记的数据。

### 安装

#### Blender 扩展安装包（推荐）

1. 从 [`dist`](dist) 目录或最新 GitHub Release 下载
   `chromoxel-blender-0.5.0-extension.zip`。
2. 在 Blender 5.1 中打开 **编辑（Edit）> 偏好设置（Preferences）> 插件（Add-ons）**。
3. 选择 **从磁盘安装（Install from Disk）**，并选中下载的 ZIP。
4. 启用 **Chromoxel**。
5. 回到 3D 视图，按 `N` 打开侧栏，然后进入 **Voxelizer** 标签页。

#### 传统插件安装包

如果安装流程要求 ZIP 内包含传统的顶层 `voxelizer` 文件夹，请使用
`chromoxel-blender-0.5.0.zip`。

### 快速开始

1. 创建或导入一个带贴图的 Mesh，并选中该对象。
2. 打开 **3D 视图 > 侧栏（`N`）> Voxelizer**。
3. 选择 **Active**、**Selected** 或 **Collection** 源范围。
4. 使用 **Coarse / Medium / Fine** 预设，或手动输入 **Voxel Size**。
5. 保持 **Object Origin** 获得稳定的局部网格，或指定自定义原点。
6. 如果源模型不是闭合流形，保持 **Auto Watertight Copy** 启用。
7. 指定 UV Map 与 BaseColor 图片，或使用备用颜色。
8. 先点 **Estimate Work**，再点 **Add / Update Chromoxel**。
9. 活动对象迭代可使用 **Start Live**；最终结果使用 **Bake to Mesh**。

### 预览与烘焙

| 模式 | 适合用途 | 输出结果 |
| --- | --- | --- |
| Preview | 交互式外观调整 | 使用 Geometry Nodes 立方体实例的点载体 |
| Bake to Mesh | Cycles 渲染、导出和最终编辑 | 带角点域颜色属性的实体立方体网格 |

Geometry Nodes 修改器位于预览对象上，原始 Mesh 及其修改器不会被重写。当几何、网格、修复、
UV、图片和备用颜色输入完全一致时，Preview 与 Bake 会复用同一份占用及颜色缓存。
**Clear Sampling Cache** 只释放缓存，不删除已有输出。

当前版本进行最终 Cycles 渲染时，建议使用 **Bake to Mesh**。未实体化点实例的颜色传递
可能因渲染器和 Blender 版本而有所不同。

### 对称性行为

Chromoxel 使用镜像顶点、边和多边形边界，分别验证局部 X、Y、Z 反射对称性。只有通过
验证的轴才会使用以对称面为中心的采样网格和镜像占用闭包。刻意制作的不对称模型不会被
强制改为对称。

### 当前限制

- 当前采用 CPU BVH/网格采样，尚未实现 GPU 体素化。
- 只生成表面体素壳，不生成填满内部的实心体积。
- 每次操作支持一个 UV Map 和一张 BaseColor 图片。
- 暂不支持 UDIM、程序化 Shader 烘焙、稀疏 Brick、Clipmap 或自动 LOD 层级。
- 默认每个源对象最多处理 1,500,000 个候选单元并输出 250,000 个有效体素；可在
  Advanced 中调整上限、任务 Chunk 和缓存预算。

### 兼容性标识

扩展 ID 继续使用 `textured_voxelizer_mvp`，运行时所有权 ID 继续使用
`org.openai.textured_voxelizer_mvp`，以兼容已有 `.blend` 文件和已标记输出。这些是
兼容性技术标识；面向用户的产品名称为 **Chromoxel**。

### 构建与验证

生成确定性的传统插件包和扩展包：

```powershell
python tools/build_packages.py
```

使用 Blender 5.1 执行可移植 Smoke Test：

```powershell
blender --background --factory-startup --python tests/release_smoke.py
blender --background --factory-startup --python tests/blender_v050_regression.py
blender --background --factory-startup --python tests/blender_v050_performance.py
```

已验证的 Blender 版本和发布检查记录见 [VALIDATION.md](VALIDATION.md)。

### 许可证

Chromoxel 采用 [Apache License 2.0](LICENSE)。
