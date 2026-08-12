"""Chromoxel 0.9.1 real-layout and tooltip regression for Blender 5.1."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import editor, vox_io  # noqa: E402

WORKFLOW_TEST_PATH = ROOT / "tests" / "blender_v090_workflow_ui.py"
SPEC = importlib.util.spec_from_file_location("chromoxel_workflow_ui_test", WORKFLOW_TEST_PATH)
WORKFLOW_TEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW_TEST)
RecordingLayout = WORKFLOW_TEST.RecordingLayout


def draw(language: str):
    settings = bpy.context.scene.voxelizer_settings
    settings.ui_language = language
    settings.show_step_edit = False
    settings.show_step_live = False
    settings.show_advanced = False
    events = []
    panel = SimpleNamespace(layout=RecordingLayout(events))
    voxelizer.VOXELIZER_PT_panel.draw(panel, bpy.context)
    return events


def descriptions(classes):
    return {
        cls.__name__: str(getattr(cls, "bl_description", "") or "").strip()
        for cls in classes
    }


def icon_literals(path: Path):
    """Collect every constant UI icon, including both arms of conditionals."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    icons = set()

    def collect(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            icons.add(node.value)
        elif isinstance(node, ast.IfExp):
            collect(node.body)
            collect(node.orelse)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "icon":
                collect(keyword.value)
    return icons


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    try:
        settings = bpy.context.scene.voxelizer_settings
        assert tuple(voxelizer.bl_info["version"]) >= (0, 9, 1)

        # One invalid Blender icon aborts Panel.draw and hides every control
        # after it. Validate all literal icons against Blender 5.1's own RNA.
        valid_icons = bpy.types.UILayout.bl_rna.functions["operator"].parameters[
            "icon"
        ].enum_items
        used_icons = icon_literals(ROOT / "voxelizer" / "__init__.py")
        invalid_icons = sorted(icon for icon in used_icons if icon not in valid_icons)
        assert not invalid_icons, invalid_icons
        assert "MOD_NODES" not in used_icons

        # Empty selection must still draw both primary actions and an explicit
        # start instruction; it must not attempt source/topology inspection.
        empty_events = draw("EN")
        empty_ops = [event for event in empty_events if event[0] == "operator"]
        assert any(event[1] == voxelizer.VOXELIZER_OT_preview.bl_idname for event in empty_ops)
        assert any(event[1] == voxelizer.VOXELIZER_OT_bake.bl_idname for event in empty_ops)
        assert any(
            event[0] == "label" and event[1] == "First select an original Mesh object"
            for event in empty_events
        )
        assert any(event == ("enabled", False) for event in empty_events)

        bpy.ops.mesh.primitive_cube_add(size=2.0)
        english = draw("EN")
        chinese = draw("ZH")
        for events, preview_text, bake_text in (
            (english, "CREATE PREVIEW", "START BAKE"),
            (chinese, "创建预览", "开始烘焙"),
        ):
            visible = [event[2] for event in events if event[0] == "operator"]
            assert preview_text in visible
            assert bake_text in visible
            preview_event = next(
                event for event in events
                if event[0] == "operator"
                and event[1] == voxelizer.VOXELIZER_OT_preview.bl_idname
            )
            assert preview_event[3] == "GEOMETRY_NODES"

        enum_events = [
            event for event in english
            if event[0] == "operator"
            and event[1] == voxelizer.VOXELIZER_OT_set_enum.bl_idname
        ]
        assert enum_events
        for event in enum_events:
            assert len(str(getattr(event[4], "tooltip", "")).strip()) >= 20, event[2]

        # Buttons that share one operator still expose action-specific hover
        # text, rather than repeating an ambiguous generic description.
        dynamic_tooltips = (
            (voxelizer.VOXELIZER_OT_quality_preset, {"preset": "COARSE"}),
            (voxelizer.VOXELIZER_OT_quality_preset, {"preset": "FINE"}),
            (editor.VOXELIZER_OT_select, {"action": "INVERT"}),
            (editor.VOXELIZER_OT_move_selected, {"delta": (0, 0, 1)}),
            (editor.VOXELIZER_OT_select_similar, {"mode": "COLOR_CONNECTED"}),
            (editor.VOXELIZER_OT_mirror_selected, {"axis": "Y"}),
        )
        settings.ui_language = "EN"
        for operator_class, values in dynamic_tooltips:
            tooltip = operator_class.description(bpy.context, SimpleNamespace(**values))
            assert len(str(tooltip).strip()) >= 20, operator_class.__name__
        settings.ui_language = "ZH"
        for operator_class, values in dynamic_tooltips:
            tooltip = operator_class.description(bpy.context, SimpleNamespace(**values))
            assert len(str(tooltip).strip()) >= 8, operator_class.__name__

        assert settings.sampling_mode == "ADAPTIVE"
        result = bpy.ops.voxelizer.set_enum(
            property_name="sampling_mode",
            value="UNIFORM",
            tooltip="Use one voxel size across the whole source.",
        )
        assert result == {"FINISHED"}
        assert settings.sampling_mode == "UNIFORM"

        property_names = (
            "ui_language", "source_scope", "source_collection", "include_hidden",
            "grid_origin_mode", "grid_origin", "live_update", "live_debounce",
            "auto_watertight_copy", "preserve_disconnected_parts", "repair_voxel_size",
            "voxel_size", "resolution_mode", "target_voxel_count",
            "target_voxel_tolerance", "sampling_mode",
            "adaptive_max_level", "adaptive_texture_threshold", "adaptive_geometry_angle",
            "adaptive_geometry_max_level", "cube_gap", "uv_map", "base_color_image",
            "auto_material_images", "texture_filter", "compute_backend", "gpu_batch_size",
            "gpu_memory_limit_mb", "fallback_color", "color_mode", "edit_color",
            "edit_material_id", "edit_roughness", "edit_metallic", "edit_emission",
            "bake_mode", "remove_enclosed_voxels", "vox_import_size",
            "use_sparse_candidates", "sparse_grid_threshold", "sample_budget",
            "candidate_expansion_budget", "voxel_budget", "sampling_chunk_size",
            "cache_memory_mb", "show_step_source", "show_step_grid", "show_step_surface",
            "show_step_colour", "show_step_preview", "show_step_bake", "show_step_edit",
            "show_step_live", "show_advanced",
        )
        for name in property_names:
            prop = voxelizer.VOXELIZER_PG_settings.bl_rna.properties[name]
            assert len(str(prop.description).strip()) >= 24, name

        operator_classes = (
            voxelizer.VOXELIZER_OT_quality_preset,
            voxelizer.VOXELIZER_OT_estimate,
            voxelizer.VOXELIZER_OT_check_surface,
            voxelizer.VOXELIZER_OT_preview,
            voxelizer.VOXELIZER_OT_bake,
            voxelizer.VOXELIZER_OT_cancel_job,
            voxelizer.VOXELIZER_OT_clear_cache,
            voxelizer.VOXELIZER_OT_clear,
            voxelizer.VOXELIZER_OT_live_toggle,
            *editor.CLASSES[1:],
            vox_io.VOXELIZER_OT_import_vox,
            vox_io.VOXELIZER_OT_export_vox,
        )
        missing = [name for name, value in descriptions(operator_classes).items() if len(value) < 20]
        assert not missing, missing
        print("PASS chromoxel_blender_0.9.1_ui_hotfix")
    finally:
        voxelizer.unregister()


if __name__ == "__main__":
    main()
