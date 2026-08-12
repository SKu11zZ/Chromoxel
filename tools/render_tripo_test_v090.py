"""Render a saved four-model Chromoxel 0.9 TripoTest project."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
import traceback

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import core, editable, meshing  # noqa: E402


KEYS = ("214730", "220646", "112043", "112406")
TARGETS = (2_000, 20_000, 100_000)
POSITIONS = (-9.0, -3.0, 3.0, 9.0)
OUTPUT_DIR = None
REPORT_PATH = None
LOG_PATH = None
PENDING_ARGS = None


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=32)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def mark(message):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"{time.perf_counter():.6f} {message}\n")


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def material(name, color, roughness=0.45, metallic=0.0, emission=0.0):
    result = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    result.use_nodes = True
    principled = result.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    emission_socket = principled.inputs.get("Emission Color") or principled.inputs.get("Emission")
    if emission_socket is not None:
        emission_socket.default_value = color
    strength = principled.inputs.get("Emission Strength")
    if strength is not None:
        strength.default_value = emission
    return result


def add_text(body, location, size, text_material, collection, name):
    curve = bpy.data.curves.new(name + "_Curve", "FONT")
    curve.body = body
    curve.align_x = "LEFT"
    curve.align_y = "CENTER"
    curve.size = size
    curve.extrude = 0.006
    curve.bevel_depth = 0.002
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler.x = math.radians(87.0)
    obj.data.materials.append(text_material)
    return obj


def clean_render_artifacts():
    for obj in tuple(bpy.data.objects):
        if obj.name.startswith("V090_LABEL_") or obj.name.startswith("V090_RENDER_"):
            data = getattr(obj, "data", None)
            object_type = obj.type
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and not data.users:
                if object_type == "MESH":
                    bpy.data.meshes.remove(data)
                elif object_type in {"CURVE", "FONT"}:
                    bpy.data.curves.remove(data)


def configure_render(samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(8, int(samples))
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 5
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 2
    scene.render.use_simplify = True
    scene.render.resolution_x = 3200
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.65
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass

    backend = "CPU"
    preferences = bpy.context.preferences.addons.get("cycles")
    if preferences is not None:
        cycles_preferences = preferences.preferences
        for candidate in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
            try:
                cycles_preferences.compute_device_type = candidate
                cycles_preferences.get_devices()
                enabled = 0
                for device in cycles_preferences.devices:
                    device.use = device.type != "CPU"
                    enabled += int(device.use)
                if enabled:
                    scene.cycles.device = "GPU"
                    backend = candidate
                    break
            except (TypeError, RuntimeError):
                continue

    world = scene.world or bpy.data.worlds.new("Chromoxel Tripo V090 World")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.62
    texcoord = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = (0.006, 0.014, 0.032, 1.0)
    ramp.color_ramp.elements[1].position = 0.80
    ramp.color_ramp.elements[1].color = (0.27, 0.055, 0.012, 1.0)
    links.new(texcoord.outputs["Normal"], separate.inputs["Vector"])
    links.new(separate.outputs["Z"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])

    stage = bpy.data.objects.get("Chromoxel Tripo Stage")
    if stage is not None:
        stage.scale = (2.0, 2.0, 2.0)
        stage.data.materials.clear()
        stage.data.materials.append(
            material("Tripo V090 Stage", (0.016, 0.028, 0.052, 1.0), 0.32, 0.10)
        )

    light_settings = {
        "Tripo Warm Key": (4.2, (1.0, 0.76, 0.58), 0.20),
        "Tripo Cool Fill": (2.0, (0.64, 0.78, 1.0), 0.28),
        "Tripo Rim": (1.65, (1.0, 0.62, 0.42), 0.24),
    }
    for name, (energy, color, angle) in light_settings.items():
        light = bpy.data.objects.get(name)
        if light is not None:
            light.data.type = "SUN"
            light.data.energy = energy
            light.data.color = color
            light.data.angle = angle

    camera = scene.camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 31.0
    camera.location = (0.0, -34.0, 8.0)
    point_at(camera, (0.0, 0.0, 2.35))

    scene.use_nodes = True
    compositor = getattr(scene, "node_tree", None)
    if compositor is not None:
        compositor.nodes.clear()
        layers = compositor.nodes.new("CompositorNodeRLayers")
        glare = compositor.nodes.new("CompositorNodeGlare")
        glare.glare_type = "FOG_GLOW"
        glare.quality = "HIGH"
        glare.threshold = 1.0
        glare.size = 6
        glare.mix = -0.96
        composite = compositor.nodes.new("CompositorNodeComposite")
        compositor.links.new(layers.outputs["Image"], glare.inputs["Image"])
        compositor.links.new(glare.outputs["Image"], composite.inputs["Image"])
    return backend


def carriers(key):
    found = sorted(
        (
            obj for obj in bpy.data.objects
            if obj.name.startswith(f"{key}_") and obj.name.endswith("_EDITABLE")
        ),
        key=lambda obj: int(obj.get("chromoxel_target_voxels", 0)),
    )
    if len(found) != 3:
        raise RuntimeError(f"Expected three editable outputs for {key}, got {len(found)}")
    return found


def set_visibility(active_key):
    for obj in bpy.data.objects:
        if obj.name.startswith("SRC_TRIPO_") or obj.name.startswith(".BTVM_"):
            obj.hide_render = True
        elif obj.name.startswith("V090_LABEL_"):
            obj.hide_render = not obj.name.startswith(f"V090_LABEL_{active_key}_")
        elif obj.name.startswith("V090_RENDER_"):
            obj.hide_render = not obj.name.startswith(f"V090_RENDER_{active_key}_")
        elif any(obj.name.startswith(f"{key}_") for key in KEYS):
            obj.hide_render = not obj.name.startswith(f"{active_key}_")
            if obj.name.endswith("_EDITABLE"):
                obj.hide_render = True


def place_and_realize(key, text_material):
    collection = bpy.data.collections.get(f"TRIPO_{key}")
    original = bpy.data.objects[f"{key}_ORIGINAL"]
    points = carriers(key)
    model_objects = [original, *points]
    yaw = math.radians(45.0)
    for index, obj in enumerate(model_objects):
        obj.location = (POSITIONS[index], 0.0, 0.0)
        obj.rotation_euler = (0.0, 0.0, yaw)
    bpy.context.view_layer.update()
    if key == "112043":
        # A few thin tendrils extend far below the visual mass. Sink only the
        # lowest 0.5% so the body reads as grounded without burying its shape.
        original_world_z = sorted(
            float((original.matrix_world @ vertex.co).z)
            for vertex in original.data.vertices
        )
        original_ground = original_world_z[max(0, int(len(original_world_z) * 0.005) - 1)]
    else:
        original_ground = min(
            (original.matrix_world @ Vector(corner)).z
            for corner in original.bound_box
        )
    original.location.z -= original_ground
    bpy.context.view_layer.update()

    colour_material = core.ensure_colour_material()
    realized = []
    stats = [{
        "kind": "original",
        "vertices": len(original.data.vertices),
        "faces": len(original.data.polygons),
    }]
    for point_object in points:
        mesh, _count = meshing.build_from_editable(
            point_object,
            "REALIZED",
            f"V090_RENDER_{point_object.name}_MESH",
            remove_enclosed=True,
        )
        mesh.transform(point_object.matrix_world)
        z_values = sorted(float(vertex.co.z) for vertex in mesh.vertices)
        if key == "112043":
            ground = z_values[max(0, int(len(z_values) * 0.005) - 1)]
        else:
            ground = z_values[0]
        mesh.transform(Matrix.Translation((0.0, 0.0, -ground)))
        mesh.update()
        render_object = bpy.data.objects.new(f"V090_RENDER_{point_object.name}", mesh)
        collection.objects.link(render_object)
        if not mesh.materials:
            mesh.materials.append(colour_material)
        realized.append(render_object)
        input_voxels = len(point_object.data.vertices)
        stats.append({
            "kind": "voxel",
            "target_voxels": int(point_object.get("chromoxel_target_voxels", 0)),
            "input_voxels": input_voxels,
            "optimized_voxels": int(mesh.get(meshing.ENCLOSED_OUTPUT_TAG, input_voxels)),
            "removed_enclosed_voxels": int(mesh.get(meshing.ENCLOSED_REMOVED_TAG, 0)),
            "faces": len(mesh.polygons),
            "voxel_size_bu": round(
                float(point_object.get("chromoxel_cli_voxel_size", point_object.get(editable.GRID_SIZE_TAG, 0.0))),
                9,
            ),
        })

    labels = (
        "ORIGINAL\n"
        f"{stats[0]['vertices']:,} VERTICES\n"
        f"{stats[0]['faces']:,} FACES",
        "~2,000 INPUT\n"
        f"{stats[1]['input_voxels']:,} > {stats[1]['optimized_voxels']:,} VOXELS\n"
        f"-{stats[1]['removed_enclosed_voxels']:,} ENCLOSED  |  {stats[1]['faces']:,} FACES\n"
        f"CELL {stats[1]['voxel_size_bu']:.5f} BU",
        "~20,000 INPUT\n"
        f"{stats[2]['input_voxels']:,} > {stats[2]['optimized_voxels']:,} VOXELS\n"
        f"-{stats[2]['removed_enclosed_voxels']:,} ENCLOSED  |  {stats[2]['faces']:,} FACES\n"
        f"CELL {stats[2]['voxel_size_bu']:.5f} BU",
        "~100,000 INPUT\n"
        f"{stats[3]['input_voxels']:,} > {stats[3]['optimized_voxels']:,} VOXELS\n"
        f"-{stats[3]['removed_enclosed_voxels']:,} ENCLOSED  |  {stats[3]['faces']:,} FACES\n"
        f"CELL {stats[3]['voxel_size_bu']:.5f} BU",
    )
    for index, label in enumerate(labels):
        add_text(
            label,
            (POSITIONS[index] - 2.5, -5.0, 5.65),
            0.19,
            text_material,
            collection,
            f"V090_LABEL_{key}_{index}",
        )
    title = add_text(
        f"TRIPO {key}  /  CHROMOXEL 0.9.0  /  45 DEG  /  CYCLES",
        (-11.5, -5.1, 6.55),
        0.30,
        text_material,
        collection,
        f"V090_LABEL_{key}_TITLE",
    )
    title.data.align_x = "LEFT"
    return original, realized, stats


def main(args):
    global OUTPUT_DIR, REPORT_PATH, LOG_PATH
    OUTPUT_DIR = args.output_dir.resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH = OUTPUT_DIR / "Chromoxel_TripoTest_V090_Four_Models.json"
    LOG_PATH = OUTPUT_DIR / "Chromoxel_TripoTest_V090_Render.log"
    LOG_PATH.write_text("", encoding="utf-8")
    if not hasattr(bpy.types.Scene, "voxelizer_settings"):
        voxelizer.register()
    clean_render_artifacts()
    backend = configure_render(args.samples)
    text_material = material(
        "Tripo V090 Label Emission",
        (0.68, 0.95, 1.0, 1.0),
        0.3,
        0.0,
        4.0,
    )
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    renders = {}
    for key in KEYS:
        mark(f"{key} layout start")
        set_visibility(key)
        original, realized, stats = place_and_realize(key, text_material)
        original.hide_render = False
        for render_object in realized:
            render_object.hide_render = False
        path = OUTPUT_DIR / f"Tripo_{key}_V090_Original_2K_20K_100K.png"
        bpy.context.scene.render.filepath = str(path)
        started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        renders[key] = {
            "path": str(path),
            "seconds": round(time.perf_counter() - started, 3),
            "mesh_stats": stats,
            "camera_degrees": 45,
        }
        mark(f"{key} render complete {renders[key]['seconds']}")
        original.hide_render = True
        for render_object in realized:
            render_object.hide_render = True

    report["status"] = "RENDERED"
    report["render"] = {
        "engine": "CYCLES",
        "backend": backend,
        "samples": bpy.context.scene.cycles.samples,
        "resolution": [3200, 800],
        "remove_enclosed_voxels": True,
        "renders": renders,
        "combined": str(OUTPUT_DIR / "Chromoxel_TripoTest_V090_Four_Models_Combined.png"),
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for key in KEYS:
        for obj in bpy.data.objects:
            if obj.name.startswith(f"{key}_") or obj.name.startswith(f"V090_LABEL_{key}_"):
                obj.hide_render = key != KEYS[0] or obj.name.endswith("_EDITABLE")
    project = OUTPUT_DIR / "Chromoxel_TripoTest_V090_Four_Models.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(project), compress=True)
    print("PASS tripo_test_v090_render " + json.dumps(report["render"]), flush=True)
    bpy.ops.wm.quit_blender()


def scheduled_main():
    try:
        main(PENDING_ARGS)
    except Exception:
        with LOG_PATH.open("a", encoding="utf-8") if LOG_PATH else sys.stderr as stream:
            traceback.print_exc(file=stream)
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.1)
    return None


if __name__ == "__main__":
    PENDING_ARGS = arguments()
    OUTPUT_DIR = PENDING_ARGS.output_dir.resolve()
    REPORT_PATH = OUTPUT_DIR / "Chromoxel_TripoTest_V090_Four_Models.json"
    LOG_PATH = OUTPUT_DIR / "Chromoxel_TripoTest_V090_Render.log"
    bpy.app.timers.register(scheduled_main, first_interval=1.0)
