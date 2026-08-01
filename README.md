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

### Full-scene comparisons / 完整场景对比

The left side is the original Cycles render; the right side is the Chromoxel
surface-voxel Bake rendered with Cycles.

左侧为原始 Cycles 渲染，右侧为 Chromoxel 表面体素化烘焙后的 Cycles 渲染。

![Prototype obstacle scene before and after Chromoxel voxelization](docs/images/kaykit-prototype-scene-original-vs-voxelized.png)

![Prototype training room before and after Chromoxel voxelization](docs/images/kaykit-training-room-original-vs-voxelized.png)

Both voxelized scenes use a `0.16 BU` cell size. Scene composition, lighting,
voxelization, and final rendering were produced for the Chromoxel project.

两个体素化场景均使用 `0.16 BU` 单元尺寸；场景搭建、灯光、体素化和最终渲染均为
Chromoxel 项目演示制作。

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

