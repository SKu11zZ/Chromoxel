"""Render three Mixamo character comparisons through the Chromoxel 0.8 CLI API."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
import traceback

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer
from voxelizer import cli, core, editable, meshing


OUTPUT_DIR = ROOT.parents[1] / "mixamo_voxel_showcase_v080"
PROJECT_PATH = OUTPUT_DIR / "Chromoxel_Mixamo_CLI_Levels.blend"
REPORT_PATH = OUTPUT_DIR / "Chromoxel_Mixamo_CLI_Levels.json"
CHARACTERS = ("CH14", "CH15", "CH46")
TARGETS = (2_000, 20_000, 100_000)
POSITIONS = (-6.0, -2.0, 2.0, 6.0)
CALIBRATED_SIZES = {
    "SRC_CH14": (0.1128191, 0.0363549, 0.0164019),
    "SRC_CH15": (0.09210, 0.02952, 0.01357),
    "SRC_CH46": (0.08370, 0.02720, 0.01218),
}


def remove_object(obj):
    data = obj.data if obj.type in {"MESH", "CURVE", "FONT", "CAMERA", "LIGHT"} else None
    object_type = obj.type
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if object_type == "MESH":
            bpy.data.meshes.remove(data)
        elif object_type in {"CURVE", "FONT"}:
            bpy.data.curves.remove(data)
        elif object_type == "CAMERA":
            bpy.data.cameras.remove(data)
        elif object_type == "LIGHT":
            bpy.data.lights.remove(data)


def clean_to_sources():
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and obj.name.startswith("SRC_CH"):
            obj.hide_render = True
            obj.hide_set(True)
            continue
        remove_object(obj)
    for collection in list(bpy.data.collections):
        if collection.name == "Collection" or collection.name.startswith("Chromoxel Sources"):
            continue
        if collection.users == 0 or not collection.objects:
            bpy.data.collections.remove(collection)


def make_collection(name):
    result = bpy.data.collections.get(name)
    if result is None:
        result = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(result)
    return result


def move_to_collection(obj, target):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    target.objects.link(obj)


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def material(name, color, roughness=0.45, metallic=0.0, emission=0.0):
    result = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    result.use_nodes = True
    principled = result.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    if "Emission Color" in principled.inputs:
        principled.inputs["Emission Color"].default_value = color
    elif "Emission" in principled.inputs:
        principled.inputs["Emission"].default_value = color
    if "Emission Strength" in principled.inputs:
        principled.inputs["Emission Strength"].default_value = emission
    return result


def add_text(body, location, size, text_material, collection, name):
    curve = bpy.data.curves.new(name + "_Curve", "FONT")
    curve.body = body
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = size
    curve.extrude = 0.006
    curve.bevel_depth = 0.002
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler.x = math.radians(90.0)
    obj.data.materials.append(text_material)
    return obj


def area_light(name, location, energy, color, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.color = color
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    point_at(obj, (0.0, 0.0, 1.7))


def configure_cycles():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 48
    scene.cycles.use_denoising = True
    scene.cycles.use_preview_denoising = True
    scene.cycles.max_bounces = 5
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 2
    scene.cycles.transparent_max_bounces = 2
    scene.render.use_simplify = True
    scene.render.resolution_x = 2560
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    selected_backend = "CPU"
    preferences = bpy.context.preferences.addons.get("cycles")
    if preferences is not None:
        cycles_preferences = preferences.preferences
        for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
            try:
                cycles_preferences.compute_device_type = backend
                cycles_preferences.get_devices()
                enabled = 0
                for device in cycles_preferences.devices:
                    device.use = device.type != "CPU"
                    enabled += int(device.use)
                if enabled:
                    scene.cycles.device = "GPU"
                    selected_backend = backend
                    break
            except (TypeError, RuntimeError):
                continue
    return selected_backend


def configure_world_and_stage():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("Chromoxel Warm Gradient World")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.3
    texcoord = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.22
    ramp.color_ramp.elements[0].color = (0.015, 0.025, 0.05, 1.0)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.7, 0.23, 0.025, 1.0)
    links.new(texcoord.outputs["Normal"], separate.inputs["Vector"])
    links.new(separate.outputs["Z"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=30.0, location=(0.0, 0.0, -0.025))
    floor = bpy.context.object
    floor.name = "Chromoxel CLI Stage"
    floor.data.materials.append(material("Stage Material", (0.025, 0.04, 0.07, 1.0), 0.28, 0.18))
    area_light("Warm Key", (-6.0, -6.0, 7.5), 1250.0, (1.0, 0.67, 0.38), 5.5)
    area_light("Cool Fill", (6.0, -4.0, 5.0), 900.0, (0.36, 0.62, 1.0), 5.0)
    area_light("Warm Rim", (0.0, 4.0, 7.0), 1450.0, (1.0, 0.46, 0.18), 4.0)

    camera_data = bpy.data.cameras.new("Chromoxel CLI Camera")
    camera = bpy.data.objects.new("Chromoxel CLI Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = "ORTHO"
    # Blender 5.1 treats this as the horizontal orthographic span in this
    # wide-frame setup; 16 BU contains four 3.4-BU T-posed columns.
    camera.data.ortho_scale = 16.0
    camera.location = (0.0, -18.0, 2.35)
    point_at(camera, (0.0, 0.0, 1.9))

    scene.use_nodes = True
    compositor = getattr(scene, "node_tree", None)
    if compositor is None:
        # Blender 5.1 exposes the new compositor node-group API without the
        # legacy Composite output node. Emissive labels retain the restrained
        # glow cue while the render remains portable between 5.1 builds.
        return
    compositor.nodes.clear()
    render_layers = compositor.nodes.new("CompositorNodeRLayers")
    glare = compositor.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    glare.threshold = 1.0
    glare.size = 6
    glare.mix = -0.92
    composite = compositor.nodes.new("CompositorNodeComposite")
    compositor.links.new(render_layers.outputs["Image"], glare.inputs["Image"])
    compositor.links.new(glare.outputs["Image"], composite.inputs["Image"])


def fit_levels(source, settings):
    results = []
    calibrated = CALIBRATED_SIZES[source.name]
    cli.configure_settings(
        settings,
        voxel_size=calibrated[0],
        sampling_mode="UNIFORM",
        detail_level=0,
        max_voxels=editable.MODEL_POINT_LIMIT,
        compute_backend="AUTO",
    )
    prepared = time.perf_counter()
    with core.sampling_session(bpy.context, source, settings) as session:
        prepare_seconds = time.perf_counter() - prepared
        print(
            "CHROMOXEL_SESSION",
            source.name,
            f"seconds={prepare_seconds:.3f}",
            session.timings,
            flush=True,
        )
        for target, initial_size in zip(TARGETS, calibrated):
            desired = target * 0.98
            lower = target * 0.95
            voxel_size = initial_size
            sample = None
            attempts = []
            for iteration in range(1, 4):
                cli.configure_settings(
                    settings,
                    voxel_size=voxel_size,
                    sampling_mode="UNIFORM",
                    detail_level=0,
                    max_voxels=editable.MODEL_POINT_LIMIT,
                    compute_backend="AUTO",
                )
                cli._select_only(source)
                started = time.perf_counter()
                try:
                    candidate = core.sample_surface_voxels(
                        bpy.context,
                        source,
                        settings,
                        use_cache=False,
                        session=session,
                        occupancy_only=True,
                    )
                except core.VoxelizerError as exc:
                    attempts.append({
                        "iteration": iteration,
                        "voxel_size": voxel_size,
                        "voxels": None,
                        "seconds": round(time.perf_counter() - started, 4),
                        "phase": "OCCUPANCY_FIT",
                        "error": str(exc),
                    })
                    voxel_size *= 1.025
                    continue
                attempts.append({
                    "iteration": iteration,
                    "voxel_size": voxel_size,
                    "voxels": candidate.count,
                    "seconds": round(time.perf_counter() - started, 4),
                    "phase": "OCCUPANCY_FIT",
                })
                if lower <= candidate.count <= target:
                    started = time.perf_counter()
                    sample = core.sample_surface_voxels(
                        bpy.context,
                        source,
                        settings,
                        use_cache=True,
                        session=session,
                    )
                    attempts[-1]["finalize_seconds"] = round(
                        time.perf_counter() - started,
                        4,
                    )
                    break
                voxel_size *= math.sqrt(max(1, candidate.count) / desired)
                voxel_size *= 1.004 if candidate.count > target else 0.998
            if sample is None:
                raise RuntimeError(f"{source.name} target {target:,} failed 5% fit: {attempts}")
            unique_sizes = {round(float(value), 9) for value in sample.sizes}
            unique_extents = {
                tuple(round(float(axis), 9) for axis in value)
                for value in sample.extents
            }
            if len(unique_sizes) != 1 or len(unique_extents) != 1:
                raise RuntimeError(f"Uniform size validation failed for {source.name}: {unique_sizes}")
            results.append((target, sample, voxel_size, attempts))
            print(
                "CHROMOXEL_LEVEL",
                source.name,
                f"target={target}",
                f"actual={sample.count}",
                f"size={voxel_size:.7f}",
                flush=True,
            )
    return results


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    voxelizer.register()
    clean_to_sources()
    backend = configure_cycles()
    configure_world_and_stage()
    shared = make_collection("Chromoxel CLI Shared")
    floor = bpy.data.objects.get("Chromoxel CLI Stage")
    if floor is not None:
        move_to_collection(floor, shared)
    text_material = material("CLI Label Emission", (0.72, 0.96, 1.0, 1.0), 0.3, 0.0, 3.5)
    settings = bpy.context.scene.voxelizer_settings
    settings["chromoxel_cli_repair_voxel_size"] = 0.06
    character_groups = {}
    report_characters = []

    for character in CHARACTERS:
        source = bpy.data.objects.get(f"SRC_{character}")
        if source is None:
            raise RuntimeError(f"Missing normalized source SRC_{character}")
        source.hide_set(False)
        source.hide_render = True
        group = make_collection(f"CLI_{character}")
        character_groups[character] = group
        original = source.copy()
        original.data = source.data.copy()
        original.name = f"{character}_ORIGINAL"
        group.objects.link(original)
        original.location.x = POSITIONS[0]
        original.hide_render = False
        levels = fit_levels(source, settings)
        level_records = []
        objects = [original]
        for index, (target, sample, voxel_size, attempts) in enumerate(levels, start=1):
            output = cli.create_editable_output(
                bpy.context,
                source,
                sample,
                voxel_size,
                name=f"{character}_{target:06d}_EDITABLE",
            )
            move_to_collection(output, group)
            output.location.x = POSITIONS[index]
            output["chromoxel_target_voxels"] = target
            output["chromoxel_uniform_size_verified"] = True
            objects.append(output)
            level_records.append({
                "target_voxels": target,
                "actual_voxels": sample.count,
                "voxel_size_bu": round(voxel_size, 8),
                "uniform_size_verified": True,
                "used_image": sample.used_image,
                "attempts": attempts,
            })
        labels = (
            "ORIGINAL",
            f"~2,000 VOXELS\n{levels[0][1].count:,}",
            f"~20,000 VOXELS\n{levels[1][1].count:,}",
            f"~100,000 UNIFORM\n{levels[2][1].count:,}  |  {levels[2][2]:.5f} BU",
        )
        for index, label in enumerate(labels):
            objects.append(add_text(label, (POSITIONS[index], -0.7, 3.72), 0.22, text_material, group, f"{character}_Label_{index}"))
        objects.append(add_text(
            f"{character}  —  CHROMOXEL 0.8 / GPU-AUTO / UNIFORM VOXEL LEVELS",
            (0.0, -0.72, 4.18),
            0.3,
            text_material,
            group,
            f"{character}_Title",
        ))
        source.hide_set(True)
        source.hide_render = True
        report_characters.append({
            "character": character,
            "source": source.get("chromoxel_showcase_source", source.name),
            "levels": level_records,
            "render": str(OUTPUT_DIR / f"{character}_Original_2K_20K_100K.png"),
        })

    # Render one horizontal comparison per character.
    for character in CHARACTERS:
        for other, group in character_groups.items():
            for obj in group.objects:
                obj.hide_render = other != character
        # Cycles does not consistently expose POINT colour attributes inside
        # non-realized GN instances. Render the official Bake result, then
        # discard the temporary meshes; the saved project retains editable
        # point carriers for authoring.
        realized = []
        for point_object in sorted(
            (
                obj
                for obj in character_groups[character].objects
                if obj.name.endswith("_EDITABLE")
            ),
            key=lambda obj: obj.name,
        ):
            mesh, _count = meshing.build_from_editable(
                point_object,
                "REALIZED",
                point_object.name + "_RENDER_MESH",
            )
            render_object = bpy.data.objects.new(point_object.name + "_RENDER", mesh)
            character_groups[character].objects.link(render_object)
            render_object.location = point_object.location
            realized.append(render_object)
            point_object.hide_render = True
        render_path = OUTPUT_DIR / f"{character}_Original_2K_20K_100K.png"
        bpy.context.scene.render.filepath = str(render_path)
        started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        elapsed = time.perf_counter() - started
        next(item for item in report_characters if item["character"] == character)["render_seconds"] = round(elapsed, 3)
        print("CHROMOXEL_RENDER", character, f"seconds={elapsed:.3f}", flush=True)
        for render_object in realized:
            mesh = render_object.data
            bpy.data.objects.remove(render_object, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)

    # Leave CH14 visible on file open; all collections and variants remain in
    # the one packed project for inspection.
    for character, group in character_groups.items():
        for obj in group.objects:
            obj.hide_render = (
                character != CHARACTERS[0]
                if not obj.name.endswith("_EDITABLE")
                else True
            )
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(PROJECT_PATH), compress=True)
    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "chromoxel": "0.8.0",
        "pipeline": "CLI API / UNIFORM / Geometry Nodes point instances / Cycles",
        "cycles_backend": backend,
        "project": str(PROJECT_PATH),
        "characters": report_characters,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("PASS chromoxel_mixamo_cli_levels", flush=True)
    print(json.dumps(report, ensure_ascii=False), flush=True)


def _run_interactive() -> None:
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    if bpy.app.background:
        main()
    else:
        bpy.app.timers.register(_run_interactive, first_interval=0.5)
