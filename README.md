# Chromoxel（纹彩体素）for Blender 5.1

**Adaptive, texture-aware, symmetry-safe voxelization for Blender.**

**面向 Blender 的自适应、纹理感知、对称安全体素化工具。**

**Version / 版本：** 0.6.0 · **Status / 状态：** Beta · **Target / 目标版本：** Blender 5.1

[English](#english) · [简体中文](#简体中文)

![Chromoxel multi-model and multi-level voxelization comparison](docs/images/chromoxel-multi-model-multi-level-preview.png)

> Four source meshes at coarse, medium, and fine voxel sizes. The comparison
> demonstrates texture colour sampling, exact symmetry closure, curved and
> sharp-edge coverage, and concave NGON handling.
>
> 四种源模型在粗、中、细三种体素尺寸下的对比，展示贴图颜色采样、精确对称闭包、
> 曲面与锐边覆盖，以及凹 NGON 处理能力。

![Chromoxel 0.6 bullseye texture-adaptive comparison](docs/images/chromoxel-adaptive-bullseye.png)

> v0.6 visual acceptance: the uniform 0.50 BU grid misses most of the circular
> marking, while bounded adaptive L3 refinement resolves the ring down to
> 0.0625 BU without globally applying that fine voxel size.
>
> v0.6 圆形纹理验收：统一 0.50 BU 网格会丢失大部分圆环；受预算约束的 L3
> 自适应细分仅在纹理边界降至 0.0625 BU，无需让整个模型都使用最小体素。

---

<a id="english"></a>

## English

Chromoxel converts selected meshes into coloured surface-voxel shells. It
provides a lightweight Geometry Nodes preview for iteration and a realized
**Bake to Mesh** result for Cycles rendering, export, and downstream editing.

### What is new in 0.6

- **Adaptive Texture & Geometry Refinement** is now the default detail mode.
- A base voxel can be subdivided on a deterministic power-of-two lattice when
  its texture footprint crosses a high-contrast boundary or it lies near a
  sharp geometric edge.
- A global voxel and sampling budget prioritizes the highest-error regions and
  prevents unbounded scene growth.
- Base Color images can be found automatically from material node graphs when
  no manual image override is selected.
- Texture reads support bilinear reconstruction and a nine-tap UV footprint
  analysis instead of one nearest texel per voxel.
- Adaptive refinement is mirrored over every proven geometry-symmetry axis.
  Geometry stays exactly symmetric while colours are sampled independently.
- Preview and Bake now carry `voxel_size` and `voxel_level` in addition to the
  existing `voxel_color` attribute.
- **Uniform** mode preserves the 0.5 single-size workflow for compatibility.

### Highlights

- Processes the active mesh, all selected meshes, or a chosen collection.
- Supports image-textured materials, a manual image override, and per-material
  flat Base Color fallback.
- Preserves proven local X/Y/Z reflection symmetry on symmetric source meshes.
- Handles closed meshes, stock Suzanne through a private repair copy, curved
  surfaces, sharp corners, thin surfaces, and concave NGON prisms.
- Uses sparse triangle-expanded surface candidates and a conservative
  centre-to-surface coverage radius.
- Provides Coarse, Medium, and Fine base-size presets with repeatable Object or
  Custom grid origins.
- Reports progress, supports cancellation, estimates work, and enforces
  candidate, refinement, voxel, and memory limits.
- Reuses a bounded sampling cache between Preview and Bake.
- Supports debounced live updates without rewriting source meshes or modifiers.
- Cleans up only data created and tagged by Chromoxel.

### Install

#### Blender extension package (recommended)

1. Download `chromoxel-blender-0.6.0-extension.zip` from [`dist`](dist) or the
   latest GitHub Release.
2. In Blender 5.1, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk** and select the ZIP.
4. Enable **Chromoxel**.
5. In the 3D Viewport, press `N` and open the **Voxelizer** tab.

Use `chromoxel-blender-0.6.0.zip` only when a legacy add-on installer expects a
top-level `voxelizer` directory inside the archive.

### Quick start

1. Create or import one or more Mesh objects and select them.
2. Open **3D Viewport > Sidebar (`N`) > Voxelizer**.
3. Choose **Active**, **Selected**, or **Collection**.
4. Choose a base **Voxel Size** or apply Coarse, Medium, or Fine.
5. Keep **Detail Mode: Adaptive** and start with **Max Detail Level: 2**.
6. Keep **Auto Material Images** enabled. Select an Image Override only when
   automatic material discovery is not the desired source.
7. Keep **Auto Watertight Copy** enabled for open or non-manifold meshes.
8. Click **Estimate Work**, then **Add / Update Chromoxel**.
9. Use **Bake to Mesh** for a realized Cycles/export result.

With a base size of `0.16 BU` and detail level 2, Chromoxel can keep broad flat
areas at `0.16`, refine sharp or textured regions to `0.08`, and refine the
highest-error texture boundaries to `0.04` automatically.

### Adaptive behavior

Adaptive mode uses a bounded error-priority process:

1. Build the base surface grid.
2. Reconstruct the Base Color with bilinear filtering and inspect a 3×3 UV
   footprint for colour variation while keeping the centre sample as the voxel
   colour.
3. Detect nearby boundary/non-coplanar geometry edges.
4. Reject circumsphere-only outer cells with an expanded AABB overlap guard,
   then rank refinement groups by texture or geometry error.
5. Replace accepted parents with occupied half-size children until the maximum
   level, sampling limit, or voxel limit is reached.
6. Mirror the refinement orbit over proven symmetry axes and sample each
   mirrored colour independently.

The default geometry refinement depth is one level, while texture detail may
continue to the selected maximum. This preserves sharp silhouettes without
allowing every hard-surface edge to expand through all levels.

### Preview and Bake

| Mode | Best for | Output |
| --- | --- | --- |
| Preview | Interactive look development | POINT carrier with variable-size Geometry Nodes cube instances |
| Bake to Mesh | Cycles, export, and final editing | Realized cubes with colour, size, and level attributes |

Output attributes:

- `voxel_color`: sampled scene-linear colour.
- `voxel_size`: actual cell size before the display gap is applied.
- `voxel_level`: `0` for the base grid, `1` for half size, `2` for quarter size,
  and so on.

Preview and Bake share cached occupancy, colour, size, and level samples when
their geometry, grid, material, image, adaptive, and budget inputs match.

### Symmetry behavior

Chromoxel proves local X, Y, and Z reflection symmetry independently from
vertex correspondence and reflected edge/polygon topology. Only proven axes
receive a centered lattice and exact orbit closure. Intentionally asymmetric
sources remain asymmetric. In Adaptive mode, one high-error cell causes its
whole proven symmetry orbit to refine, so variable cell sizes cannot introduce
geometric asymmetry.

### Current limits

- CPU BVH/grid/refinement sampling; GPU voxelization is not implemented yet.
- Surface shell only; the interior is not filled as a solid volume.
- Automatic material discovery supports UV-driven images upstream of a
  Principled Base Color input. The manual Image Override remains available.
- Procedural shader baking, UDIM tile sampling, alpha-cutout occupancy, sparse
  bricks, clipmaps, and camera-dependent LOD are not implemented yet.
- Default per-source limits are 1,500,000 sampling/refinement tests and 250,000
  output voxels. Advanced settings can change these limits and cache memory.

### Compatibility identity

The extension ID remains `textured_voxelizer_mvp`, and the runtime ownership ID
remains `org.openai.textured_voxelizer_mvp`. Existing saved files, scripts that
unpack the 0.5 four-value sampling result, and tagged outputs remain compatible.

### Build and validate

```powershell
python tools/build_packages.py

blender --background --factory-startup --python tests/release_smoke.py
blender --background --factory-startup --python tests/blender_v050_regression.py
blender --background --factory-startup --python tests/blender_v050_performance.py
blender --background --factory-startup --python tests/blender_v060_adaptive.py
```

See [VALIDATION.md](VALIDATION.md) for the verified Blender version and release
checks.

### License

Chromoxel is released under the [Apache License 2.0](LICENSE).

Maintainer: **Moore "Zz11uKS" Ji** (`SKu11zZ`).

---

<a id="简体中文"></a>

## 简体中文

Chromoxel（纹彩体素）可将选中的模型转换为带颜色的表面体素壳。插件提供轻量级
Geometry Nodes 预览用于迭代，也可以通过 **Bake to Mesh** 生成实体网格，用于 Cycles
渲染、导出和后续编辑。

### 0.6 新功能

- 默认使用 **自适应纹理与几何细分**。
- 当基础体素跨越高对比纹理边界或靠近锐利几何边缘时，会在确定性的二分网格上自动细分。
- 使用全局采样与体素预算，优先处理误差最大的区域，避免场景规模无限增长。
- 未指定手动图片时，可从材质节点的 Base Color 链路自动寻找图片贴图。
- 使用双线性过滤和 3×3 UV 足迹分析，不再只为每个体素读取一个最近像素。
- 自适应细分会同步闭合所有已证明的几何对称轴；几何保持精确对称，颜色独立采样。
- Preview 与 Bake 在 `voxel_color` 之外新增 `voxel_size` 和 `voxel_level` 属性。
- 保留 **Uniform** 模式，兼容 0.5 的单一体素尺寸工作流。

### 功能特点

- 支持处理活动对象、全部选中对象或指定集合。
- 支持图片贴图材质、手动图片覆盖，以及按材质读取纯色 Base Color。
- 对源模型已证明的局部 X/Y/Z 镜像轴保持精确对称。
- 支持闭合模型、通过私有修复副本处理默认 Suzanne、曲面、锐角、薄面和凹 NGON 棱柱。
- 使用稀疏三角形候选扩张与保守的表面覆盖半径。
- 提供 Coarse、Medium、Fine 基础尺寸预设，以及稳定的 Object/Custom 网格原点。
- 支持工作量估算、进度、取消，以及候选、细分、体素和内存上限。
- Preview 与 Bake 共用受内存限制的采样缓存。
- 支持防抖实时更新，不修改源模型及其修改器。
- 清理操作只删除由 Chromoxel 创建并标记的数据。

### 安装

#### Blender 扩展安装包（推荐）

1. 从 [`dist`](dist) 或最新 GitHub Release 下载
   `chromoxel-blender-0.6.0-extension.zip`。
2. 在 Blender 5.1 中打开 **Edit > Preferences > Add-ons**。
3. 选择 **Install from Disk** 并选择 ZIP。
4. 启用 **Chromoxel**。
5. 回到 3D 视图，按 `N` 打开侧栏并进入 **Voxelizer** 标签页。

只有传统安装器要求 ZIP 内含顶层 `voxelizer` 文件夹时，才使用
`chromoxel-blender-0.6.0.zip`。

### 快速开始

1. 创建或导入一个或多个 Mesh 并选中。
2. 打开 **3D Viewport > Sidebar（`N`）> Voxelizer**。
3. 选择 **Active**、**Selected** 或 **Collection**。
4. 设置基础 **Voxel Size**，或使用 Coarse、Medium、Fine 预设。
5. 保持 **Detail Mode: Adaptive**，初次使用建议 **Max Detail Level: 2**。
6. 保持 **Auto Material Images** 开启；只有自动材质识别不是所需来源时才设置
   **Image Override**。
7. 对开放或非流形模型保持 **Auto Watertight Copy** 开启。
8. 点击 **Estimate Work**，再点击 **Add / Update Chromoxel**。
9. 最终 Cycles 渲染或导出时使用 **Bake to Mesh**。

例如基础尺寸为 `0.16 BU`、细分级别为 2 时，普通平面可保持 `0.16`，锐边或纹理区域
自动进入 `0.08`，误差最大的纹理边界自动进入 `0.04`，不需要逐个物体设置。

### 自适应工作方式

1. 构建基础表面体素网格。
2. 使用双线性过滤重建 Base Color，检查 3×3 UV 足迹的颜色变化，同时保留中心采样作为体素颜色。
3. 检测附近的边界边和非共面几何边。
4. 使用扩展 AABB 重叠保护剔除仅命中外接球的外层体素，再按纹理或几何误差排序细分组。
5. 在最大级别、采样上限或体素上限内，用有效的半尺寸子体素替换父体素。
6. 对已证明的对称轴同步闭合细分轨道，并分别采样镜像位置的颜色。

默认情况下，几何锐边最多细分一级，而纹理细节可以继续到用户选择的最大级别。这样既能
改善轮廓，又不会让所有硬表面边缘无限扩张。

### Preview 与 Bake

| 模式 | 适用场景 | 输出 |
| --- | --- | --- |
| Preview | 交互式外观调整 | 带可变尺寸立方体实例的 POINT 载体 |
| Bake to Mesh | Cycles、导出和最终编辑 | 带颜色、尺寸与层级属性的实体立方体 |

输出属性：

- `voxel_color`：采样后的场景线性颜色。
- `voxel_size`：应用显示间隙之前的实际体素尺寸。
- `voxel_level`：基础层为 `0`，半尺寸为 `1`，四分之一尺寸为 `2`，依次类推。

当几何、网格、材质、图片、自适应设置和预算一致时，Preview 与 Bake 会复用同一份占用、
颜色、尺寸和层级缓存。

### 对称性行为

Chromoxel 根据顶点对应关系及镜像后的边/多边形拓扑，分别证明局部 X、Y、Z 反射对称。
只有通过证明的轴才会使用居中网格与精确轨道闭包；刻意制作的不对称模型不会被强制修改。
在 Adaptive 模式中，一个高误差体素会带动整个对称轨道一起细分，因此可变尺寸不会重新引入
几何不对称。

### 当前限制

- 当前采用 CPU BVH、网格和细分采样，尚未实现 GPU 体素化。
- 只生成表面体素壳，不填充内部体积。
- 自动材质识别支持连接到 Principled Base Color 上游、使用 UV 的图片节点；仍可手动覆盖图片。
- 尚未实现程序化 Shader 自动烘焙、UDIM、基于 Alpha 的占用、稀疏 Brick、Clipmap 和相机相关 LOD。
- 默认每个源对象最多执行 1,500,000 次采样/细分测试并输出 250,000 个体素；可在 Advanced
  中调整上限和缓存内存。

### 兼容性标识

扩展 ID 继续使用 `textured_voxelizer_mvp`，运行时所有权 ID 继续使用
`org.openai.textured_voxelizer_mvp`。已有 `.blend`、使用 0.5 四项解包接口的脚本和已标记输出
仍保持兼容。

### 构建与验证

```powershell
python tools/build_packages.py

blender --background --factory-startup --python tests/release_smoke.py
blender --background --factory-startup --python tests/blender_v050_regression.py
blender --background --factory-startup --python tests/blender_v050_performance.py
blender --background --factory-startup --python tests/blender_v060_adaptive.py
```

已验证的 Blender 版本和发布检查见 [VALIDATION.md](VALIDATION.md)。

### 许可证

Chromoxel 使用 [Apache License 2.0](LICENSE)。

维护者：**Moore "Zz11uKS" Ji**（`SKu11zZ`）。
