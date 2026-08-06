"""Render the Chromoxel 0.6 bullseye acceptance image in Blender 5.1.

Run from the repository root:
    blender --background --factory-startup --python tools/render_adaptive_bullseye.py
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "docs" / "images" / "chromoxel-adaptive-bullseye.png"
sys.path.insert(0, str(REPOSITORY_ROOT))

import voxelizer  # noqa: E402
from voxelizer import core  # noqa: E402


def look_at(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat("-Z", "Y").to_euler()


def material(name, colour, *, metallic=0.0, roughness=0.42, emission=None):
    result = bpy.data.materials.new(name)
    result.diffuse_color = colour
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = colour
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    if emission is not None:
        shader.inputs["Emission Color"].default_value = emission
        shader.inputs["Emission Strength"].default_value = 3.0
    return result


def cube(name, location, scale, assigned_material, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(assigned_material)
    if bevel > 0.0:
        modifier = obj.modifiers.new("Soft edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    return obj


def create_bullseye_image(size=256):
    image = bpy.data.images.new("Chromoxel_Bullseye", width=size, height=size, alpha=True)
    pixels = []
    for y in range(size):
        for x in range(size):
            dx = ((x + 0.5) / size - 0.5) * 2.0
            dy = ((y + 0.5) / size - 0.5) * 2.0
            radius = math.sqrt(dx * dx + dy * dy)
            red = radius <= 0.13 or 0.37 <= radius <= 0.50
            pixels.extend((0.92, 0.025, 0.018, 1.0) if red else (0.96, 0.96, 0.92, 1.0))
    image.pixels = pixels
    image.update()
    return image


def create_target_materials(image):
    target = bpy.data.materials.new("Chromoxel_Target")
    target.use_nodes = True
    nodes = target.node_tree.nodes
    links = target.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.34
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    uv_map = nodes.new("ShaderNodeUVMap")
    uv_map.uv_map = "UVMap"
    links.new(uv_map.outputs["UV"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    white = material("Chromoxel_TargetSides", (0.82, 0.84, 0.86, 1.0), roughness=0.38)
    return target, white


def create_target(image):
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
    mesh = bpy.data.meshes.new("Chromoxel_TargetMesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    target_material, side_material = create_target_materials(image)
    mesh.materials.append(target_material)
    mesh.materials.append(side_material)
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
    obj = bpy.data.objects.new("Bullseye_Source", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def create_voxel_version(source, settings, name, mode, max_level):
    settings.sampling_mode = mode
    settings.adaptive_max_level = max_level
    mesh, count, _used_image = core.build_voxel_mesh(
        bpy.context,
        source,
        settings,
        name + "_Mesh",
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj, count


def add_text(body, location, size, assigned_material, *, extrude=0.012):
    curve = bpy.data.curves.new(body + "_Curve", "FONT")
    curve.body = body
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = size
    curve.extrude = extrude
    curve.bevel_depth = 0.004
    obj = bpy.data.objects.new(body, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(assigned_material)
    return obj


def configure_world(scene):
    world = bpy.data.worlds.new("Chromoxel_WarmGradient")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.32
    coordinates = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.22
    ramp.color_ramp.elements[0].color = (0.012, 0.018, 0.04, 1.0)
    ramp.color_ramp.elements[1].position = 0.78
    ramp.color_ramp.elements[1].color = (0.34, 0.095, 0.012, 1.0)
    links.new(coordinates.outputs["Normal"], separate.inputs["Vector"])
    links.new(separate.outputs["Z"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])


def configure_cycles(scene):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.cycles.preview_samples = 16
    scene.cycles.use_preview_denoising = True
    backend = "CPU"
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is not None:
        preferences = addon.preferences
        for candidate in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
            try:
                preferences.compute_device_type = candidate
                preferences.get_devices()
            except Exception:
                continue
            enabled = False
            for device in preferences.devices:
                device.use = device.type != "CPU"
                enabled = enabled or bool(device.use)
            if enabled:
                scene.cycles.device = "GPU"
                backend = candidate
                break
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.filepath = str(OUTPUT_PATH)
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.look = "AgX - Medium High Contrast"
    return backend


def configure_compositor(scene):
    scene.use_nodes = True
    node_tree = getattr(scene, "node_tree", None)
    if node_tree is None:
        # Blender 5.1 moved compositor construction to its new node-group API
        # and no longer exposes the legacy Composite output node. The scene's
        # emissive geometry provides a compatible restrained highlight instead.
        return False
    nodes = node_tree.nodes
    links = node_tree.links
    nodes.clear()
    render_layers = nodes.new("CompositorNodeRLayers")
    glare = nodes.new("CompositorNodeGlare")
    composite = nodes.new("CompositorNodeComposite")
    if hasattr(glare, "glare_type"):
        glare.glare_type = "FOG_GLOW"
        glare.quality = "HIGH"
        glare.threshold = 1.2
        glare.size = 6
        glare.mix = -0.82
        links.new(render_layers.outputs["Image"], glare.inputs["Image"])
        links.new(glare.outputs["Image"], composite.inputs["Image"])
    else:
        # Blender 5.1's new compositor exposes legacy Glare without its RNA
        # controls. Keep the render valid; emissive labels and area lights still
        # provide the intended restrained glow in the Cycles image.
        nodes.remove(glare)
        links.new(render_layers.outputs["Image"], composite.inputs["Image"])
    return True


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    scene = bpy.context.scene
    image = create_bullseye_image()
    source = create_target(image)
    settings = scene.voxelizer_settings
    settings.source_scope = "ACTIVE"
    settings.grid_origin_mode = "OBJECT"
    settings.voxel_size = 0.5
    settings.cube_gap = 0.035
    settings.auto_watertight_copy = True
    settings.auto_material_images = True
    settings.base_color_image = None
    settings.uv_map = ""
    settings.texture_filter = "BILINEAR"
    settings.use_sparse_candidates = True
    settings.sparse_grid_threshold = 0
    settings.sample_budget = 200_000
    settings.voxel_budget = 100_000
    settings.adaptive_texture_threshold = 0.12
    settings.adaptive_geometry_angle = 35.0
    settings.adaptive_geometry_max_level = 1

    uniform, uniform_count = create_voxel_version(source, settings, "Uniform_Voxels", "UNIFORM", 0)
    adaptive, adaptive_count = create_voxel_version(source, settings, "Adaptive_Voxels", "ADAPTIVE", 3)

    source.location = (-3.35, 0.0, 0.58)
    uniform.location = (0.0, 0.0, 0.58)
    adaptive.location = (3.35, 0.0, 0.58)

    charcoal = material("Platform", (0.018, 0.025, 0.042, 1.0), metallic=0.2, roughness=0.3)
    trim = material("PlatformTrim", (0.028, 0.22, 0.30, 1.0), metallic=0.38, roughness=0.25)
    floor_material = material("Floor", (0.009, 0.013, 0.022, 1.0), metallic=0.15, roughness=0.3)
    label_material = material(
        "LabelGlow",
        (0.08, 0.7, 0.92, 1.0),
        roughness=0.3,
        emission=(0.04, 0.52, 0.85, 1.0),
    )
    accent_material = material(
        "AccentGlow",
        (1.0, 0.32, 0.05, 1.0),
        roughness=0.3,
        emission=(1.0, 0.08, 0.008, 1.0),
    )
    cube("Floor", (0.0, 0.0, -0.18), (6.5, 3.2, 0.14), floor_material, bevel=0.08)
    for x in (-3.35, 0.0, 3.35):
        cube("DisplayBase", (x, 0.0, 0.18), (1.42, 1.42, 0.18), charcoal, bevel=0.1)
        cube("DisplayTrim", (x, 0.0, 0.38), (1.34, 1.34, 0.035), trim, bevel=0.025)

    add_text("ORIGINAL", (-3.35, -1.75, 0.08), 0.27, label_material)
    add_text(f"UNIFORM  /  0.50 BU  /  {uniform_count}", (0.0, -1.75, 0.08), 0.19, label_material)
    add_text(
        f"ADAPTIVE L3  /  MIN 0.0625 BU  /  {adaptive_count}",
        (3.35, -1.75, 0.08),
        0.17,
        accent_material,
    )
    title = add_text(
        "CHROMOXEL 0.6  /  TEXTURE-AWARE ADAPTIVE VOXELIZATION",
        (0.0, 2.65, 2.35),
        0.30,
        label_material,
        extrude=0.018,
    )
    title.rotation_euler.x = math.radians(90.0)

    configure_world(scene)
    sun_data = bpy.data.lights.new("WarmSun", "SUN")
    sun_data.energy = 3.0
    sun_data.angle = math.radians(16.0)
    sun_data.color = (1.0, 0.62, 0.34)
    sun = bpy.data.objects.new("WarmSun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(28.0), math.radians(-18.0), math.radians(-35.0))
    key_data = bpy.data.lights.new("SoftKey", "AREA")
    key_data.energy = 850.0
    key_data.shape = "DISK"
    key_data.size = 6.0
    key_data.color = (0.55, 0.78, 1.0)
    key = bpy.data.objects.new("SoftKey", key_data)
    scene.collection.objects.link(key)
    key.location = (-1.5, -4.0, 7.0)
    look_at(key, (0.0, 0.0, 0.5))
    rim_data = bpy.data.lights.new("WarmRim", "AREA")
    rim_data.energy = 650.0
    rim_data.size = 4.0
    rim_data.color = (1.0, 0.22, 0.04)
    rim = bpy.data.objects.new("WarmRim", rim_data)
    scene.collection.objects.link(rim)
    rim.location = (4.0, 4.0, 5.0)
    look_at(rim, (1.0, 0.0, 0.7))

    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.location = (10.5, -15.2, 12.8)
    camera_data.lens = 54.0
    look_at(camera, (0.0, 0.20, 0.55))

    backend = configure_cycles(scene)
    configure_compositor(scene)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    print(
        "PASS chromoxel_blender_0.6.0_visual",
        f"uniform={uniform_count}",
        f"adaptive={adaptive_count}",
        f"cycles={backend}",
        f"output={OUTPUT_PATH}",
    )


main()
