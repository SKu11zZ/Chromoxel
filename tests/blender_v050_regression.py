"""Blender 5.1 regression for Chromoxel v0.5 staged workflow and sampler."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import voxelizer  # noqa: E402
from voxelizer import core, preview  # noqa: E402


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def select_only(obj):
    for candidate in tuple(bpy.context.selected_objects):
        candidate.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def source_snapshot(obj):
    return {
        "mesh": obj.data.as_pointer(),
        "vertices": [tuple(vertex.co) for vertex in obj.data.vertices],
        "polygons": [tuple(polygon.vertices) for polygon in obj.data.polygons],
        "matrix": tuple(tuple(row) for row in obj.matrix_world),
    }


def require_unchanged(obj, snapshot):
    require(obj.data.as_pointer() == snapshot["mesh"], f"{obj.name}: mesh replaced")
    require(
        [tuple(vertex.co) for vertex in obj.data.vertices] == snapshot["vertices"],
        f"{obj.name}: vertices changed",
    )
    require(
        [tuple(polygon.vertices) for polygon in obj.data.polygons] == snapshot["polygons"],
        f"{obj.name}: topology changed",
    )
    require(
        tuple(tuple(row) for row in obj.matrix_world) == snapshot["matrix"],
        f"{obj.name}: transform changed",
    )


def create_concave_ngon_prism():
    outline = ((0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2))
    vertices = [(x, y, -0.5) for x, y in outline]
    vertices.extend((x, y, 0.5) for x, y in outline)
    faces = [tuple(reversed(range(6))), tuple(range(6, 12))]
    for index in range(6):
        following = (index + 1) % 6
        faces.append((index, following, following + 6, index + 6))
    mesh = bpy.data.meshes.new("V050_ConcaveNGON_Mesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    obj = bpy.data.objects.new("V050_ConcaveNGON", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def quantized(point, tolerance):
    return tuple(int(round(float(value) / tolerance)) for value in point)


def require_mirror_closure(centres, symmetry, tolerance):
    keys = {quantized(point, tolerance) for point in centres}
    for axis_name in symmetry["proven_axes"]:
        axis = "XYZ".index(axis_name)
        plane = float(symmetry["axes"][axis_name]["plane"])
        for centre in centres:
            mirrored = Vector(centre)
            mirrored[axis] = 2.0 * plane - mirrored[axis]
            require(
                quantized(mirrored, tolerance) in keys,
                f"missing {axis_name} partner for {tuple(centre)}",
            )


def require_preview_contract(source):
    output = bpy.data.objects.get(core.preview_name(source))
    require(output is not None, f"{source.name}: preview missing")
    require(len(output.data.vertices) > 0, f"{source.name}: empty carrier")
    require(len(output.data.edges) == 0, f"{source.name}: carrier has edges")
    require(len(output.data.polygons) == 0, f"{source.name}: carrier has faces")
    modifier = output.modifiers.get(preview.MODIFIER_NAME)
    require(modifier is not None and modifier.type == "NODES", "GN modifier missing")
    node_types = {node.bl_idname for node in modifier.node_group.nodes}
    require("GeometryNodeInstanceOnPoints" in node_types, "instancing node missing")
    require("GeometryNodeRealizeInstances" not in node_types, "preview was realized")
    colour = output.data.color_attributes.get(core.COLOUR_ATTRIBUTE)
    require(colour is not None and colour.domain == "POINT", "POINT colour missing")
    return output


def run():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    settings = bpy.context.scene.voxelizer_settings
    settings.source_scope = "ACTIVE"
    settings.grid_origin_mode = "OBJECT"
    settings.sampling_mode = "UNIFORM"
    settings.use_sparse_candidates = True
    settings.sparse_grid_threshold = 0
    settings.voxel_size = 0.25
    settings.cube_gap = 0.02
    settings.auto_watertight_copy = True
    settings.repair_voxel_size = 0.08
    settings.sampling_chunk_size = 128
    settings.fallback_color = (0.2, 0.6, 0.9, 1.0)

    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.active_object
    cube.name = "V050_Cube"
    cube_before = source_snapshot(cube)

    require(bpy.ops.voxelizer.quality_preset(preset="MEDIUM") == {"FINISHED"}, "preset failed")
    require(settings.quality_preset == "MEDIUM", "preset identity missing")
    require(math.isclose(settings.voxel_size, 2.0 / 24.0, abs_tol=1.0e-6), "preset size")
    settings.voxel_size = 0.25
    settings.cube_gap = 0.02
    require(bpy.ops.voxelizer.estimate() == {"FINISHED"}, "estimate failed")
    require("1 source" in settings.estimate_summary, settings.estimate_summary)

    require(bpy.ops.voxelizer.preview() == {"FINISHED"}, "cube preview failed")
    cube_preview = require_preview_contract(cube)
    cube_points = [vertex.co.copy() for vertex in cube_preview.data.vertices]
    first_diagnostics = core.sampling_diagnostics(cube)
    require(first_diagnostics["candidate_strategy"] == "TRIANGLE_AABB_SPARSE", first_diagnostics)
    require(first_diagnostics["grid_origin_mode"] == "OBJECT", first_diagnostics)
    require(not first_diagnostics["cache_hit"], first_diagnostics)
    require(
        first_diagnostics["candidate_count"] <= first_diagnostics["full_grid_count"],
        first_diagnostics,
    )
    require_mirror_closure(cube_points, first_diagnostics["source_symmetry"], 1.0e-6)

    cancelled_mesh_name = "V050_CancelledBakeMesh"
    cancelled_job = core.build_voxel_mesh_iter(
        bpy.context,
        cube,
        settings,
        cancelled_mesh_name,
        cache_key=core.preview_sampling_key(bpy.context, cube, settings),
    )
    while True:
        cancelled_progress = next(cancelled_job)
        if cancelled_progress.phase == "BAKE_COLOUR":
            break
    cancelled_job.close()
    require(
        bpy.data.meshes.get(cancelled_mesh_name) is None,
        "cancelled Bake left an orphan mesh",
    )

    select_only(cube)
    require(bpy.ops.voxelizer.bake() == {"FINISHED"}, "cube bake failed")
    baked = bpy.data.objects.get(core.bake_name(cube))
    require(baked is not None, "cube bake output missing")
    require(len(baked.data.vertices) == len(cube_points) * 8, "bake is not 8V per voxel")
    require(len(baked.data.polygons) == len(cube_points) * 6, "bake is not 6F per voxel")
    require(core.sampling_diagnostics(cube)["cache_hit"], "Bake did not reuse Preview cache")
    require_unchanged(cube, cube_before)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
    sphere = bpy.context.active_object
    sphere.name = "V050_UVSphere"
    sphere_before = source_snapshot(sphere)
    settings.voxel_size = 0.28
    sphere_coarse, _colours, coarse_count, _used = core.sample_surface_voxels(
        bpy.context, sphere, settings, use_cache=False
    )
    sphere_diagnostics = core.sampling_diagnostics(sphere)
    require_mirror_closure(sphere_coarse, sphere_diagnostics["source_symmetry"], 1.0e-6)
    settings.voxel_size = 0.16
    sphere_fine, _colours, fine_count, _used = core.sample_surface_voxels(
        bpy.context, sphere, settings, use_cache=False
    )
    require(fine_count > coarse_count, (coarse_count, fine_count))
    require_mirror_closure(
        sphere_fine,
        core.sampling_diagnostics(sphere)["source_symmetry"],
        1.0e-6,
    )
    require_unchanged(sphere, sphere_before)

    bpy.ops.mesh.primitive_monkey_add()
    suzanne = bpy.context.active_object
    suzanne.name = "V050_StockSuzanne"
    suzanne_before = source_snapshot(suzanne)
    suzanne_raw = core.mesh_diagnostics(suzanne.data)
    require(suzanne_raw["boundary_edges"] > 0, "stock Suzanne unexpectedly watertight")
    settings.voxel_size = 0.28
    settings.repair_voxel_size = 0.08
    suzanne_centres, _colours, suzanne_count, _used = core.sample_surface_voxels(
        bpy.context, suzanne, settings, use_cache=False
    )
    suzanne_sampling = core.sampling_diagnostics(suzanne)
    require(suzanne_sampling["helper_used"], "Suzanne repair helper was not used")
    require("X" in suzanne_sampling["proven_axes"], suzanne_sampling)
    require_mirror_closure(
        suzanne_centres,
        suzanne_sampling["source_symmetry"],
        1.0e-6,
    )
    require(suzanne_count > 0, "Suzanne sampling returned no voxels")
    require_unchanged(suzanne, suzanne_before)

    ngon = create_concave_ngon_prism()
    ngon_before = source_snapshot(ngon)
    select_only(ngon)
    settings.voxel_size = 0.24
    settings.cube_gap = 0.02
    require(bpy.ops.voxelizer.preview() == {"FINISHED"}, "NGON preview failed")
    ngon_preview = require_preview_contract(ngon)
    require(len(ngon_preview.data.vertices) > 50, "NGON edge coverage unexpectedly sparse")
    for vertex in ngon_preview.data.vertices:
        # Non-proven X/Y axes remain exactly anchored to the object-origin lattice.
        for axis in (0, 1):
            quotient = float(vertex.co[axis]) / settings.voxel_size
            require(abs(quotient - round(quotient)) < 1.0e-5, "fixed grid drift")
    require_unchanged(ngon, ngon_before)

    select_only(sphere)
    cube.select_set(True)
    settings.source_scope = "SELECTED"
    settings.voxel_size = 0.3
    require(bpy.ops.voxelizer.preview() == {"FINISHED"}, "batch preview failed")
    require_preview_contract(cube)
    require_preview_contract(sphere)
    require(settings.live_point_count > 0, "batch point total missing")

    cache_stats = core.sampling_cache_stats()
    require(cache_stats["entries"] >= 2, cache_stats)
    require(cache_stats["bytes"] > 0, cache_stats)
    require(bpy.ops.voxelizer.clear_cache() == {"FINISHED"}, "clear cache failed")
    require(core.sampling_cache_stats() == {"entries": 0, "bytes": 0}, "cache not cleared")

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "cube_voxels": len(cube_points),
        "sphere_coarse": coarse_count,
        "sphere_fine": fine_count,
        "suzanne_voxels": suzanne_count,
        "ngon_voxels": len(ngon_preview.data.vertices),
        "sparse_candidate_count": first_diagnostics["candidate_count"],
        "full_grid_count": first_diagnostics["full_grid_count"],
        "preview_bake_cache_hit": True,
        "cancel_cleanup": True,
        "multi_object_preview": True,
        "fixed_origin": True,
        "symmetry_closure": True,
        "source_unchanged": True,
    }
    print("PASS chromoxel_blender_0.5.0_regression", json.dumps(report, sort_keys=True))


run()
