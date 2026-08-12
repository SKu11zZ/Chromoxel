"""Blender command-line workflow for Chromoxel 0.9.

Invoke through Blender, not the system Python interpreter.  The public wrapper
is ``tools/chromoxel_cli.py``; arguments after Blender's ``--`` are parsed here.
"""

from __future__ import annotations

import argparse
import json
import math
from array import array
from pathlib import Path
import sys
import time
from typing import Sequence

import bpy
from mathutils import Matrix, Vector

from . import core, editable, meshing, preview, vox_io


class CLIError(RuntimeError):
    """Raised for invalid CLI input or a failed target fit."""


def _select_only(obj: bpy.types.Object) -> None:
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_render = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _remove_object(obj: bpy.types.Object) -> None:
    data = obj.data if obj.type in {"MESH", "ARMATURE"} else None
    object_type = obj.type
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if object_type == "MESH":
            bpy.data.meshes.remove(data)
        elif object_type == "ARMATURE":
            bpy.data.armatures.remove(data)


def import_input(filepath: str) -> list[bpy.types.Object]:
    """Open/import a supported scene and return imported mesh objects."""

    path = Path(filepath).resolve()
    if not path.exists():
        raise CLIError(f"Input does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
        return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = set(bpy.data.objects)
    if suffix == ".fbx":
        result = bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
    elif suffix in {".glb", ".gltf"}:
        result = bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".obj":
        result = bpy.ops.wm.obj_import(filepath=str(path))
    elif suffix == ".vox":
        output, _report = vox_io.import_vox(
            bpy.context,
            str(path),
            float(bpy.context.scene.voxelizer_settings.vox_import_size),
        )
        return [output]
    else:
        raise CLIError(f"Unsupported input format: {suffix}")
    if result != {"FINISHED"}:
        raise CLIError(f"Import failed for {path}: {result}")
    return [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]


def join_evaluated_meshes(
    sources: Sequence[bpy.types.Object],
    *,
    name: str = "Chromoxel_CLI_Source",
    normalize_height: float = 0.0,
) -> bpy.types.Object:
    """Freeze evaluated meshes, preserve material slots/UVs, and join them."""

    if not sources:
        raise CLIError("No mesh source was found.")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    static_objects = []
    target_collection = bpy.context.scene.collection
    for index, source in enumerate(sources):
        evaluated = source.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        static = bpy.data.objects.new(f"{name}_{index:02d}", mesh)
        target_collection.objects.link(static)
        static.matrix_world = source.matrix_world.copy()
        if not mesh.materials:
            for material in source.data.materials:
                mesh.materials.append(material)
        static_objects.append(static)

    _select_only(static_objects[0])
    for obj in static_objects[1:]:
        obj.select_set(True)
    if len(static_objects) > 1:
        bpy.ops.object.join()
    result = bpy.context.view_layer.objects.active
    result.name = name
    result.data.transform(result.matrix_world)
    result.matrix_world = Matrix.Identity(4)
    if normalize_height > 0.0 and result.data.vertices:
        values = [vertex.co.copy() for vertex in result.data.vertices]
        minimum = Vector(tuple(min(value[axis] for value in values) for axis in range(3)))
        maximum = Vector(tuple(max(value[axis] for value in values) for axis in range(3)))
        height = max(1.0e-9, float(maximum.z - minimum.z))
        result.data.transform(Matrix.Scale(float(normalize_height) / height, 4))
        values = [vertex.co.copy() for vertex in result.data.vertices]
        minimum = Vector(tuple(min(value[axis] for value in values) for axis in range(3)))
        maximum = Vector(tuple(max(value[axis] for value in values) for axis in range(3)))
        result.data.transform(
            Matrix.Translation((
                -(float(minimum.x) + float(maximum.x)) * 0.5,
                -(float(minimum.y) + float(maximum.y)) * 0.5,
                -float(minimum.z),
            ))
        )
    result.data.update()
    return result


def configure_settings(
    settings,
    *,
    voxel_size: float,
    sampling_mode: str,
    detail_level: int,
    max_voxels: int = editable.MODEL_POINT_LIMIT,
    compute_backend: str = "AUTO",
    gpu_batch_size: int = 65_536,
    gpu_memory_limit_mb: int = 512,
) -> None:
    settings.source_scope = "ACTIVE"
    settings.sampling_mode = sampling_mode
    settings.adaptive_max_level = detail_level
    settings.adaptive_geometry_max_level = min(1, detail_level)
    settings.voxel_size = voxel_size
    settings.cube_gap = voxel_size * 0.06
    settings.grid_origin_mode = "OBJECT"
    settings.auto_watertight_copy = True
    repair_override = 0.0
    try:
        repair_override = float(settings.get("chromoxel_cli_repair_voxel_size", 0.0))
    except (AttributeError, TypeError, ValueError):
        pass
    settings.repair_voxel_size = (
        repair_override if repair_override > 0.0 else max(0.002, voxel_size * 0.5)
    )
    settings.auto_material_images = True
    settings.texture_filter = "BILINEAR"
    settings.compute_backend = str(compute_backend).upper()
    settings.gpu_batch_size = max(1_024, min(1_000_000, int(gpu_batch_size)))
    settings.gpu_memory_limit_mb = max(64, min(8192, int(gpu_memory_limit_mb)))
    settings.use_sparse_candidates = True
    # Coarse character grids are often cheaper to scan directly than to expand
    # every triangle AABB into a Python set.  Fine grids still switch to Sparse.
    settings.sparse_grid_threshold = 250_000
    settings.sample_budget = max(1_500_000, min(100_000_000, max_voxels * 32))
    settings.candidate_expansion_budget = max(48_000_000, min(1_000_000_000, max_voxels * 512))
    settings.voxel_budget = min(editable.MODEL_POINT_LIMIT, max_voxels)
    settings.sampling_chunk_size = 65_536


def _surface_area(context, source) -> float:
    with core.evaluated_local_mesh(context, source) as mesh:
        return sum(float(polygon.area) for polygon in mesh.polygons)


def fit_target_voxels(
    context,
    source: bpy.types.Object,
    settings,
    target_voxels: int,
    *,
    sampling_mode: str = "UNIFORM",
    detail_level: int = 0,
    tolerance: float = 0.08,
    max_iterations: int = 6,
    initial_size: float | None = None,
    compute_backend: str = "AUTO",
    gpu_batch_size: int = 65_536,
    gpu_memory_limit_mb: int = 512,
) -> tuple[core.VoxelSampleResult, float, list[dict[str, object]]]:
    """Fit a uniform/adaptive grid into ``[(1-tol)*target, target]``."""

    target_voxels = int(target_voxels)
    if target_voxels < 1 or target_voxels > editable.MODEL_POINT_LIMIT:
        raise CLIError(f"Target voxels must be between 1 and {editable.MODEL_POINT_LIMIT:,}.")
    tolerance = max(0.01, min(0.45, float(tolerance)))
    desired = target_voxels * (1.0 - tolerance * 0.45)
    area = max(1.0e-9, _surface_area(context, source))
    # A conservative shell-coverage factor accounts for edge/corner cells and
    # avoids beginning target fits with a large over-budget sample.
    size = float(initial_size or math.sqrt(area * 1.65 / max(1.0, desired)))
    if sampling_mode == "ADAPTIVE":
        size *= 2.0 ** max(0, detail_level) * 0.72
    attempts = []
    best_size = None
    best_count = None
    best_error = float("inf")
    dense_size = None
    sparse_size = None
    lower_bound = int(math.floor(target_voxels * (1.0 - tolerance)))
    configure_settings(
        settings,
        voxel_size=size,
        sampling_mode=sampling_mode,
        detail_level=detail_level,
        max_voxels=editable.MODEL_POINT_LIMIT,
        compute_backend=compute_backend,
        gpu_batch_size=gpu_batch_size,
        gpu_memory_limit_mb=gpu_memory_limit_mb,
    )
    fixed_repair_size = float(settings.repair_voxel_size)
    occupancy_fit = sampling_mode == "UNIFORM"
    with core.sampling_session(context, source, settings) as session:
        for iteration in range(1, max_iterations + 1):
            configure_settings(
                settings,
                voxel_size=size,
                sampling_mode=sampling_mode,
                detail_level=detail_level,
                # Keep the hard per-model ceiling while allowing the solver to
                # observe overshoot for targets below 100k.
                max_voxels=editable.MODEL_POINT_LIMIT,
                compute_backend=compute_backend,
                gpu_batch_size=gpu_batch_size,
                gpu_memory_limit_mb=gpu_memory_limit_mb,
            )
            settings.repair_voxel_size = fixed_repair_size
            _select_only(source)
            started = time.perf_counter()
            try:
                candidate = core.sample_surface_voxels(
                    context,
                    source,
                    settings,
                    use_cache=not occupancy_fit,
                    session=session,
                    occupancy_only=occupancy_fit,
                )
            except core.VoxelizerError as exc:
                attempts.append({
                    "iteration": iteration,
                    "voxel_size": size,
                    "voxels": None,
                    "seconds": round(time.perf_counter() - started, 4),
                    "error": str(exc),
                })
                size *= 1.04
                continue
            count = int(candidate.count)
            elapsed = time.perf_counter() - started
            attempts.append({
                "iteration": iteration,
                "voxel_size": size,
                "voxels": count,
                "seconds": round(elapsed, 4),
                "session_reused": True,
                "phase": "OCCUPANCY_FIT" if occupancy_fit else "FULL_SAMPLE",
            })
            error = abs(count - desired)
            if count <= target_voxels and error < best_error:
                best_size = float(size)
                best_count = count
                best_error = error
            if lower_bound <= count <= target_voxels:
                if occupancy_fit:
                    started = time.perf_counter()
                    sample = core.sample_surface_voxels(
                        context,
                        source,
                        settings,
                        use_cache=True,
                        session=session,
                    )
                    attempts[-1]["finalize_seconds"] = round(
                        time.perf_counter() - started,
                        4,
                    )
                    attempts[-1]["final_voxels"] = sample.count
                    if sample.count != count:
                        raise CLIError(
                            "Occupancy fit and final texture sample produced different counts."
                        )
                    return sample, size, attempts
                return candidate, size, attempts

            if count > target_voxels:
                dense_size = max(float(size), dense_size or float("-inf"))
            elif count < lower_bound:
                sparse_size = min(float(size), sparse_size or float("inf"))

            if dense_size is not None and sparse_size is not None:
                if dense_size >= sparse_size:
                    raise CLIError(
                        "Target fitting produced a non-monotonic size bracket: "
                        f"dense={dense_size:.9g}, sparse={sparse_size:.9g}; "
                        f"attempts={attempts}"
                    )
                next_size = math.sqrt(dense_size * sparse_size)
            else:
                next_size = size * math.sqrt(max(1, count) / max(1.0, desired))
                next_size *= 1.018 if count > target_voxels else 0.994
            if abs(next_size - size) <= max(1.0e-12, abs(size) * 1.0e-9):
                break
            size = next_size

    best_text = (
        "none"
        if best_size is None or best_count is None
        else f"{best_count:,} voxels at size {best_size:.9g}"
    )
    raise CLIError(
        f"Could not fit {lower_bound:,}-{target_voxels:,} voxels within "
        f"{max_iterations} iteration(s); best under target was {best_text}. "
        f"No out-of-tolerance output was created. Attempts: {attempts}"
    )


def create_editable_output(
    context,
    source: bpy.types.Object,
    sample: core.VoxelSampleResult,
    voxel_size: float,
    *,
    name: str,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "_Carrier")
    output = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(output)
    preview.configure_preview(
        output,
        sample.centres,
        sample.colours,
        sample.sizes,
        sample.extents,
        sample.levels,
        0.94,
        core.ensure_colour_material(),
    )
    output[editable.GRID_SIZE_TAG] = min(sample.sizes or [voxel_size])
    output[editable.GRID_ORIGIN_TAG] = (0.0, 0.0, 0.0)
    editable.initialize_carrier(
        output,
        reset_delta=True,
        coordinate_ordered=True,
    )
    uv_attribute = output.data.attributes.get(editable.SOURCE_UV_ATTRIBUTE)
    if uv_attribute is not None and sample.source_uvs:
        uv_attribute.data.foreach_set(
            "vector",
            array("f", (component for uv in sample.source_uvs for component in uv)),
        )
    core.tag_output(output, source, core.PREVIEW_KIND)
    output["chromoxel_cli"] = True
    output["chromoxel_cli_voxel_count"] = sample.count
    output["chromoxel_cli_voxel_size"] = voxel_size
    return output


def prune_editable_output(editable_output) -> dict[str, object]:
    records = editable.records_from_object(editable_output)
    filtered, stats = meshing.remove_enclosed_records(
        records,
        float(editable_output[editable.GRID_SIZE_TAG]),
        tuple(editable_output[editable.GRID_ORIGIN_TAG]),
    )
    if len(filtered) != len(records):
        editable.replace_records(editable_output, filtered)
    meshing.tag_filter_stats(editable_output.data, stats)
    return stats


def bake_output(
    editable_output,
    mode: str,
    name: str,
    *,
    remove_enclosed: bool = False,
):
    mode = mode.upper()
    if mode == "EDITABLE":
        if remove_enclosed:
            prune_editable_output(editable_output)
        return editable_output
    mesh, _count = meshing.build_from_editable(
        editable_output,
        mode,
        name + "_Mesh",
        remove_enclosed=remove_enclosed,
    )
    result = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(result)
    result.matrix_world = editable_output.matrix_world.copy()
    result.data.materials.append(core.ensure_colour_material())
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chromoxel", description="Chromoxel Blender CLI")
    parser.add_argument("--input", required=True, help=".blend, .fbx, .obj, .glb/.gltf, or .vox input")
    parser.add_argument("--output", required=True, help="Output .blend path")
    parser.add_argument("--source-object", default="", help="Mesh name for .blend inputs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--voxel-size", type=float)
    group.add_argument("--target-voxels", type=int)
    parser.add_argument("--sampling", choices=("uniform", "adaptive"), default="uniform")
    parser.add_argument("--detail-level", type=int, default=0)
    parser.add_argument("--bake-mode", choices=("editable", "realized", "surface", "greedy"), default="editable")
    parser.add_argument(
        "--remove-enclosed-voxels",
        action="store_true",
        help=(
            "Remove voxels whose six axis-aligned sides are completely covered "
            "from the chosen Bake output"
        ),
    )
    parser.add_argument("--normalize-height", type=float, default=0.0)
    parser.add_argument(
        "--repair-voxel-size",
        type=float,
        default=0.0,
        help="Fixed watertight occupancy proxy size reused while fitting targets",
    )
    parser.add_argument("--target-tolerance", type=float, default=0.08)
    parser.add_argument("--max-iterations", type=int, default=6)
    parser.add_argument(
        "--compute-backend",
        choices=("auto", "gpu", "cpu"),
        default="auto",
        help="GPU batch texture sampling is used only when a graphics context is available",
    )
    parser.add_argument("--gpu-batch-size", type=int, default=65_536)
    parser.add_argument(
        "--gpu-memory-limit-mb",
        type=int,
        default=512,
        help="Bound GPU source-texture plus temporary-buffer memory; oversized work falls back to CPU",
    )
    parser.add_argument("--export-vox", default="")
    parser.add_argument("--report", default="")
    return parser


def run(arguments: Sequence[str]) -> dict[str, object]:
    from . import register

    args = build_parser().parse_args(list(arguments))
    register()
    run_started = time.perf_counter()
    phase_timings: dict[str, float] = {}
    phase_started = time.perf_counter()
    imported = import_input(args.input)
    phase_timings["import"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    if args.source_object:
        source = bpy.data.objects.get(args.source_object)
        if source is None or source.type != "MESH":
            raise CLIError(f"Mesh source not found: {args.source_object}")
    elif editable.is_editable(imported[0]) if len(imported) == 1 else False:
        source = imported[0]
    else:
        source = join_evaluated_meshes(imported, normalize_height=args.normalize_height)
    phase_timings["source_join"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    if editable.is_editable(source):
        output = source
        sample_count = len(source.data.vertices)
        voxel_size = float(source[editable.GRID_SIZE_TAG])
        attempts = []
    else:
        settings = bpy.context.scene.voxelizer_settings
        if args.repair_voxel_size > 0.0:
            settings["chromoxel_cli_repair_voxel_size"] = args.repair_voxel_size
        if args.target_voxels:
            sample, voxel_size, attempts = fit_target_voxels(
                bpy.context,
                source,
                settings,
                args.target_voxels,
                sampling_mode=args.sampling.upper(),
                detail_level=args.detail_level,
                tolerance=args.target_tolerance,
                max_iterations=args.max_iterations,
                compute_backend=args.compute_backend.upper(),
                gpu_batch_size=args.gpu_batch_size,
                gpu_memory_limit_mb=args.gpu_memory_limit_mb,
            )
        else:
            voxel_size = float(args.voxel_size)
            configure_settings(
                settings,
                voxel_size=voxel_size,
                sampling_mode=args.sampling.upper(),
                detail_level=args.detail_level,
                compute_backend=args.compute_backend.upper(),
                gpu_batch_size=args.gpu_batch_size,
                gpu_memory_limit_mb=args.gpu_memory_limit_mb,
            )
            sample = core.sample_surface_voxels(bpy.context, source, settings, use_cache=True)
            attempts = []
        sample_count = sample.count
        phase_timings["sample"] = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        output = create_editable_output(
            bpy.context,
            source,
            sample,
            voxel_size,
            name="Chromoxel_CLI_Editable",
        )
    if "sample" not in phase_timings:
        phase_timings["sample"] = 0.0
    phase_timings["editable_carrier"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    final_output = bake_output(
        output,
        args.bake_mode,
        "Chromoxel_CLI_Output",
        remove_enclosed=args.remove_enclosed_voxels,
    )
    phase_timings["bake"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    _select_only(final_output)
    if args.export_vox:
        vox_io.export_vox(output, str(Path(args.export_vox).resolve()))
    phase_timings["export_vox"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path), compress=True)
    phase_timings["save"] = time.perf_counter() - phase_started
    phase_timings["total"] = time.perf_counter() - run_started
    filter_mesh = final_output.data
    sampling_report = core.sampling_diagnostics(source)
    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "input": str(Path(args.input).resolve()),
        "output": str(output_path),
        "source": source.name,
        "output_object": final_output.name,
        "sampling": args.sampling.upper(),
        "bake_mode": args.bake_mode.upper(),
        "voxel_size": voxel_size,
        "voxel_count": sample_count,
        "output_voxel_count": int(
            filter_mesh.get(meshing.ENCLOSED_OUTPUT_TAG, len(output.data.vertices))
        ),
        "remove_enclosed_voxels": bool(args.remove_enclosed_voxels),
        "enclosed_voxels_removed": int(
            filter_mesh.get(meshing.ENCLOSED_REMOVED_TAG, 0)
        ),
        "enclosed_filter_exact": bool(
            filter_mesh.get(meshing.ENCLOSED_EXACT_TAG, True)
        ),
        "enclosed_filter_skip_reason": str(
            filter_mesh.get(meshing.ENCLOSED_SKIP_TAG, "")
        ),
        "output_faces": len(final_output.data.polygons),
        "target_voxels": args.target_voxels,
        "attempts": attempts,
        "compute_backend_requested": args.compute_backend.upper(),
        "gpu_memory_limit_mb": args.gpu_memory_limit_mb,
        "compute_backend": sampling_report.get("compute_backend", {}),
        "occupancy_backend": sampling_report.get("occupancy_backend", {}),
        "sampling_phase_timings": sampling_report.get("phase_timings", {}),
        "source_session_timings": sampling_report.get("source_session_timings", {}),
        "bvh_query_count": sampling_report.get("bvh_query_count", 0),
        "timings": phase_timings,
    }
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("CHROMOXEL_CLI_RESULT " + json.dumps(report, sort_keys=True), flush=True)
    return report


def main() -> int:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        run(arguments)
        return 0
    except Exception as exc:
        print(f"CHROMOXEL_CLI_ERROR {exc}", file=sys.stderr, flush=True)
        return 2
