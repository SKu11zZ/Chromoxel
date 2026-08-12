"""Chromoxel 0.9.2 target-count UI and separated-part repair regression."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib.util
import math
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import cli, core, editable, preview  # noqa: E402

WORKFLOW_PATH = ROOT / "tests" / "blender_v090_workflow_ui.py"
SPEC = importlib.util.spec_from_file_location("chromoxel_workflow", WORKFLOW_PATH)
WORKFLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW)
RecordingLayout = WORKFLOW.RecordingLayout


def add_open_cube(name: str, location):
    mesh = bpy.data.meshes.new(name + "_Mesh")
    x, y, z = location
    vertices = [
        (x - 0.5, y - 0.5, z - 0.5), (x + 0.5, y - 0.5, z - 0.5),
        (x + 0.5, y + 0.5, z - 0.5), (x - 0.5, y + 0.5, z - 0.5),
        (x - 0.5, y - 0.5, z + 0.5), (x + 0.5, y - 0.5, z + 0.5),
        (x + 0.5, y + 0.5, z + 0.5), (x - 0.5, y + 0.5, z + 0.5),
    ]
    # Deliberately omit the two opposing X faces. Two close components would
    # be bridged by a coarse whole-object Voxel Remesh.
    faces = ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (3, 2, 6, 7))
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def add_open_parts(count: int = 9):
    parts = []
    for index in range(count):
        x = -0.58 if index % 2 == 0 else 0.58
        y = ((index // 2) - 2) * 1.15
        parts.append(add_open_cube(f"Part{index:02d}", (x, y, 0.0)))
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    return bpy.context.active_object


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    try:
        settings = bpy.context.scene.voxelizer_settings
        assert tuple(voxelizer.bl_info["version"]) == (0, 9, 2)

        # A small number of disconnected islands is repaired one island at a
        # time, retaining the authored gap while preserving legacy monkey-like
        # automatic closure behavior.
        first = add_open_cube("NearPartA", (-0.58, 0.0, 0.0))
        second = add_open_cube("NearPartB", (0.58, 0.0, 0.0))
        first.select_set(True)
        second.select_set(True)
        bpy.context.view_layer.objects.active = first
        bpy.ops.object.join()
        small_source = bpy.context.active_object
        small_readiness = core.mesh_readiness_diagnostics(small_source.data)
        small_symmetry = core.reflection_symmetry_diagnostics(small_source.data)
        small_helper, rebuilt = core.ensure_sampling_object(
            bpy.context,
            small_source,
            settings,
            source_mesh=small_source.data,
            source_diagnostics=small_readiness,
            source_symmetry=small_symmetry,
            component_count=2,
        )
        assert small_helper is not small_source
        assert rebuilt is True
        assert small_helper[core.REPAIR_STRATEGY_TAG] == "COMPONENTWISE"
        helper_diagnostics = core.mesh_diagnostics(small_helper.data)
        assert helper_diagnostics["components"] == 2
        assert helper_diagnostics["nonmanifold_edges"] == 0

        settings.voxel_size = 0.12
        settings.cube_gap = 0.006
        small_sample = core.sample_surface_voxels(
            bpy.context,
            small_source,
            settings,
            use_cache=False,
        )
        small_centres = small_sample.centres if hasattr(small_sample, "centres") else small_sample[0]
        centre_band = [
            value for value in small_centres
            if abs(float(value.x)) < 0.04
            and abs(float(value.y)) < 0.35
            and abs(float(value.z)) < 0.35
        ]
        assert not centre_band, len(centre_band)

        # Large multi-part art sources take the direct-shell guard, matching
        # the 159-component balloon-character production fixture.
        core.clear_sampling_cache()
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        source = add_open_parts()
        assert core.mesh_component_count(source.data, stop_after=100) == 9
        readiness = core.mesh_readiness_diagnostics(source.data)
        assert not core.diagnostics_ready(readiness)

        settings.auto_watertight_copy = True
        settings.preserve_disconnected_parts = True
        settings.repair_voxel_size = 0.25
        symmetry = core.reflection_symmetry_diagnostics(source.data)
        sampling_object, rebuilt = core.ensure_sampling_object(
            bpy.context,
            source,
            settings,
            source_mesh=source.data,
            source_diagnostics=readiness,
            source_symmetry=symmetry,
            component_count=9,
        )
        assert sampling_object is source
        assert rebuilt is False

        settings.resolution_mode = "COUNT"
        assert settings.sampling_mode == "UNIFORM"
        # Count fitting itself is verified on a smooth closed source so the
        # 5% contract is not made impossible by a synthetic four-face lattice.
        core.clear_sampling_cache()
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0)
        count_source = bpy.context.active_object
        count_source.name = "CountSphere"
        settings.target_voxel_count = 1_000
        settings.target_voxel_tolerance = 0.05
        events = []
        panel = SimpleNamespace(layout=RecordingLayout(events))
        voxelizer.VOXELIZER_PT_panel.draw(panel, bpy.context)
        props = {event[1] for event in events if event[0] == "prop"}
        labels = {event[1] for event in events if event[0] == "label"}
        assert "target_voxel_count" in props
        assert "target_voxel_tolerance" in props
        assert "Uniform only; accepted result never exceeds target." in labels

        sample, fitted_size, attempts = core._consume_progress_generator(
            cli.fit_target_voxels_iter(
                bpy.context,
                count_source,
                settings,
                1_000,
                tolerance=0.05,
                max_iterations=10,
            )
        )
        assert 950 <= sample.count <= 1_000
        assert fitted_size > 0.0
        assert attempts[-1]["final_voxels"] == sample.count
        assert math.isclose(settings.voxel_size, fitted_size, rel_tol=1.0e-6)

        # The same fitted path must drive the visible Preview action, not just
        # the lower-level solver used by the CLI.
        preview_result = bpy.ops.voxelizer.preview()
        assert preview_result == {"FINISHED"}
        preview_output = bpy.data.objects[core.preview_name(count_source)]
        assert editable.is_editable(preview_output)
        assert 950 <= len(preview_output.data.vertices) <= 1_000
        assert preview_output["chromoxel_target_voxels"] == 1_000
        assert settings.target_last_count == len(preview_output.data.vertices)

        # All four user-facing output choices consume the already fitted
        # sample, including Editable Points with its Geometry Nodes modifier.
        for mode in ("EDITABLE", "REALIZED", "SURFACE", "GREEDY"):
            settings.bake_mode = mode
            mesh, count, _used_image = core._consume_progress_generator(
                core.build_voxel_mesh_from_sample_iter(
                    count_source,
                    settings,
                    f"Count_{mode}_Mesh",
                    sample,
                )
            )
            assert count > 0
            if mode == "EDITABLE":
                carrier = bpy.data.objects.new("Count_EDITABLE", mesh)
                bpy.context.collection.objects.link(carrier)
                preview.ensure_modifier(
                    carrier,
                    core.ensure_colour_material(),
                    preview.display_cube_fill(settings),
                )
                editable.initialize_carrier(
                    carrier,
                    reset_delta=True,
                    coordinate_ordered=True,
                )
                assert editable.is_editable(carrier)
                bpy.data.objects.remove(carrier, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            else:
                assert len(mesh.polygons) > 0
                bpy.data.meshes.remove(mesh)

        # Exercise the actual direct-Bake operator branch as well as its
        # lower-level geometry builders.
        settings.bake_mode = "EDITABLE"
        bake_result = bpy.ops.voxelizer.bake()
        assert bake_result == {"FINISHED"}
        baked_output = bpy.data.objects[core.bake_name(count_source)]
        assert editable.is_editable(baked_output)
        assert baked_output.modifiers.get(preview.MODIFIER_NAME) is not None
        assert baked_output["chromoxel_target_voxels"] == 1_000
        baked_mesh = baked_output.data
        bpy.data.objects.remove(baked_output, do_unlink=True)
        if baked_mesh.users == 0:
            bpy.data.meshes.remove(baked_mesh)
        for name in (
            "resolution_mode", "target_voxel_count", "target_voxel_tolerance",
            "preserve_disconnected_parts",
        ):
            description = voxelizer.VOXELIZER_PG_settings.bl_rna.properties[name].description
            assert len(description.strip()) >= 24, name
        print(
            "PASS chromoxel_blender_0.9.2_count_parts",
            {"voxels": sample.count, "size": fitted_size, "attempts": len(attempts)},
        )
    finally:
        voxelizer.unregister()


if __name__ == "__main__":
    main()
