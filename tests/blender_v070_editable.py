"""Chromoxel 0.7 editable-carrier, Bake, and VOX round-trip regression."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voxelizer import core, editable, meshing, preview, vox_io
import voxelizer


def select_only(obj):
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def add_test_texture(source):
    image = bpy.data.images.new("V070_UV_Probe", width=4, height=4, alpha=True)
    pixels = []
    for y in range(4):
        for x in range(4):
            pixels.extend((x / 3.0, y / 3.0, 0.25, 1.0))
    image.pixels = pixels
    image.update()
    material = bpy.data.materials.new("V070_UV_Material")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    uv_map = nodes.new("ShaderNodeUVMap")
    uv_map.uv_map = "UVMap"
    links.new(uv_map.outputs["UV"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], principled.inputs["Base Color"])
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    source.data.materials.append(material)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    source = bpy.context.object
    source.name = "V070_Source"
    add_test_texture(source)
    settings = bpy.context.scene.voxelizer_settings
    settings.sampling_mode = "UNIFORM"
    settings.voxel_size = 0.5
    settings.cube_gap = 0.025
    settings.auto_watertight_copy = False
    settings.grid_origin_mode = "OBJECT"
    settings.fallback_color = (0.1, 0.35, 0.8, 1.0)
    settings.auto_material_images = True

    update = preview.refresh_preview(bpy.context, source, settings, force_rebuild=True)
    output = update.output
    select_only(output)
    diagnostics = editable.validate_editable(output)
    assert diagnostics["editable"]
    assert diagnostics["voxels"] == update.point_count
    assert diagnostics["duplicate_coordinates"] == 0
    assert diagnostics["duplicate_ids"] == 0
    original_records = editable.records_from_object(output)
    original_count = len(original_records)
    assert update.used_image
    assert any(
        abs(record.source_uv[0]) > 1.0e-6 or abs(record.source_uv[1]) > 1.0e-6
        for record in original_records
    ), "sampled source_uv data was not written to the editable carrier"

    # Move one selected voxel by three cells so overwrite semantics do not
    # accidentally reduce this synthetic shell.
    for vertex in output.data.vertices:
        vertex.select = False
    output.data.vertices[0].select = True
    moved_id = original_records[0].voxel_id
    old_coord = original_records[0].coord
    result = bpy.ops.voxelizer.move_selected_voxels(delta=(3, 0, 0))
    assert result == {"FINISHED"}
    moved = next(record for record in editable.records_from_object(output) if record.voxel_id == moved_id)
    expected_coord = (old_coord[0] + 3, old_coord[1], old_coord[2])
    assert moved.coord == expected_coord

    settings.edit_color = (0.9, 0.05, 0.02, 1.0)
    result = bpy.ops.voxelizer.paint_selected_voxels()
    assert result == {"FINISHED"}
    painted = next(record for record in editable.records_from_object(output) if record.voxel_id == moved_id)
    assert painted.color[0] > 0.8
    assert len(editable.load_delta(output)) >= 3

    # A forced source rebuild must replay the move and paint by exact integer
    # coordinates.
    select_only(source)
    rebuilt = preview.refresh_preview(bpy.context, source, settings, force_rebuild=True)
    output = rebuilt.output
    replayed = [record for record in editable.records_from_object(output) if record.coord == expected_coord]
    assert replayed and replayed[0].color[0] > 0.8

    records = editable.records_from_object(output)
    atoms = meshing.atomic_records(
        records,
        float(output[editable.GRID_SIZE_TAG]),
        tuple(output[editable.GRID_ORIGIN_TAG]),
    )
    meshes = {}
    for mode in ("REALIZED", "SURFACE", "GREEDY"):
        mesh, count = meshing.build_from_editable(output, mode, f"V070_{mode}")
        meshes[mode] = mesh
        assert count == (len(records) if mode == "REALIZED" else len(atoms))
        assert mesh.color_attributes.get(core.COLOUR_ATTRIBUTE) is not None
        assert mesh.attributes.get(editable.VOXEL_ID_ATTRIBUTE) is not None
        assert mesh.attributes.get(editable.SOURCE_UV_ATTRIBUTE) is not None
    assert len(meshes["REALIZED"].polygons) == len(records) * 6
    assert len(meshes["SURFACE"].polygons) < len(atoms) * 6
    assert len(meshes["GREEDY"].polygons) <= len(meshes["SURFACE"].polygons)

    output_dir = ROOT / "build_validation" / "v070_editable"
    output_dir.mkdir(parents=True, exist_ok=True)
    vox_path = output_dir / "editable_roundtrip.vox"
    export_report = vox_io.export_vox(output, str(vox_path))
    parsed = vox_io.parse_vox(str(vox_path))
    assert sum(len(model["voxels"]) for model in parsed["models"]) == export_report["voxels"]
    imported, import_report = vox_io.import_vox(
        bpy.context,
        str(vox_path),
        float(output[editable.GRID_SIZE_TAG]),
    )
    imported_diagnostics = editable.validate_editable(imported)
    assert imported_diagnostics["voxels"] == export_report["voxels"]
    assert imported_diagnostics["duplicate_coordinates"] == 0

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "preview_voxels": original_count,
        "replayed_coordinate": expected_coord,
        "atomic_voxels": len(atoms),
        "surface_faces": len(meshes["SURFACE"].polygons),
        "greedy_faces": len(meshes["GREEDY"].polygons),
        "vox_models": export_report["models"],
        "vox_palette": export_report["palette_entries"],
        "imported_voxels": import_report["voxels"],
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS chromoxel_blender_0.7.0_editable", json.dumps(report, sort_keys=True))
    voxelizer.unregister()


main()
