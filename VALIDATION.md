# Validation Record / 验证记录

## Chromoxel 0.9.2 — Blender 5.1.2 PASS

Date / 日期：2026-08-12

### Target count and separate-part preservation / 目标数量与分离部件保护

- A two-component open source was repaired per component and retained its
  deliberately empty centre gap. The legacy stock-Suzanne repair and symmetry
  regression also remained green. A closed source requested 1,000 Uniform
  voxels and produced an accepted result inside the selected -5% to target
  interval after bounded occupancy trials.
- The fitted sample passed through editable Preview and all four Bake choices:
  Editable Points, Realized Cubes, Surface Mesh, and Greedy Mesh.
- The supplied 1,377,362-face balloon character was evaluated through the
  formal 0.9.2 path with 159 source components. The separate-part guard used
  the original shell (no repair helper, `separate_parts_guard_used=true`) and
  fitted 19,740 voxels at
  0.03880999 BU. The previous whole-object repair path failed to produce a
  single closed manifold and was the source of inconsistent demo/UI behavior.
- 双部件开放模型按部件分别修复，刻意留出的中央间隙没有生成桥接体素；旧版默认猴头修复与
  对称性回归仍通过。封闭测试源请求 1,000 个统一体素，经有限次试算得到目标值以下 5%
  容差内的结果。
- 同一拟合结果已通过可编辑 Preview，以及可编辑点、实体立方体、表面网格和贪心网格四类 Bake。
- 对 1,377,362 面、159 个连通部件的气球角色，0.9.2 正式路径启用了分离部件保护，直接采样
  原始表面壳且未使用整体修复副本；20K 档得到 19,740 个体素，尺寸为 0.03880999 BU。

## Chromoxel 0.9.1 — Blender 5.1.2 PASS

Date / 日期：2026-08-12

### N-panel entry point and hover help / N 面板入口与悬浮说明

- Replaced the invalid Blender 5.1 `MOD_NODES` and `BORDER_RECT` icons with
  supported icons. A source-level regression now checks every literal panel
  icon against Blender 5.1 RNA, so one bad icon cannot silently truncate UI.
- Empty selection, original Mesh selection, English, Chinese, disabled action
  state, action order, enum-button tooltip, choice-specific operator tooltip,
  and property/operator description coverage pass without topology traversal.
- 修复 Blender 5.1 不支持的 `MOD_NODES` 与 `BORDER_RECT` 图标，并新增源码级回归：将面板中
  每一个图标与 Blender 5.1 RNA 对照，避免单个错误图标再次静默截断后续 UI。
- 空选择、原始 Mesh 选择、中英文、禁用状态、操作顺序、枚举按钮说明、选项专属操作说明以及
  属性/操作器说明均已通过回归，绘制期间不会遍历模型拓扑。

## Chromoxel 0.9.0 — Blender 5.1.2 PASS

Date / 日期：2026-08-12

### GPU occupancy, large meshes, and staged profiling

- Interactive Blender created the Uniform occupancy compute shader on the
  available GPU backend. Its conservative AABB prefilter was followed by exact
  CPU BVH confirmation for every positive candidate.
- Both supplied Tripo GLBs (1,488,721 and 1,471,620 source faces) matched CPU
  coordinates exactly at the tested ~2K, ~20K, and ~97K levels: zero missing
  and zero extra voxels in cold and warm GPU runs.
- Model 214730 measured 0.48/1.13/3.97 seconds cold GPU and
  0.16/1.03/3.75 seconds warm at 1,906/19,594/96,979 voxels.
- Model 220646 measured 2.27/1.72/6.25 seconds cold GPU and
  0.14/1.12/5.46 seconds warm at 2,027/19,651/96,953 voxels.
- Exact NumPy chunked-mask candidate generation reduced the first model's 97K
  candidate stage from about 1.28 seconds to 0.25 seconds and the second from
  about 8.20 seconds to 1.74 seconds.
- Source preparation remained a separate one-time cost of 6.44 and 10.44
  seconds. Preview/direct Bake now retain a two-entry Source Session LRU;
  explicit cache clearing closes snapshots and releases GPU resources.
- The passive N-panel, session/profile regression, legacy 0.5 sampling and
  cancellation contract, 0.7 editable output, 0.8 prepared sessions, 0.8.1
  CLI/panel behavior, and 0.8.2 enclosed-voxel filter passed.
- A second Tripo pair with 1,491,682 and 1,377,362 source faces produced
  1,975/19,654/99,152 and 1,965/19,374/98,215 input voxels. Together with the
  archived astronaut and tank, all four models were rebuilt as Realized Cubes,
  filtered for enclosed voxels, rendered at a common -45-degree Cycles/OptiX
  setup, and assembled into one four-row acceptance image.
- The numbered workflow UI regression verified that language, output type,
  Preview, and Bake precede Step 1 and that every visible workflow heading
  switches between English and Chinese without topology inspection.

### GPU 占据、大模型与阶段诊断

- 交互式 Blender 已真实创建并运行 Uniform GPU 占据计算着色器；GPU 使用保守 AABB 预筛，
  所有阳性候选再由 CPU BVH 精确确认。
- 两个 Tripo GLB 的源模型分别为 1,488,721 与 1,471,620 面；在约 2K、20K、97K 三档中，
  CPU、冷 GPU、热 GPU 的体素坐标均完全一致，没有缺失或额外体素。
- 214730 的冷 GPU 为 0.48/1.13/3.97 秒，热 GPU 为 0.16/1.03/3.75 秒；对应体素数为
  1,906/19,594/96,979。
- 220646 的冷 GPU 为 2.27/1.72/6.25 秒，热 GPU 为 0.14/1.12/5.46 秒；对应体素数为
  2,027/19,651/96,953。
- 精确 NumPy 分块位图把两个模型 97K 档的候选生成从约 1.28/8.20 秒降至 0.25/1.74 秒。
- 一次性源准备仍分别需要 6.44/10.44 秒；Preview 与直接 Bake 现会复用两条 Source Session，
  手动清缓存会关闭快照并释放 GPU 资源。
- 新增的两个 Tripo 模型分别有 1,491,682 与 1,377,362 个源面，三档输入体素为
  1,975/19,654/99,152 与 1,965/19,374/98,215。它们与旧宇航员、坦克统一采用 -45°
  Cycles/OptiX、Realized Cubes 和内部体素剔除，并合成为四行视觉验收图。
- 编号式 UI 回归确认语言、输出类型、预览和 Bake 位于第 1 步之前；所有可见流程标题均可在
  中英文之间完整切换，绘制面板时仍不会遍历模型拓扑。

## Chromoxel 0.8.2 — Blender 5.1.2 PASS

Date / 日期：2026-08-12

### Enclosed-voxel optimization

- A solid 3×3×3 Uniform block was reduced from 27 to 26 records. Realized
  output fell from 162 to 156 polygons; Surface remained 54 polygons and
  Greedy remained 6 polygons, proving that pruning does not open cavity faces.
- A mixed Adaptive fixture expanded to 64 exact minimum cells and removed only
  its one completely enclosed coarse record. Opening one side retained that
  record.
- A 100,000-cell solid fixture was filtered in 0.6574 seconds, retaining the
  12,448-cell exterior shell and removing 87,552 enclosed cells.
- Blender UI/operator, CLI parser and Surface CLI path, direct Uniform Bake,
  preserved record attributes, safe Adaptive limits, and default-off behavior
  all passed.
- All 0.5, 0.6, 0.7, 0.8, and 0.8.1 compatibility regressions passed. Blender's
  extension validator parsed the 0.8.2 Extension ZIP successfully.

### 封闭内部体素优化

- 3×3×3 Uniform 实心块从 27 个记录减少为 26 个；实体立方体从 162 面降至 156 面，
  Surface 仍为 54 面，Greedy 仍为 6 面，证明删除内部体素不会打开空腔面。
- 混合 Adaptive 用例精确展开为 64 个最小单元，仅删除 1 个完全封闭的粗体素；打开任意
  一侧后，该体素会被保留。
- 10 万体素实心用例耗时 0.6574 秒，保留 12,448 个外壳体素，删除 87,552 个内部体素。
- Blender 面板/操作器、CLI、直接 Uniform Bake、属性保留、安全上限和默认关闭行为均通过；
  0.5–0.8.1 全部兼容回归及 0.8.2 扩展包解析也已通过。

## Historical validation / 历史验证记录

## Blender 5.1.2 — PASS

Date / 日期：2026-08-11

### Chromoxel 0.8.1 dense-source and passive-panel validation

- On both 1.47-1.49-million-face Tripo sources, 100 panel draws completed
  without topology traversal. The measured draw cost was 0.037-0.042 ms.
- The first bounded Preview key on Tripo 220646 took 26.9 ms and repeated keys
  took 0.125 ms, versus 12.1 s for the previous full geometry/UV hash.
- SourceSession preparation measured 6.437 s (Tripo 214730), 6.375 s (Tripo
  220646), and 0.210 s (Mixamo CH14). All symmetry, adaptive, editable, Bake,
  VOX, 100K-carrier, cache, and CPU-fallback regressions passed.
- The Tripo 220646 2K CLI acceptance produced 1,934 voxels (3.3% below target)
  in 17.7 s end-to-end. All eight fit attempts and final colour sampling reused
  one source session; no out-of-tolerance fallback was saved.

### Chromoxel 0.8.1 高密度模型与轻量面板验证

- 两个 147-149 万面 Tripo 模型各执行 100 次面板 draw，均未遍历拓扑；单次耗时
  0.037-0.042 ms。
- Tripo 220646 首次有界 Preview key 为 26.9 ms，后续为 0.125 ms；旧版完整
  几何/UV 哈希约为 12.1 秒。
- SourceSession 分别为 Tripo 214730 6.437 秒、Tripo 220646 6.375 秒、Mixamo
  CH14 0.210 秒；对称、自适应、编辑、Bake、VOX、10 万点载体、缓存和 CPU 回退
  回归全部通过。
- Tripo 220646 的 2K CLI 验收端到端耗时 17.7 秒，输出 1,934 个体素（误差 3.3%）；
  8 次拟合与最终颜色采样共用一个 SourceSession，未保存任何超差回退结果。

### Chromoxel 0.8 GPU and performance validation

- Blender 5.1.2 created and dispatched the Chromoxel compute shader on the
  `OPENGL / NVIDIA` backend in a normal interactive graphics context.
- Nearest and bilinear GPU reads matched the CPU reference, including repeat
  addressing and scene-linear sRGB conversion.
- On the real CH14 4096×4096 Base Color image, 1,988 sampled voxel colours had
  a maximum CPU/GPU component error of `2.67e-7` and a mean maximum-component
  error of `1.11e-7`.
- Background/headless `Auto` resolved to CPU without changing output. A 512 MiB
  default VRAM ceiling bounds source textures plus UV/colour dispatch buffers;
  oversized work falls back to CPU.
- One reusable source session was used for each character's ~2K/~20K/~100K
  levels. Target-fitting retries sampled occupancy only and performed colour
  reconstruction once at the accepted size.
- Three-level GPU sampling completed in 6.73 s (CH14), 9.98 s (CH15), and
  7.65 s (CH46), versus 155.73-428.42 s on the archived repeated full-sampling
  path. Counts were 1,988/19,744/99,469; 1,955/19,377/98,358; and
  1,964/19,662/98,745 respectively.
- A 100,000-point editable carrier wrote all required attributes in 0.32 s.
  Editable operations, four Bake modes, adaptive sampling, `.vox` interchange,
  and GPU fallback regressions all passed.
- Blender's extension validator parsed the final 0.8.0 extension ZIP
  successfully, and Blender imported, registered, and unregistered the legacy
  ZIP directly without extraction.
- Three 2560×800 Cycles/OptiX visual comparisons were rebuilt from the official
  Realized Cubes Bake path. Colour, silhouettes, uniform cell size, and all
  2K/20K/100K labels passed visual review. The saved project retains editable
  POINT carriers; transient render meshes were removed after each frame.

### Chromoxel 0.8 GPU 与性能验证

- Blender 5.1.2 在普通交互式图形上下文中，通过 `OPENGL / NVIDIA` 后端实际创建并执行
  Chromoxel 计算着色器。
- GPU 最近点和双线性读取与 CPU 参考一致，包括重复寻址与 sRGB 到场景线性颜色转换。
- 在 CH14 的真实 4096×4096 Base Color 贴图上，1,988 个体素颜色的 CPU/GPU 最大分量误差
  为 `2.67e-7`，逐体素最大分量误差的平均值为 `1.11e-7`。
- 后台模式的 `Auto` 会无损回退 CPU；默认 512 MiB 显存上限约束源纹理与 UV/颜色临时缓冲，
  超限任务自动回退，不会强制申请显存。
- 每个角色的约 2K/20K/100K 三档共用一个 Source Session；目标拟合只测试占用，并只在最终
  接受尺寸执行一次颜色采样。
- GPU 三档总采样耗时为 CH14 6.73 秒、CH15 9.98 秒、CH46 7.65 秒；旧重复完整采样路径为
  155.73-428.42 秒。三组数量分别为 1,988/19,744/99,469、1,955/19,377/98,358、
  1,964/19,662/98,745。
- 10 万点载体的完整属性写入为 0.32 秒；编辑操作、四类 Bake、自适应采样、`.vox` 互换和
  GPU 回退测试全部通过。
- Blender 扩展验证器成功解析最终 0.8.0 Extension ZIP；Legacy ZIP 也通过了无需解压的直接
  导入、注册和注销测试。
- 三张 2560×800 Cycles/OptiX 验收图通过正式 Realized Cubes Bake 管线重建，颜色、轮廓、
  统一体素尺寸及三档标签均通过视觉检查。保存工程继续保留可编辑 POINT 载体，临时渲染网格
  在每帧结束后删除。

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
