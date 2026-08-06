# Validation Record / 验证记录

## Blender 5.1.2 — PASS

Date / 日期：2026-08-06

### Chromoxel 0.6 adaptive validation

- Factory-startup background import, `register()`, and `unregister()` passed.
- A generated 128×128 red/white bullseye was discovered automatically from a
  Principled Base Color material without selecting an image or UV manually.
- At a base size of `0.5 BU`, Uniform produced 75 cells and Adaptive produced
  148 cells over levels `1` and `2`; the minimum sampling size was `0.125 BU`.
  Grid-aligned refined cells retained the base `0.5 BU` normal extent.
- The adaptive AABB-overlap guard rejected 9 canonical circumsphere-only seed
  candidates (50 cells after symmetry expansion), preventing a thin textured
  surface from being hidden by a coarse outer layer.
- Red ring samples survived away from the horizontal and vertical axes, proving
  that the circle did not collapse into an axis-aligned cross.
- Adaptive cell sizes remained exactly closed over every proven X/Y/Z symmetry
  orbit.
- A 1,000-voxel cap stopped a finer-grid L4 request at 1,000 cells and reported
  `budget_limited`.
- Preview carried POINT-domain `voxel_color`, `voxel_size`, `voxel_extent`, and
  `voxel_level` data and used one non-realized Geometry Nodes instancer.
- Bake produced realized cells with CORNER colour and FACE
  size/extent/level data.
- A planar-surface regression proved that the outward face position is
  identical across refinement levels, while all three baked dimensions equal
  `voxel_extent × (1 - cube_gap / base_voxel_size)`.
- Preview-to-Bake adaptive cache reuse passed.

### KayKit training-range visual acceptance

- The same 27-part scene, orthographic camera, materials, lighting, and Cycles
  configuration were rendered in a four-panel comparison.
- The archived old Uniform 0.16 BU result, Chromoxel 0.6 Uniform 0.16 BU, and
  Chromoxel 0.6 Adaptive result were isolated from the original meshes before
  rendering; no smooth source shell remains over a voxel result.
- Uniform 0.16 BU produced 28,763 scene cells including repeated instances.
  Adaptive used a 0.16 BU base with a 0.04 BU minimum and selectively refined
  texture and geometric detail.
- Circular bullseyes and thin high-contrast markings remain visibly more
  continuous in the 0.04 BU adaptive panel.
- The final 1920×1080 Cycles/OptiX comparison passed visual review. Scene
  assets are KayKit: Prototype Bits 1.1 by Kay Lousberg, CC0 1.0.
- The caption compositor now clones the 72-DPI Blender pixels directly instead
  of drawing them through a 96-DPI canvas. A 16-pixel-grid audit reported zero
  changed pixels outside the four caption safe zones, preventing scale/crop
  regressions.
- The adaptive Bake regression verifies every realized axis against
  `voxel_extent × (1 - cube_gap / base_voxel_size)`; all 148 cells passed,
  proving both proportional display gaps and a flush planar envelope.

### Legacy and performance validation

- Uniform mode passed the complete 0.5 regression for cube, UV sphere, stock
  Suzanne repair, concave NGON, multi-object scope, fixed origin, source
  immutability, cancellation cleanup, exact symmetry closure, and cache reuse.
- Sparse and full-grid occupancy were identical on a 36,292-voxel asymmetric
  sphere.
- Candidate tests fell from 531,441 to 110,893, a 79.13% reduction.
- In the recorded three-run median, sparse sampling took 1.326 s versus 1.438 s
  for the full grid; a warm cache call took 0.027 s versus 1.336 s cold.
- Deterministic extension and legacy ZIPs are recorded in
  `RELEASE_MANIFEST.json` and `SHA256SUMS.txt`.

### 中文摘要

- Blender 5.1.2 工厂启动、导入、注册和注销通过。
- 程序生成的红白圆靶无需手动指定图片或 UV，即可从 Principled Base Color 材质中自动识别。
- 基础尺寸 `0.5 BU` 下，Uniform 输出 75 个体素；Adaptive 输出 148 个体素，覆盖 `1/2`
  两个层级，最小采样尺寸为 `0.125 BU`；轴对齐平面细分体素的法线厚度保持 `0.5 BU`。
- 自适应 AABB 重叠保护过滤了 9 个仅与外接球相交的规范种子候选（对称展开后为 50 个体素），
  避免薄纹理表面被外层粗体素遮挡。
- 圆环在横纵轴之外仍保留红色采样，未退化成十字。
- 自适应体素在所有已证明的 X/Y/Z 对称轴上保持精确闭包。
- 更细网格的 L4 请求在 1,000 体素预算处停止，并正确报告预算受限。
- Preview 的点载体包含 `voxel_color`、`voxel_size`、`voxel_extent`、`voxel_level`，且只使用一个未实体化的
  Geometry Nodes 实例器。
- Bake 输出实际体素，并写入角域颜色和面域采样尺寸/三轴尺寸/层级属性。
- 旧版 Uniform 工作流、Suzanne 修复、NGON、批处理、缓存、取消、对称性和源对象不可变性回归通过。
- 36,292 体素性能测试中，稀疏与完整网格占用完全一致，候选数量减少 79.13%。
- KayKit 靶场四格使用同一套 27 部件场景、相机、材质、光照和 Cycles 管线；统一
  0.16 BU 为 28,763 个场景体素；自适应以 0.16 BU 为基础、最小 0.04 BU，并只细分纹理与
  几何细节。右下圆形靶纸和细线纹理更连续，平整墙面和地板保持共面，且不存在原模型覆盖体素的问题。
- 标题合成改为直接克隆 Blender 的 72-DPI 原始像素，避免被 96-DPI 画布放大裁切；
  以 16 像素步长检查四个标题安全区之外的画面，差异像素为 0。
- 新增自适应体素间隙与平面共面回归，148 个体素的三个轴均满足
  “显示尺寸 = `voxel_extent` × 基础填充比例”，证明 0.08/0.04 BU 层级既不会继承错误的固定
  绝对间隙，也不会在平整表面产生深度台阶。

The repository contains rendered comparison images produced for Chromoxel. It
does not include KayKit source assets, private project files, local logs, or
absolute machine paths.

仓库只包含用于展示 Chromoxel 的渲染对比图，不包含 KayKit 源资产、私人项目文件、本地日志或
绝对机器路径。
