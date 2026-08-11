"""Headless operator regression for the Chromoxel 0.7 voxel editor."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer
from voxelizer import core, editable, preview


def select_ids(obj, voxel_ids):
    wanted = set(voxel_ids)
    for vertex, item in zip(obj.data.vertices, editable.records_from_object(obj)):
        vertex.select = item.voxel_id in wanted
    obj.data.update()


def make_editor_carrier():
    coordinates = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (10, 0, 0)]
    colors = [(0.2, 0.2, 0.2, 1.0)] * 3 + [(0.0, 0.1, 0.8, 1.0)]
    mesh = bpy.data.meshes.new("V070_Editor_Carrier")
    obj = bpy.data.objects.new("V070_Editor", mesh)
    bpy.context.collection.objects.link(obj)
    preview.configure_preview(
        obj,
        coordinates,
        colors,
        [1.0] * 4,
        [(1.0, 1.0, 1.0)] * 4,
        [0] * 4,
        0.95,
        core.ensure_colour_material(),
    )
    obj[editable.GRID_SIZE_TAG] = 1.0
    obj[editable.GRID_ORIGIN_TAG] = (0.0, 0.0, 0.0)
    editable.initialize_carrier(obj, reset_delta=True)
    obj[core.TOOL_TAG] = core.TOOL_ID
    obj[core.KIND_TAG] = core.PREVIEW_KIND
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    obj = make_editor_carrier()
    settings = bpy.context.scene.voxelizer_settings

    assert bpy.ops.voxelizer.enter_voxel_edit() == {"FINISHED"}
    assert obj.mode == "EDIT"
    assert bpy.ops.voxelizer.exit_voxel_edit() == {"FINISHED"}
    assert obj.mode == "OBJECT"

    assert bpy.ops.voxelizer.voxel_select(action="ALL") == {"FINISHED"}
    assert len(editable.selected_indices(obj)) == 4
    assert bpy.ops.voxelizer.voxel_select(action="NONE") == {"FINISHED"}
    assert len(editable.selected_indices(obj)) == 0
    assert bpy.ops.voxelizer.voxel_select(action="INVERT") == {"FINISHED"}
    assert len(editable.selected_indices(obj)) == 4

    records = editable.records_from_object(obj)
    select_ids(obj, (records[0].voxel_id,))
    settings.edit_color = (0.9, 0.1, 0.05, 1.0)
    settings.edit_material_id = 7
    settings.edit_roughness = 0.25
    settings.edit_metallic = 0.75
    settings.edit_emission = 2.0
    assert bpy.ops.voxelizer.flood_fill_voxels() == {"FINISHED"}
    painted = editable.records_from_object(obj)
    assert sum(item.color[0] > 0.8 for item in painted) == 3
    assert sum(item.material_id == 7 for item in painted) == 3

    # Eyedropper and similarity selection use persisted point attributes.
    settings.edit_color = (0.0, 0.0, 0.0, 1.0)
    seed = next(item for item in painted if item.coord == (1, 0, 0))
    select_ids(obj, (seed.voxel_id,))
    assert bpy.ops.voxelizer.pick_selected_voxel() == {"FINISHED"}
    assert settings.edit_color[0] > 0.8 and settings.edit_material_id == 7
    assert bpy.ops.voxelizer.select_similar_voxels(mode="MATERIAL") == {"FINISHED"}
    assert len(editable.selected_indices(obj)) == 3

    # Palette generation, linked slot update, and direct-to-palette conversion.
    assert bpy.ops.voxelizer.palette_generate() == {"FINISHED"}
    assert 1 <= len(settings.palette_slots) <= 2
    first = editable.records_from_object(obj)[0]
    select_ids(obj, (first.voxel_id,))
    settings.palette_active_index = first.palette_index - 1
    slot = settings.palette_slots[settings.palette_active_index]
    slot.color = (0.05, 0.8, 0.2, 1.0)
    slot.roughness = 0.6
    assert bpy.ops.voxelizer.palette_update_linked() == {"FINISHED"}
    linked = [item for item in editable.records_from_object(obj) if item.palette_index == first.palette_index]
    assert linked and all(item.color[1] > 0.7 for item in linked)
    old_slots = len(settings.palette_slots)
    assert bpy.ops.voxelizer.palette_add() == {"FINISHED"}
    assert len(settings.palette_slots) == old_slots + 1
    assert bpy.ops.voxelizer.palette_remove() == {"FINISHED"}
    assert len(settings.palette_slots) == old_slots

    # Mirror, clipboard paste, cursor add, integer move, and delete.
    source = next(item for item in editable.records_from_object(obj) if item.coord == (2, 0, 0))
    select_ids(obj, (source.voxel_id,))
    assert bpy.ops.voxelizer.mirror_selected_voxels(axis="X") == {"FINISHED"}
    assert (-2, 0, 0) in {item.coord for item in editable.records_from_object(obj)}
    assert bpy.ops.voxelizer.copy_voxels() == {"FINISHED"}
    bpy.context.scene.cursor.location = (20.0, 0.0, 0.0)
    assert bpy.ops.voxelizer.paste_voxels() == {"FINISHED"}
    assert (20, 0, 0) in {item.coord for item in editable.records_from_object(obj)}
    bpy.context.scene.cursor.location = (30.0, 0.0, 0.0)
    assert bpy.ops.voxelizer.add_voxel_at_cursor() == {"FINISHED"}
    assert (30, 0, 0) in {item.coord for item in editable.records_from_object(obj)}
    assert bpy.ops.voxelizer.move_selected_voxels(delta=(0, 1, 0)) == {"FINISHED"}
    assert (30, 1, 0) in {item.coord for item in editable.records_from_object(obj)}
    before_delete = len(editable.records_from_object(obj))
    assert bpy.ops.voxelizer.delete_selected_voxels() == {"FINISHED"}
    assert len(editable.records_from_object(obj)) == before_delete - 1

    diagnostics = editable.validate_editable(obj)
    assert diagnostics["duplicate_coordinates"] == 0
    assert diagnostics["duplicate_ids"] == 0
    assert len(editable.load_delta(obj)) >= 10
    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "remaining_voxels": diagnostics["voxels"],
        "edit_operations": len(editable.load_delta(obj)),
        "palette_slots": len(settings.palette_slots),
    }
    output_dir = ROOT / "build_validation" / "v070_editor_tools"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS chromoxel_blender_0.7.0_editor_tools", json.dumps(report, sort_keys=True))
    voxelizer.unregister()


main()
