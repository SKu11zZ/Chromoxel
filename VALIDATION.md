# Validation Record / 验证记录

## Blender 5.1.2 — PASS

Date / 日期：2026-08-06

### Chromoxel 0.6 adaptive validation

- Factory-startup background import, `register()`, and `unregister()` passed.
- A generated 128×128 red/white bullseye was discovered automatically from a
  Principled Base Color material without selecting an image or UV manually.
- At a base size of `0.5 BU`, Uniform produced 75 cells and Adaptive produced
  296 cells over levels `1` and `2`; the minimum cell size was `0.125 BU`.
- The adaptive AABB-overlap guard rejected 9 canonical circumsphere-only seed
  candidates (50 cells after symmetry expansion), preventing a thin textured
  surface from being hidden by a coarse outer layer.
- Red ring samples survived away from the horizontal and vertical axes, proving
  that the circle did not collapse into an axis-aligned cross.
- Adaptive cell sizes remained exactly closed over every proven X/Y/Z symmetry
  orbit.
- A 1,000-voxel cap stopped an L4 pass at 992 cells and reported
  `budget_limited`.
- Preview carried POINT-domain `voxel_color`, `voxel_size`, and `voxel_level`
  data and used one non-realized Geometry Nodes instancer.
- Bake produced realized cubes with CORNER colour and FACE size/level data.
- Preview-to-Bake adaptive cache reuse passed.

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
- 基础尺寸 `0.5 BU` 下，Uniform 输出 75 个体素；Adaptive 输出 296 个体素，覆盖 `1/2`
  两个层级，最小尺寸为 `0.125 BU`。
- 自适应 AABB 重叠保护过滤了 9 个仅与外接球相交的规范种子候选（对称展开后为 50 个体素），
  避免薄纹理表面被外层粗体素遮挡。
- 圆环在横纵轴之外仍保留红色采样，未退化成十字。
- 自适应体素在所有已证明的 X/Y/Z 对称轴上保持精确闭包。
- L4 测试在 1,000 体素预算下停止于 992，并正确报告预算受限。
- Preview 的点载体包含 `voxel_color`、`voxel_size`、`voxel_level`，且只使用一个未实体化的
  Geometry Nodes 实例器。
- Bake 输出实际立方体，并写入角域颜色和面域尺寸/层级属性。
- 旧版 Uniform 工作流、Suzanne 修复、NGON、批处理、缓存、取消、对称性和源对象不可变性回归通过。
- 36,292 体素性能测试中，稀疏与完整网格占用完全一致，候选数量减少 79.13%。

The repository contains rendered comparison images produced for Chromoxel. It
does not include KayKit source assets, private project files, local logs, or
absolute machine paths.

仓库只包含用于展示 Chromoxel 的渲染对比图，不包含 KayKit 源资产、私人项目文件、本地日志或
绝对机器路径。
