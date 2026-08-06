"""Render a four-panel Chromoxel version/detail KayKit range comparison.

Open the prepared training-range blend before running this script. The blend
contains the original scene, archived v0.3 uniform Preview outputs, and hidden
KayKit sources. Chromoxel 0.6 is evaluated from this repository for the lower
uniform and texture-adaptive panels.

Example:
    blender --background scene_01_training_room.blend \
      --python tools/render_training_range_version_comparison.py
    powershell -File tools/overlay_training_range_labels.ps1
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import bpy
import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "images"
    / "chromoxel-training-range-old-vs-adaptive.png"
)
PANEL_SIZE = (960, 540)
COMPARISON_SIZE = (1920, 1080)
BASE_VOXEL_SIZE = 0.16
MAX_DETAIL_LEVEL = 2


def load_repository_core():
    core_path = REPOSITORY_ROOT / "voxelizer" / "core.py"
    spec = importlib.util.spec_from_file_location(
        "chromoxel_v060_render_core",
        core_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Chromoxel core: {core_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configure_gpu(scene):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"
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
    scene.render.resolution_x = PANEL_SIZE[0]
    scene.render.resolution_y = PANEL_SIZE[1]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.render.use_persistent_data = False
    return backend


def set_output_visibility(objects, visible):
    for obj in objects:
        obj.hide_render = not visible
        obj.hide_viewport = not visible
        obj.hide_set(not visible)


def build_v060_outputs(scene, core, *, mode, max_level, suffix):
    texture = bpy.data.images.get("prototypebits_texture")
    if texture is None:
        raise RuntimeError("The prepared range is missing prototypebits_texture.")
    settings = SimpleNamespace(
        sampling_mode=mode,
        adaptive_max_level=max_level,
        adaptive_texture_threshold=0.12,
        adaptive_geometry_angle=35.0,
        adaptive_geometry_max_level=1,
        voxel_size=BASE_VOXEL_SIZE,
        cube_gap=BASE_VOXEL_SIZE * 0.10,
        grid_origin_mode="OBJECT",
        custom_grid_origin=(0.0, 0.0, 0.0),
        auto_watertight_copy=True,
        repair_voxel_size=0.08,
        auto_material_images=True,
        base_color_image=texture,
        fallback_color=(0.18, 0.48, 0.80, 1.0),
        uv_map="",
        texture_filter="BILINEAR",
        use_sparse_candidates=True,
        sparse_grid_threshold=0,
        sample_budget=1_500_000,
        candidate_expansion_budget=48_000_000,
        voxel_budget=250_000,
        sampling_chunk_size=4096,
        cache_memory_mb=128,
    )
    core.clear_sampling_cache()

    collection = bpy.data.collections.new(f"COL_V060_{suffix}_OUTPUT")
    scene.collection.children.link(collection)
    root = bpy.data.objects.new(f"ROOT_V060_{suffix}", None)
    collection.objects.link(root)

    sources = sorted(
        (
            obj
            for obj in scene.objects
            if obj.type == "MESH"
            and obj.get("validation_role") == "hidden_voxel_source"
        ),
        key=lambda obj: obj.name,
    )
    if not sources:
        raise RuntimeError("No hidden voxel sources were found in the prepared range.")

    cache = {}
    outputs = []
    records = []
    total_voxels = 0
    for index, source in enumerate(sources, start=1):
        uv_layer = source.data.uv_layers.active if source.data.uv_layers else None
        settings.uv_map = uv_layer.name if uv_layer else ""
        cache_key = (
            str(source.get("kaykit_asset", source.name)),
            str(source.get("kaykit_mesh_part", source.data.name)),
        )
        started = time.perf_counter()
        cached = cache.get(cache_key)
        if cached is None:
            mesh, count, used_image = core.build_voxel_mesh(
                bpy.context,
                source,
                settings,
                f"V060_{suffix}_{index:03d}_Mesh",
            )
            cache[cache_key] = (mesh, count, used_image)
            reused = False
        else:
            mesh, count, used_image = cached
            reused = True
        output = bpy.data.objects.new(f"V060_{suffix}_{index:03d}", mesh)
        collection.objects.link(output)
        output.parent = root
        # The prepared hidden sources deliberately live outside the active
        # view-layer hierarchy. In Blender background mode their matrix_world
        # can remain an unevaluated identity, while matrix_basis retains the
        # authored scene transform. The hidden-source root is identity, so the
        # basis is the correct world transform for the detached output.
        output.matrix_world = source.matrix_basis.copy()
        output.hide_render = False
        output["validation_role"] = f"chromoxel_v060_{suffix.lower()}_bake"
        output["source_object"] = source.name
        outputs.append(output)
        total_voxels += int(count)
        records.append({
            "source": source.name,
            "asset": cache_key[0],
            "part": cache_key[1],
            "voxels": int(count),
            "used_image": bool(used_image),
            "mesh_reused": reused,
            "seconds": round(time.perf_counter() - started, 4),
        })
        print(
            f"{suffix} {index:02d}/{len(sources):02d}",
            source.name,
            f"{count:,} voxels",
            "cached" if reused else "built",
        )
    return collection, outputs, records, total_voxels


def render_panel(scene, path):
    scene.render.filepath = str(path)
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - started
    if not path.exists():
        raise RuntimeError(f"Cycles did not produce {path}")
    return elapsed


def compose_grid(original_path, old_path, uniform_path, adaptive_path, output_path):
    images = [
        bpy.data.images.load(str(path), check_existing=False)
        for path in (original_path, old_path, uniform_path, adaptive_path)
    ]
    try:
        if any(tuple(image.size) != PANEL_SIZE for image in images):
            raise RuntimeError(
                f"Unexpected panel sizes: {[tuple(image.size) for image in images]}"
            )
        width, height = PANEL_SIZE
        panels = []
        for image in images:
            values = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(values)
            panels.append(values.reshape((height, width, 4)))
        pixels = np.empty((COMPARISON_SIZE[1], COMPARISON_SIZE[0], 4), dtype=np.float32)
        # Blender image rows start at the bottom: lower pair first, upper pair second.
        pixels[height:, :width, :] = panels[0]
        pixels[height:, width:, :] = panels[1]
        pixels[:height, :width, :] = panels[2]
        pixels[:height, width:, :] = panels[3]
        pixels[:, width - 3 : width + 3, :3] = 0.012
        pixels[:, width - 3 : width + 3, 3] = 1.0
        pixels[height - 3 : height + 3, :, :3] = 0.012
        pixels[height - 3 : height + 3, :, 3] = 1.0
        output = bpy.data.images.new(
            "Chromoxel_Training_Range_Version_Comparison",
            width=COMPARISON_SIZE[0],
            height=COMPARISON_SIZE[1],
            alpha=True,
        )
        try:
            output.colorspace_settings.name = "sRGB"
            output.pixels.foreach_set(pixels.reshape(-1))
            output.filepath_raw = str(output_path)
            output.file_format = "PNG"
            output.save()
        finally:
            bpy.data.images.remove(output)
    finally:
        for image in images:
            bpy.data.images.remove(image)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("The prepared training range has no active camera.")
    core = load_repository_core()
    backend = configure_gpu(scene)
    original_collection = bpy.data.collections.get("COL_ORIGINAL")
    old_collection = bpy.data.collections.get("COL_VOXEL_OUTPUT")
    if original_collection is None or old_collection is None:
        raise RuntimeError("This is not the prepared KayKit training-range blend.")
    old_outputs = [
        obj
        for obj in scene.objects
        if obj.get("validation_role") in {
            "actual_installed_voxelizer_preview",
            "cached_actual_preview_instance",
        }
    ]
    if len(old_outputs) != 27:
        raise RuntimeError(f"Expected 27 archived old outputs, found {len(old_outputs)}")
    uniform_collection, uniform_outputs, uniform_records, uniform_voxels = build_v060_outputs(
        scene,
        core,
        mode="UNIFORM",
        max_level=0,
        suffix="UNIFORM",
    )
    adaptive_collection, adaptive_outputs, adaptive_records, adaptive_voxels = build_v060_outputs(
        scene,
        core,
        mode="ADAPTIVE",
        max_level=MAX_DETAIL_LEVEL,
        suffix="ADAPTIVE",
    )

    all_labels = [obj for obj in scene.objects if obj.type == "FONT"]
    original_meshes = [
        obj
        for obj in scene.objects
        if obj.type == "MESH"
        and obj.get("validation_role") == "original_kaykit_mesh"
    ]
    if len(original_meshes) != 27:
        raise RuntimeError(
            f"Expected 27 original KayKit meshes, found {len(original_meshes)}"
        )
    set_output_visibility(original_meshes, False)
    set_output_visibility(old_outputs, False)
    set_output_visibility(uniform_outputs, False)
    set_output_visibility(adaptive_outputs, False)
    for label in all_labels:
        label.hide_render = True
    old_collection.hide_render = True
    uniform_collection.hide_render = True
    adaptive_collection.hide_render = True

    temporary = Path(bpy.app.tempdir) / "chromoxel_training_range_v060"
    temporary.mkdir(parents=True, exist_ok=True)
    original_path = temporary / "original.png"
    old_path = temporary / "old_uniform.png"
    uniform_path = temporary / "new_uniform.png"
    adaptive_path = temporary / "new_adaptive.png"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    original_collection.hide_render = False
    set_output_visibility(original_meshes, True)
    original_seconds = render_panel(scene, original_path)

    set_output_visibility(original_meshes, False)
    original_collection.hide_render = True
    old_collection.hide_render = False
    set_output_visibility(old_outputs, True)
    old_seconds = render_panel(scene, old_path)
    set_output_visibility(old_outputs, False)
    old_collection.hide_render = True

    uniform_collection.hide_render = False
    set_output_visibility(uniform_outputs, True)
    uniform_seconds = render_panel(scene, uniform_path)
    set_output_visibility(uniform_outputs, False)
    uniform_collection.hide_render = True

    adaptive_collection.hide_render = False
    set_output_visibility(adaptive_outputs, True)
    adaptive_seconds = render_panel(scene, adaptive_path)
    compose_grid(
        original_path,
        old_path,
        uniform_path,
        adaptive_path,
        OUTPUT_PATH,
    )

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "cycles_backend": backend,
        "source_blend": Path(bpy.data.filepath).name,
        "output": str(OUTPUT_PATH),
        "sha256": sha256(OUTPUT_PATH),
        "dimensions": list(COMPARISON_SIZE),
        "original": {
            "render_seconds": round(original_seconds, 3),
        },
        "old": {
            "version": "0.3.1",
            "mode": "UNIFORM",
            "voxel_size": BASE_VOXEL_SIZE,
            "outputs": len(old_outputs),
            "render_seconds": round(old_seconds, 3),
        },
        "new_uniform": {
            "version": "0.6.0",
            "mode": "UNIFORM",
            "voxel_size": BASE_VOXEL_SIZE,
            "outputs": len(uniform_outputs),
            "total_voxels_with_instances": uniform_voxels,
            "render_seconds": round(uniform_seconds, 3),
            "sources": uniform_records,
        },
        "new_adaptive": {
            "version": "0.6.0",
            "mode": "ADAPTIVE",
            "base_voxel_size": BASE_VOXEL_SIZE,
            "minimum_voxel_size": BASE_VOXEL_SIZE / (2 ** MAX_DETAIL_LEVEL),
            "outputs": len(adaptive_outputs),
            "total_voxels_with_instances": adaptive_voxels,
            "render_seconds": round(adaptive_seconds, 3),
            "sources": adaptive_records,
        },
    }
    print("PASS chromoxel_training_range_version_comparison")
    print(json.dumps(report, indent=2, sort_keys=True))


main()
