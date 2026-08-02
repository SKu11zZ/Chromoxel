# Validation Record / 验证记录

## Blender 5.1.2 — PASS

Date / 日期：2026-08-02

### English

- Factory-startup background import, `register()`, and `unregister()` passed.
- Coarse/Medium/Fine preset sizing and Object-origin fixed-grid alignment passed.
- Active and Selected multi-object preview scopes passed.
- Lightweight preview contract passed: POINT carrier, POINT `FLOAT_COLOR`, one
  Geometry Nodes instancer, and no `Realize Instances` node.
- Realized Bake contract passed: 8 vertices and 6 faces per voxel with CORNER
  `FLOAT_COLOR` data.
- Preview-to-Bake cache reuse passed; the measured warm sampling call dropped
  from 0.583060 s to 0.014567 s in the included performance smoke.
- Sparse and full-grid occupancy were exactly equal on a 36,292-voxel
  asymmetric high-resolution sphere. Candidate tests fell from 531,441 to
  110,893 (79.13% reduction), and sparse sampling was faster in that run.
- Exact reflection-orbit closure passed for cube, UV sphere, and stock Suzanne.
- Stock Suzanne was correctly recognized as non-watertight, sampled through a
  private repair helper, and left unchanged.
- Concave NGON edge coverage, fixed-grid alignment, and source immutability
  passed.
- IEC 61966-2-1 sRGB decoding regression values passed.
- Deterministic legacy and extension ZIPs are recorded in
  `RELEASE_MANIFEST.json` and `SHA256SUMS.txt`.

### 简体中文

- Blender 工厂启动模式下的导入、`register()` 与 `unregister()` 已通过。
- 粗/中/细预设尺寸及对象原点固定网格对齐已通过。
- Active 与 Selected 多对象预览范围已通过。
- 轻量预览结构已通过：POINT 载体、POINT `FLOAT_COLOR`、单个 Geometry Nodes
  实例修改器，且不含 `Realize Instances`。
- 实体 Bake 结构已通过：每体素 8 顶点、6 面，并写入 CORNER `FLOAT_COLOR`。
- Preview 到 Bake 的缓存复用已通过；性能测试中热缓存调用由 0.583060 秒降至
  0.014567 秒。
- 在输出 36,292 个体素的非对称高分辨率球体上，稀疏与完整网格的占用结果完全一致；
  候选测试数从 531,441 降至 110,893（减少 79.13%），该次测试中稀疏路径更快。
- 立方体、UV 球和默认 Suzanne 的精确镜像轨道闭合已通过。
- 默认 Suzanne 被正确识别为非水密模型，经私有修复副本采样，源对象保持不变。
- 凹 NGON 的边缘覆盖、固定网格对齐与源对象不可变性已通过。
- IEC 61966-2-1 sRGB 解码回归值已通过。
- 确定性传统 ZIP 与扩展 ZIP 记录于 `RELEASE_MANIFEST.json` 和
  `SHA256SUMS.txt`。

The repository includes one rendered comparison image produced for Chromoxel.
No comparison `.blend` scene, KayKit assets, source textures, local logs, or
absolute machine paths are included.

仓库仅包含为 Chromoxel 制作的一张渲染对比图，不包含对比 `.blend` 场景、KayKit
资产、源贴图、本地日志或绝对机器路径。
