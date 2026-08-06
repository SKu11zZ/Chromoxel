"""Adaptive texture/geometry regression for Chromoxel Blender 0.6."""

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


def create_bullseye_image(size=128):
    image = bpy.data.images.new("V060_Bullseye", width=size, height=size, alpha=True)
    pixels = []
    for y in range(size):
        for x in range(size):
            dx = ((x + 0.5) / size - 0.5) * 2.0
            dy = ((y + 0.5) / size - 0.5) * 2.0
            radius = (dx * dx + dy * dy) ** 0.5
            red = radius <= 0.13 or 0.37 <= radius <= 0.50
            pixels.extend((1.0, 0.0, 0.0, 1.0) if red else (1.0, 1.0, 1.0, 1.0))
    image.pixels = pixels
    image.update()
    return image


def create_materials(image):
    target = bpy.data.materials.new("V060_TargetMaterial")
    target.use_nodes = True
    nodes = target.node_tree.nodes
    links = target.node_tree.links
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

    white = bpy.data.materials.new("V060_WhiteMaterial")
    white.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    white.use_nodes = True
    white.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (
        1.0,
        1.0,
        1.0,
        1.0,
    )
    return target, white


def create_target_box(image):
    vertices = (
        (-1.0, -1.0, -0.1),
        (1.0, -1.0, -0.1),
        (1.0, 1.0, -0.1),
        (-1.0, 1.0, -0.1),
        (-1.0, -1.0, 0.1),
        (1.0, -1.0, 0.1),
        (1.0, 1.0, 0.1),
        (-1.0, 1.0, 0.1),
    )
    faces = (
        (3, 2, 1, 0),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    mesh = bpy.data.meshes.new("V060_TargetMesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    target_material, white_material = create_materials(image)
    mesh.materials.append(target_material)
    mesh.materials.append(white_material)
    mesh.polygons[0].material_index = 0
    mesh.polygons[1].material_index = 0
    for polygon in mesh.polygons[2:]:
        polygon.material_index = 1

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv_layer.data[loop_index].uv = (
                (float(vertex.x) + 1.0) * 0.5,
                (float(vertex.y) + 1.0) * 0.5,
            )
    obj = bpy.data.objects.new("V060_BullseyeTarget", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def sample_key(centre, size, extent):
    return (
        tuple(round(float(value), 7) for value in centre)
        + (round(float(size), 7),)
        + tuple(round(float(value), 7) for value in extent)
    )


def require_symmetric(result, diagnostics):
    keys = {
        sample_key(centre, size, extent)
        for centre, size, extent in zip(result.centres, result.sizes, result.extents)
    }
    for axis_name in diagnostics["proven_axes"]:
        axis = "XYZ".index(axis_name)
        plane = float(diagnostics["source_symmetry"]["axes"][axis_name]["plane"])
        for centre, size, extent in zip(result.centres, result.sizes, result.extents):
            mirrored = Vector(centre)
            mirrored[axis] = 2.0 * plane - mirrored[axis]
            require(
                sample_key(mirrored, size, extent) in keys,
                f"missing adaptive {axis_name} orbit",
            )


def run():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    image = create_bullseye_image()
    source = create_target_box(image)
    settings = bpy.context.scene.voxelizer_settings
    settings.source_scope = "ACTIVE"
    settings.grid_origin_mode = "OBJECT"
    settings.voxel_size = 0.5
    settings.cube_gap = 0.025
    settings.auto_watertight_copy = True
    settings.auto_material_images = True
    settings.base_color_image = None
    settings.uv_map = ""
    settings.texture_filter = "BILINEAR"
    settings.use_sparse_candidates = True
    settings.sparse_grid_threshold = 0
    settings.sample_budget = 200_000
    settings.voxel_budget = 100_000

    settings.sampling_mode = "UNIFORM"
    uniform = core.sample_surface_voxels(bpy.context, source, settings, use_cache=False)
    require(uniform.used_image, "auto material image was not detected")
    require(set(uniform.levels) == {0}, uniform.levels)
    require(set(round(value, 7) for value in uniform.sizes) == {0.5}, uniform.sizes)
    require(
        all(tuple(round(float(axis), 7) for axis in extent) == (0.5, 0.5, 0.5)
            for extent in uniform.extents),
        uniform.extents,
    )
    require(
        any(colour[0] > colour[1] + 0.25 for colour in uniform.colours),
        "uniform compatibility path did not sample the image",
    )

    settings.sampling_mode = "ADAPTIVE"
    settings.adaptive_max_level = 2
    settings.adaptive_texture_threshold = 0.12
    settings.adaptive_geometry_angle = 35.0
    adaptive = core.sample_surface_voxels(bpy.context, source, settings, use_cache=False)
    diagnostics = core.sampling_diagnostics(source)
    require(adaptive.used_image, "adaptive pass lost material image")
    require(adaptive.count > uniform.count, (uniform.count, adaptive.count))
    require(2 in adaptive.levels, diagnostics["adaptive"])
    require(min(adaptive.sizes) == 0.125, min(adaptive.sizes))
    require(diagnostics["adaptive"]["refined_parent_count"] > 0, diagnostics)
    require(diagnostics["adaptive"]["planar_refined_parent_count"] > 0, diagnostics)
    require(diagnostics["adaptive_rejected_seed_count"] > 0, diagnostics)
    require(
        max(abs(float(centre.z)) for centre in adaptive.centres) < 0.4,
        "circumsphere-only outer layer survived adaptive filtering",
    )
    require_symmetric(adaptive, diagnostics)

    profile_fill = 1.0 - settings.cube_gap / settings.voxel_size
    front_profile = {}
    for centre, cell_size, cell_extent, level in zip(
        adaptive.centres,
        adaptive.sizes,
        adaptive.extents,
        adaptive.levels,
    ):
        if abs(centre.z) > 0.25 or abs(centre.x) >= 0.75 or abs(centre.y) >= 0.75:
            continue
        outer_face = float(centre.z) + float(cell_extent.z) * profile_fill * 0.5
        front_profile.setdefault(str(level), []).append(outer_face)
    require("1" in front_profile and "2" in front_profile, front_profile)
    flat_faces = [value for values in front_profile.values() for value in values]
    require(
        max(flat_faces) - min(flat_faces) <= 1.0e-6,
        ("adaptive planar surface is not flush", front_profile),
    )
    require(
        any(
            level == 2
            and math.isclose(float(extent.z), settings.voxel_size, abs_tol=1.0e-7)
            and math.isclose(float(extent.x), size, abs_tol=1.0e-7)
            and math.isclose(float(extent.y), size, abs_tol=1.0e-7)
            for size, extent, level in zip(adaptive.sizes, adaptive.extents, adaptive.levels)
        ),
        "texture-only planar refinement did not preserve normal thickness",
    )

    settings.adaptive_max_level = 4
    settings.voxel_size = 0.25
    settings.voxel_budget = 1_000
    budgeted = core.sample_surface_voxels(bpy.context, source, settings, use_cache=False)
    budget_diagnostics = core.sampling_diagnostics(source)
    require(budgeted.count <= 1_000, budgeted.count)
    require(budget_diagnostics["adaptive"]["budget_limited"], budget_diagnostics)
    require(3 in budgeted.levels, budget_diagnostics["adaptive"])
    settings.voxel_size = 0.5
    settings.adaptive_max_level = 2
    settings.voxel_budget = 100_000
    adaptive = core.sample_surface_voxels(bpy.context, source, settings, use_cache=False)
    diagnostics = core.sampling_diagnostics(source)

    red_xy = {
        (round(float(centre.x), 4), round(float(centre.y), 4))
        for centre, colour, level in zip(adaptive.centres, adaptive.colours, adaptive.levels)
        if level == 2 and colour[0] > colour[1] + 0.12
    }
    require(len(red_xy) >= 12, red_xy)
    require(
        any(abs(x) > 0.12 and abs(y) > 0.12 for x, y in red_xy),
        "adaptive bullseye collapsed to an axis-aligned cross",
    )

    require(bpy.ops.voxelizer.preview() == {"FINISHED"}, "adaptive preview failed")
    output = bpy.data.objects.get(core.preview_name(source))
    require(output is not None, "adaptive preview missing")
    require(output.data.attributes.get(core.SIZE_ATTRIBUTE) is not None, "preview size missing")
    require(output.data.attributes.get(core.EXTENT_ATTRIBUTE) is not None, "preview extent missing")
    require(output.data.attributes.get(core.LEVEL_ATTRIBUTE) is not None, "preview level missing")
    modifier = output.modifiers.get(preview.MODIFIER_NAME)
    require(modifier is not None, "adaptive GN modifier missing")
    require(
        modifier.node_group.nodes.get("BTVM_Voxel_Extent") is not None,
        "GN extent reader missing",
    )

    require(bpy.ops.voxelizer.bake() == {"FINISHED"}, "adaptive bake failed")
    baked = bpy.data.objects.get(core.bake_name(source))
    require(baked is not None, "adaptive bake missing")
    require(baked.data.attributes.get(core.SIZE_ATTRIBUTE) is not None, "bake size missing")
    require(baked.data.attributes.get(core.EXTENT_ATTRIBUTE) is not None, "bake extent missing")
    require(baked.data.attributes.get(core.LEVEL_ATTRIBUTE) is not None, "bake level missing")
    require(
        len(baked.data.vertices) == adaptive.count * 8,
        "adaptive bake cube topology does not match the sampled cells",
    )
    fill_ratio = 1.0 - settings.cube_gap / settings.voxel_size
    for cell_index, cell_extent in enumerate(adaptive.extents):
        cube = baked.data.vertices[cell_index * 8 : (cell_index + 1) * 8]
        for axis in range(3):
            extent = max(vertex.co[axis] for vertex in cube) - min(
                vertex.co[axis] for vertex in cube
            )
            require(
                math.isclose(
                    extent,
                    float(cell_extent[axis]) * fill_ratio,
                    rel_tol=0.0,
                    abs_tol=1.0e-5,
                ),
                (
                    "adaptive display gap did not scale with the cell size",
                    cell_index,
                    tuple(cell_extent),
                    extent,
                    fill_ratio,
                ),
            )

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "uniform_voxels": uniform.count,
        "adaptive_voxels": adaptive.count,
        "budgeted_voxels": budgeted.count,
        "level_histogram": diagnostics["adaptive"]["level_histogram"],
        "red_detail_cells": len(red_xy),
        "rejected_seed_candidates": diagnostics["adaptive_rejected_seed_count"],
        "auto_material_image": True,
        "symmetry_closure": True,
        "preview_variable_size": True,
        "bake_variable_size": True,
        "display_gap_scales_with_level": True,
        "planar_surface_flush": True,
    }
    print("PASS chromoxel_blender_0.6.0_adaptive", json.dumps(report, sort_keys=True))


run()
