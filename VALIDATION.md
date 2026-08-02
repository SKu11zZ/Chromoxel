# Validation Record / 验证记录

Version / 版本：0.3.0

Date / 日期：2026-08-02

Target / 目标：Unreal Engine 5.8.1, Win64 Editor

## English

### Source-only isolated build — PASS

- Copied only the staged plug-in descriptor, configuration, and source into a
  clean HostProject.
- UnrealHeaderTool reflection generation and UnrealBuildTool compilation both
  succeeded with `-NoUBA -MaxParallelActions=1`.
- The final incremental validation completed all 9 compile/link/metadata
  actions successfully.
- Runtime module: `UnrealEditor-VoxelMapMVP.dll` (164,864 bytes).
- Editor module: `UnrealEditor-VoxelMapMVPEditor.dll` (439,808 bytes).

### PortfolioRTGEngine integration build — PASS

- The complete `PortfolioRTGEngineEditor` target built successfully after the
  v0.3.0 plug-in was installed.
- Clean integration build: 31/31 actions, exit code 0.
- Final incremental build: 9/9 actions, exit code 0.
- The integration build produced the same module sizes as the isolated build.

### Default-map commandlet and incremental bake — PASS

Test map: `/Game/FirstPerson/Lvl_FirstPerson`

Preset and scope: Coarse, World, 50 cm

- 13,859 occupied voxels in 672 deterministic 4 x 4 x 4 blocks.
- 53 source actors/components, 18,508 triangle instances, and 113,911
  triangle/AABB candidate tests.
- Six-view Deferred BaseColor capture completed with 9,667 captured voxels,
  4,192 explicit fallback voxels, and 69.7525% coverage.
- Repeated bake: 672 reused blocks, 0 changed blocks, 0 removed blocks.
- Preview update: 36 reused HISM chunks, 0 rebuilt chunks, 0 removed chunks.
- Stable geometry SHA1:
  `B90D7036259C2C268C01DC0AF0B98A2EB1EC93FE`.
- Stable color SHA1:
  `93311B3E1F7F483DE98535C1EC43360D63254135`.
- Final core bake time: 3.002 seconds; commandlet execution: 4.72 seconds.
- Commandlet result: 0 errors, 0 warnings, exit code 0.

### Bounds-scope first bake — PASS

- Unquoted `-BoundsMin=-500,-500,-50` and
  `-BoundsMax=500,500,350` were parsed without separator truncation.
- 17 components were included and 36 out-of-scope components were filtered.
- The bounded result contains 1,551 voxels in 66 blocks and 4 preview chunks.
- A new Data Asset and output map were created with 0 errors and 0 warnings.

The source map was not saved or modified. Validation outputs used dedicated
`v030_Smoke` asset names. Generated HostProject files, binaries, local reports,
and absolute machine paths are intentionally excluded from the repository and
source ZIP.

## 简体中文

### 纯源码隔离编译 — 通过

- 仅将待发布插件的描述文件、配置和源码复制到干净的 HostProject。
- UnrealHeaderTool 反射生成和 UnrealBuildTool 编译均成功，参数为
  `-NoUBA -MaxParallelActions=1`。
- 最终增量验证的 9 个编译、链接及元数据步骤全部成功。
- Runtime 模块：`UnrealEditor-VoxelMapMVP.dll`（164,864 字节）。
- Editor 模块：`UnrealEditor-VoxelMapMVPEditor.dll`（439,808 字节）。

### PortfolioRTGEngine 工程集成编译 — 通过

- 安装 v0.3.0 插件后，完整 `PortfolioRTGEngineEditor` Target 编译成功。
- 完整集成编译：31/31 步，退出码 0。
- 最终增量编译：9/9 步，退出码 0。
- 工程集成编译与隔离编译生成的两个插件模块尺寸一致。

### 默认地图 Commandlet 与增量 Bake — 通过

测试地图：`/Game/FirstPerson/Lvl_FirstPerson`

预设与范围：Coarse、World、50 cm

- 生成 13,859 个占用体素，存储于 672 个确定性 4 x 4 x 4 Block 中。
- 输入为 53 个 Actor/组件、18,508 个三角形实例，共执行 113,911 次
  三角形/AABB 候选检测。
- 六视角 Deferred BaseColor 捕获成功：9,667 个捕获颜色体素、4,192 个
  显式回退体素，覆盖率 69.7525%。
- 重复 Bake：复用 672 个 Block，变化 0 个，移除 0 个。
- 预览更新：复用 36 个 HISM Chunk，重建 0 个，移除 0 个。
- 几何 SHA1 稳定：`B90D7036259C2C268C01DC0AF0B98A2EB1EC93FE`。
- 颜色 SHA1 稳定：`93311B3E1F7F483DE98535C1EC43360D63254135`。
- 最终核心 Bake 用时 3.002 秒；Commandlet 执行用时 4.72 秒。
- Commandlet 结果：0 错误、0 警告、退出码 0。

### Bounds 范围首次 Bake — 通过

- 未加引号的 `-BoundsMin=-500,-500,-50` 与
  `-BoundsMax=500,500,350` 可被完整解析，不会在逗号处截断。
- 纳入 17 个组件，并过滤 36 个范围外组件。
- 范围结果包含 1,551 个体素、66 个 Block 和 4 个预览 Chunk。
- 首次创建新的 Data Asset 与输出地图时为 0 错误、0 警告。

源地图未被保存或修改；验证资源使用独立的 `v030_Smoke` 名称。生成的
HostProject 文件、二进制、机器本地报告和绝对路径均不会进入仓库或源码 ZIP。
