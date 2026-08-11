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
target-count fitting allows up to 5% tolerance. The Blender 0.8 implementation
retains this output contract while accelerating source preparation, sampling,
and colour reads.

三个带纹理角色分别展示原始模型以及约 2K、20K、100K 的均匀体素预算结果。
这张 Chromoxel 0.7 CLI 验收图展示了轮廓随体素预算逐级收敛、纹理颜色保留，
以及每个 100K 结果内部一致的体素尺寸；目标数量拟合允许最多 5% 的误差。
Blender 0.8 实现保持相同输出约定，并加速源数据准备、采样和颜色读取。

**Character test assets / 角色测试素材：** locally supplied Mixamo character
files used for validation. Only this rendered comparison is included; source
meshes and textures are not redistributed. / 本图使用本地提供的 Mixamo 角色文件
进行验证；仓库仅收录渲染对比图，不重新分发源模型与贴图。

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
| Blender | Blender 5.1 | Live preview, texture sampling, symmetry-safe grids, and Bake to Mesh | [Blender implementation](https://github.com/SKu11zZ/Chromoxel/tree/blender) |
| Unreal Engine | Unreal Engine 5.8 | Editor-side voxelization, BaseColor capture, and HISM scene preview | [Unreal implementation](https://github.com/SKu11zZ/Chromoxel/tree/unreal) |

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
| Blender | Blender 5.1 | 实时预览、贴图采样、对称安全网格和 Bake to Mesh | [Blender 实现](https://github.com/SKu11zZ/Chromoxel/tree/blender) |
| Unreal Engine | Unreal Engine 5.8 | 编辑器场景体素化、BaseColor 捕获和 HISM 场景预览 | [Unreal 实现](https://github.com/SKu11zZ/Chromoxel/tree/unreal) |

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

