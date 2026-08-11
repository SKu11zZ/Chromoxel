"""Chinese interface translations for Chromoxel."""

from __future__ import annotations

import bpy


ZH = {
    "Chromoxel": "Chromoxel 色彩体素",
    "Sources": "源对象",
    "Source Scope": "源范围",
    "Active": "活动对象",
    "Selected": "已选对象",
    "Collection": "集合",
    "Include Hidden": "包含隐藏对象",
    "Voxel Grid": "体素网格",
    "Quality": "质量",
    "Coarse": "粗糙",
    "Medium": "中等",
    "Fine": "精细",
    "Voxel Size": "体素尺寸",
    "Detail Mode": "细节模式",
    "Adaptive": "自适应",
    "Uniform": "统一",
    "Max Detail Level": "最大细节等级",
    "Cube Gap": "体素间隙",
    "Grid Origin": "网格原点",
    "Custom Origin": "自定义原点",
    "Estimate Work": "估算工作量",
    "Surface Input": "表面输入",
    "Check Surface": "检查表面",
    "Surface not checked": "尚未检查表面",
    "Active source is watertight": "活动源模型已闭合",
    "Private repair copy will be used": "将使用私有修复副本",
    "Non-manifold source is blocked": "非流形源模型已被阻止",
    "Surface check failed": "表面检查失败",
    "Auto Watertight Copy": "自动闭合副本",
    "Repair Voxel Size": "修复体素尺寸",
    "Colour": "颜色采样",
    "Auto Material Images": "自动查找材质贴图",
    "UV Map": "UV 映射",
    "Image Override": "覆盖贴图",
    "Texture Filter": "纹理过滤",
    "Fallback Color": "备用颜色",
    "Advanced": "高级设置",
    "Texture Error": "纹理误差",
    "Geometry Angle": "几何角度",
    "Geometry Detail Level": "几何细节等级",
    "Sparse Surface Candidates": "稀疏表面候选",
    "Sparse Grid Threshold": "稀疏网格阈值",
    "Candidate Limit": "候选上限",
    "Expansion Limit": "展开上限",
    "Voxel Limit": "体素上限",
    "Task Chunk": "任务分块",
    "Cache Memory": "缓存内存",
    "Compute Backend": "计算后端",
    "GPU Batch Size": "GPU 批次大小",
    "GPU Memory Limit (MiB)": "GPU 显存上限 (MiB)",
    "GPU": "GPU",
    "CPU": "CPU",
    "Clear Sampling Cache": "清除采样缓存",
    "Cancel Chromoxel Task": "取消 Chromoxel 任务",
    "Add / Update Chromoxel": "创建 / 更新 Chromoxel",
    "Bake to Mesh": "烘焙为网格",
    "Clear Outputs": "清除输出",
    "Active-source Live Preview": "活动源实时预览",
    "Live Update": "实时更新",
    "Debounce": "防抖延迟",
    "Start / Stop Live": "启动 / 停止实时预览",
    "Start Live": "启动实时预览",
    "Stop Live": "停止实时预览",
    "UI Language": "界面语言",
    "Auto": "自动",
    "English": "英文",
    "Edit Color Mode": "编辑颜色模式",
    "Direct Color": "直接颜色",
    "Palette": "调色板",
    "Edit Color": "编辑颜色",
    "Material ID": "材质 ID",
    "Roughness": "粗糙度",
    "Metallic": "金属度",
    "Emission": "自发光",
    "Palette Slot": "调色板槽",
    "Bake Output": "烘焙输出",
    "Remove Enclosed Voxels": "移除封闭内部体素",
    (
        "Delete voxels whose six axis-aligned sides are completely covered; "
        "exterior silhouettes, thin parts, holes, colours, and UV data are preserved"
    ): (
        "删除六个轴向侧面均被完全覆盖的体素；保留外轮廓、薄片、孔洞、颜色与 UV 数据"
    ),
    "Editable Points": "可编辑点",
    "Realized Cubes": "实体立方体",
    "Surface Mesh": "表面网格",
    "Greedy Mesh": "贪心合并网格",
    "VOX Unit Size": ".vox 单位尺寸",
    "Enter Voxel Edit": "进入体素编辑",
    "Exit Voxel Edit": "退出体素编辑",
    "Re-voxelize + Replay Edits": "重新体素化并重放编辑",
    "Voxel Selection": "体素选择",
    "Box Select Voxels": "框选体素",
    "Delete Selected Voxels": "删除已选体素",
    "Add Voxel at Cursor": "在游标处添加体素",
    "Move Selected Voxels": "移动已选体素",
    "Paint Selected Voxels": "为已选体素上色",
    "Pick Selected Voxel": "吸取已选体素",
    "Select Similar Voxels": "选择相似体素",
    "Flood Fill Color Region": "洪水填充颜色区域",
    "Mirror Selected Voxels": "镜像已选体素",
    "Copy Voxels": "复制体素",
    "Paste Voxels at Cursor": "在游标处粘贴体素",
    "Add Palette Slot": "添加调色板槽",
    "Remove Palette Slot": "移除调色板槽",
    "Update Linked Voxels": "更新关联体素",
    "Generate Palette from Voxels": "从体素生成调色板",
    "Import MagicaVoxel (.vox)": "导入 MagicaVoxel (.vox)",
    "Export MagicaVoxel (.vox)": "导出 MagicaVoxel (.vox)",
}

TRANSLATIONS = {
    locale: {("*", english): chinese for english, chinese in ZH.items()}
    for locale in ("zh_CN", "zh_HANS")
}


def register():
    try:
        bpy.app.translations.register(__name__, TRANSLATIONS)
    except ValueError:
        bpy.app.translations.unregister(__name__)
        bpy.app.translations.register(__name__, TRANSLATIONS)


def unregister():
    try:
        bpy.app.translations.unregister(__name__)
    except (RuntimeError, ValueError):
        pass
