# Chromoxel

**Texture-aware voxelization for Unreal Engine and Blender.**  
**面向 Unreal Engine 与 Blender、能够保留贴图细节的体素化工具集。**

[English](#english) · [简体中文](#简体中文)

## Showcase / 能力展示

### Multi-model and multi-level voxelization / 多模型与多体素等级

![Four original models compared at three voxel sizes](docs/images/chromoxel-multi-model-multi-level-preview.png)

The Blender implementation is tested on Suzanne, a UV sphere, a torus, and a
concave NGON prism at coarse, medium, and fine voxel sizes. The comparison
covers curved surfaces, holes, corners, thin features, and symmetric forms.

Blender 版本使用猴头、UV 球、圆环和凹 NGON 棱柱，在粗、中、细三种体素尺寸下进行验证，
覆盖曲面、孔洞、棱角、薄结构和对称模型等情况。

### Character-scale voxel budgets / 角色级体素预算

![Three textured characters compared at original, 2K, 20K, and 100K uniform voxel levels](docs/images/chromoxel-character-uniform-levels.png)

Three textured characters are compared as the original meshes and at
approximately 2K, 20K, and 100K uniform voxel budgets. This Chromoxel 0.7 CLI
acceptance image demonstrates progressive silhouette convergence,
texture-colour retention, and a consistent cell size within each 100K result;
target-count fitting allows up to 5% tolerance. Blender 0.9.2 retains this
output contract and exposes target-count fitting directly in the guided UI.

三个带纹理角色分别展示原始模型以及约 2K、20K、100K 的均匀体素预算结果。
这张 Chromoxel 0.7 CLI 验收图展示了轮廓随体素预算逐级收敛、纹理颜色保留，
以及每个 100K 结果内部一致的体素尺寸；目标数量拟合允许最多 5% 的误差。
Blender 0.9.2 保持相同输出约定，并将目标数量拟合直接加入编号式操作面板。

**Character test assets / 角色测试素材：** locally supplied Mixamo character
files used for validation. Only this rendered comparison is included; source
meshes and textures are not redistributed. / 本图使用本地提供的 Mixamo 角色文件
进行验证；仓库仅收录渲染对比图，不重新分发源模型与贴图。

### Million-face models and separated parts / 百万面模型与分离部件

![Four dense Tripo models compared at original, 2K, 20K, and 100K voxel levels](docs/images/chromoxel-tripo-four-model-levels.png)

Four locally supplied Tripo meshes with roughly 1.38–1.49 million source faces
are compared at the original, approximately 2K, 20K, and 100K Uniform levels.
Every row uses the same -45-degree view and Cycles pipeline; the labels include
source topology, input and visible voxel counts, removed enclosed cells, final
faces, and cell size.

Blender 0.9.2 adds **Target Count** and enables **Preserve Separate Parts** by
default. The latter prevents nearby disconnected elements—such as the balloons
and character head in the final row—from being fused by whole-object repair,
while stock Suzanne still keeps its automatic open-surface repair path.

四个本地提供、原始面数约 138–149 万的 Tripo 模型分别展示原始模型以及约 2K、20K、
100K 的 Uniform 结果。各行统一使用 -45° 视角和 Cycles 管线；标注包含源拓扑、输入与
可见体素数、剔除的封闭内部体素、最终面数和体素尺寸。

Blender 0.9.2 新增 **目标数量**，并默认开启 **保留分离部件**。后者会避免整物体修复把
彼此靠近但不连接的元素粘在一起——例如最后一行的气球与角色头部——同时默认猴头仍可使用
自动开放表面修复路径。

**Dense-model test assets / 高密度模型测试素材：** locally supplied Tripo
outputs used only for validation. The repository contains the rendered
comparison, not the source GLB files or textures. / 使用本地提供的 Tripo 输出进行验证；
仓库仅收录渲染对比图，不重新分发源 GLB 或贴图。

### Full-scene comparisons / 完整场景对比

![KayKit training range compared across original, legacy uniform, new uniform, and adaptive Chromoxel rendering](docs/images/chromoxel-training-range-old-vs-adaptive.png)

The four panels use the same KayKit training-range scene, camera, materials,
lighting, and Cycles pipeline. They compare the original render, the legacy
uniform `0.16 BU` result, the current uniform `0.16 BU` result, and current
adaptive refinement down to a `0.04 BU` minimum.

We optimized this scene specifically for circular bullseyes, thin
high-contrast markings, and mixed-detail environment surfaces. Texture-aware
upsampling concentrates smaller cells around markings, while
surface-preserving planar refinement keeps broad walls and floors flush instead
of introducing bumps or grooves between voxel levels.

四格使用同一个 KayKit 靶场场景、相机、材质、灯光和 Cycles 渲染管线，依次对比原始场景、
旧版统一 `0.16 BU`、新版统一 `0.16 BU`，以及最小细分至 `0.04 BU` 的新版自适应结果。

我们针对该场景中的圆形靶纸、细小高对比度标记和混合细节环境表面进行了专门优化：
纹理感知上采样会把更小的体素集中到图案附近；保持表面共面的平面细分则让大面积墙面和
地板维持平整，避免不同体素等级之间产生凹凸或沟槽。

**Asset source / 素材来源：** [KayKit: Prototype Bits 1.1 (FREE)](https://kaylousberg.itch.io/prototype-bits),
created and distributed by / 作者与发行者：[Kay Lousberg](https://www.kaylousberg.com/)。
The asset pack is licensed under / 素材采用
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)。
Only rendered comparison images are included; the original asset files are not
redistributed here. / 仓库仅包含渲染对比图，不重新分发原始素材文件。

---

<a id="english"></a>

## English

Chromoxel explores a practical workflow for turning textured meshes and scenes
into editable, renderable voxel geometry. The project provides two
platform-specific implementations under separate branches.

### Implementations

| Platform | Target | Current focus | Branch |
| --- | --- | --- | --- |
| Blender | Blender 5.1 | Guided preview/Bake, target-count fitting, separated-part preservation, and GPU-assisted Uniform sampling | [Blender implementation](https://github.com/SKu11zZ/Chromoxel/tree/blender) |
| Unreal Engine | Unreal Engine 5.8 | Editor-side voxelization, BaseColor capture, and HISM scene preview | [Unreal implementation](https://github.com/SKu11zZ/Chromoxel/tree/unreal) |

### Quick start

#### Blender 5.1+

1. Download `chromoxel-blender-0.9.2-extension.zip` from the
   [Blender branch `dist`](https://github.com/SKu11zZ/Chromoxel/tree/blender/dist)
   or a GitHub Release.
2. In Blender, choose **Edit > Preferences > Add-ons > Install from Disk**,
   select the ZIP, and enable **Chromoxel**.
3. Create or import one or more Mesh objects, select them, then open
   **3D Viewport > Sidebar (`N`) > Voxelizer**.
4. Choose the UI language at the top, then select **Active**, **Selected**, or
   **Collection** and one of the four Bake outputs.
5. In Step 2 choose **Voxel Size** for Adaptive detail or **Target Count** for
   an approximate 100–100,000 Uniform voxel budget. Keep **Preserve Separate
   Parts** enabled when disconnected props must remain separated.
6. Click **Add / Update Chromoxel** to build the editable point Preview. Keep
   **Compute Backend: Auto** unless a specific CPU or GPU path is required.
7. Select the Preview to edit, paint, add, move, or delete individual voxels.
   For deterministic Cycles rendering or export, choose a **Bake Output** and
   click **Bake to Mesh**.

See the [complete Blender guide](https://github.com/SKu11zZ/Chromoxel/tree/blender#quick-start)
for Bake modes, `.vox` interchange, CLI use, performance settings, and current
limits.

#### Unreal Engine 5.8

1. Download `chromoxel-unreal-0.3.0-UE5.8-source.zip` from the
   [Unreal branch `dist`](https://github.com/SKu11zZ/Chromoxel/tree/unreal/dist)
   or a GitHub Release. Extract its `Chromoxel` folder to
   `<YourProject>/Plugins/Chromoxel`.
2. Regenerate project files, build the Win64 Editor target, enable
   **Chromoxel**, and restart Unreal Editor if requested.
3. Open the source level. Eligible inputs are visible, static,
   collision-enabled Static Mesh, ISM, and HISM components. Select Actors or a
   `Volume` first when using a scoped bake.
4. Open **Tools > Chromoxel**, choose **Bake World**, **Bake Selected**, or
   **Bake Selected Volume**, then use Fine, Standard, or Coarse for 10, 25, or
   50 cm voxels.
5. Open the generated map under `/Game/VoxelMapMVP/Maps`. Chromoxel also writes
   a data asset, preview material, persistent HISM preview, and a JSON report
   under `Saved/VoxelMapMVP`. The source level is not overwritten.

BaseColor capture requires the Deferred renderer and a non-Null RHI. See the
[complete Unreal guide](https://github.com/SKu11zZ/Chromoxel/tree/unreal#editor-workflow)
for generated paths, commandlet use, supported components, and current limits.

### Shared goals

- Preserve recognizable silhouettes, corners, holes, and thin features.
- Retain source colour and texture information wherever the platform permits.
- Keep symmetric source meshes symmetric after voxelization.
- Provide a fast preview path and a concrete baked-output path.
- Scale from individual props to small environment scenes.
- Keep generated data identifiable and safely removable.

### Project status

Chromoxel is currently a beta-stage technical project. The Blender and Unreal
implementations do not share a runtime or file format yet; they share the same
visual goal and are developed as platform-native tools.

Installation, usage, compatibility notes, packages, and validation records are
maintained in the corresponding platform branch.

### License

Chromoxel source code and project documentation are released under the
[Apache License 2.0](LICENSE). Third-party demonstration assets retain their
respective licenses as credited above.

---

<a id="简体中文"></a>

## 简体中文

Chromoxel 探索一套实用工作流，将带贴图的模型与场景转换为可编辑、可渲染的体素几何体。
项目目前针对两个平台分别提供原生实现，并存放在独立分支中。

### 平台实现

| 平台 | 目标版本 | 当前重点 | 分支 |
| --- | --- | --- | --- |
| Blender | Blender 5.1 | 编号式预览/烘焙、目标数量拟合、分离部件保护和 GPU 辅助 Uniform 采样 | [Blender 实现](https://github.com/SKu11zZ/Chromoxel/tree/blender) |
| Unreal Engine | Unreal Engine 5.8 | 编辑器场景体素化、BaseColor 捕获和 HISM 场景预览 | [Unreal 实现](https://github.com/SKu11zZ/Chromoxel/tree/unreal) |

### 快速上手

#### Blender 5.1+

1. 从 [Blender 分支的 `dist`](https://github.com/SKu11zZ/Chromoxel/tree/blender/dist)
   或 GitHub Release 下载 `chromoxel-blender-0.9.2-extension.zip`。
2. 在 Blender 中选择 **Edit > Preferences > Add-ons > Install from Disk**，
   选择该 ZIP 并启用 **Chromoxel**。
3. 创建或导入一个或多个 Mesh，选中后打开
   **3D Viewport > Sidebar（`N`）> Voxelizer**。
4. 在顶部选择界面语言，再选择 **Active**、**Selected** 或 **Collection**，以及四种
   Bake 输出之一。
5. 在第 2 步选择 **Voxel Size** 进行 Adaptive 细分，或选择 **Target Count** 拟合约
   100–100,000 个 Uniform 体素。分离道具需要保持间隙时请开启
   **Preserve Separate Parts**。
6. 点击 **Add / Update Chromoxel**，生成可编辑的点 Preview。一般保持
   **Compute Backend: Auto**，只有需要固定计算路径时才手动选择 CPU 或 GPU。
7. 选择 Preview 后，可以编辑、上色、添加、移动或删除单个体素。需要稳定用于 Cycles
   渲染或导出时，选择 **Bake Output**，再点击 **Bake to Mesh**。

完整的 Bake 模式、`.vox` 互换、CLI、性能参数和限制见
[Blender 详细说明](https://github.com/SKu11zZ/Chromoxel/tree/blender#快速开始)。

#### Unreal Engine 5.8

1. 从 [Unreal 分支的 `dist`](https://github.com/SKu11zZ/Chromoxel/tree/unreal/dist)
   或 GitHub Release 下载 `chromoxel-unreal-0.3.0-UE5.8-source.zip`，将其中的
   `Chromoxel` 文件夹解压到 `<你的工程>/Plugins/Chromoxel`。
2. 重新生成工程文件，构建 Win64 Editor Target，启用 **Chromoxel**，并按提示重启编辑器。
3. 打开源关卡。可处理的输入为可见、Static、启用碰撞的 Static Mesh、ISM 和 HISM
   组件；若要限定范围，先选中 Actor 或 `Volume`。
4. 打开 **Tools > Chromoxel**，选择 **Bake World**、**Bake Selected** 或
   **Bake Selected Volume**；Fine、Standard、Coarse 分别对应 10、25、50 cm 体素。
5. 在 `/Game/VoxelMapMVP/Maps` 中打开生成的体素化地图。插件还会创建 Data Asset、
   预览材质、持久化 HISM Preview，并在 `Saved/VoxelMapMVP` 写入 JSON 报告；
   源关卡不会被覆盖。

BaseColor 捕获需要 Deferred Renderer 和非 Null RHI。生成路径、Commandlet、支持范围与限制见
[Unreal 详细说明](https://github.com/SKu11zZ/Chromoxel/tree/unreal#编辑器流程)。

### 共同目标

- 保留可识别的轮廓、棱角、孔洞和薄结构。
- 在平台允许的范围内保留源模型颜色与贴图信息。
- 对称源模型在体素化后仍保持对称。
- 同时提供快速预览路径和可实际使用的烘焙输出路径。
- 从单个道具扩展到小型环境场景。
- 让生成数据可识别、可追踪并能够安全清理。

### 项目状态

Chromoxel 当前处于 Beta 技术验证阶段。Blender 与 Unreal 版本暂不共享运行时或文件格式，
但遵循相同的视觉目标，并分别采用平台原生方式实现。

安装步骤、使用方法、兼容性说明、安装包和验证记录均维护在对应的平台分支中。

### 许可证

Chromoxel 源代码与项目文档采用 [Apache License 2.0](LICENSE)。第三方演示素材继续遵循
上文标注的各自许可证。

