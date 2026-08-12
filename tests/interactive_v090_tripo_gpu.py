"""Interactive 0.9 CPU/GPU occupancy benchmark on the two dense Tripo GLBs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import traceback

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voxelizer import cli, core, register  # noqa: E402


LEVEL_SIZES = (
    (0.123, 0.03923435119787872, 0.01775),
    (0.297, 0.10690062460818094, 0.0500),
)
REPORT = ROOT / "outputs" / "v090_tripo_gpu_benchmark.json"
LOG = ROOT / "outputs" / "v090_tripo_gpu_benchmark.log"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark exact CPU/GPU Uniform occupancy parity on two dense GLBs."
    )
    parser.add_argument("--input-a", required=True, type=Path)
    parser.add_argument("--input-b", required=True, type=Path)
    parser.add_argument("--report", default=REPORT, type=Path)
    parser.add_argument("--log", default=LOG, type=Path)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def mark(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(f"{time.perf_counter():.6f} {message}\n")


def prepare_source(path: Path):
    before = set(bpy.data.objects)
    result = bpy.ops.import_scene.gltf(filepath=str(path))
    if result != {"FINISHED"}:
        raise RuntimeError(f"glTF import failed: {result}")
    mesh_sources = [
        obj for obj in bpy.data.objects
        if obj not in before and obj.type == "MESH"
    ]
    if len(mesh_sources) != 1:
        raise RuntimeError(f"Expected one Tripo mesh, found {len(mesh_sources)}")
    source = mesh_sources[0]
    source.name = f"Tripo_{path.stem}"
    source.data.transform(source.matrix_world)
    source.matrix_world.identity()
    source.data.update()
    bounds = [Vector(corner) for corner in source.bound_box]
    minimum = Vector(tuple(min(value[axis] for value in bounds) for axis in range(3)))
    maximum = Vector(tuple(max(value[axis] for value in bounds) for axis in range(3)))
    height = max(1.0e-9, float(maximum.z - minimum.z))
    source.data.transform(Matrix.Scale(4.0 / height, 4))
    source.data.update()
    bounds = [Vector(corner) for corner in source.bound_box]
    minimum = Vector(tuple(min(value[axis] for value in bounds) for axis in range(3)))
    maximum = Vector(tuple(max(value[axis] for value in bounds) for axis in range(3)))
    source.data.transform(Matrix.Translation((
        -(float(minimum.x) + float(maximum.x)) * 0.5,
        -(float(minimum.y) + float(maximum.y)) * 0.5,
        -float(minimum.z),
    )))
    source.data.update()
    for obj in tuple(bpy.data.objects):
        if obj in before:
            continue
        if obj is not source and obj.name in bpy.data.objects:
            cli._remove_object(obj)
    return source


def configure(settings, size: float, backend: str) -> None:
    cli.configure_settings(
        settings,
        voxel_size=size,
        sampling_mode="UNIFORM",
        detail_level=0,
        max_voxels=100_000,
        compute_backend=backend,
        gpu_batch_size=65_536,
        gpu_memory_limit_mb=512,
    )
    settings.auto_watertight_copy = True
    settings.repair_voxel_size = 0.02


def main(args: argparse.Namespace) -> None:
    global LOG
    LOG = args.log
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    register()
    results = []
    models = ((args.input_a, LEVEL_SIZES[0]), (args.input_b, LEVEL_SIZES[1]))
    for path, sizes in models:
        if not path.is_file():
            raise FileNotFoundError(path)
        mark(f"{path.name} import start")
        source = prepare_source(path)
        settings = bpy.context.scene.voxelizer_settings
        configure(settings, sizes[0], "CPU")
        mark(f"{path.name} source session start")
        started = time.perf_counter()
        with core.sampling_session(bpy.context, source, settings) as session:
            prepare_seconds = time.perf_counter() - started
            mark(f"{path.name} source session ready {prepare_seconds:.4f}")
            reports = {}
            for level, size in zip(("2K", "20K", "100K"), sizes):
                coordinates = {}
                level_reports = {}
                for backend in ("CPU", "GPU", "GPU"):
                    label = backend if backend not in level_reports else "GPU_WARM"
                    configure(settings, size, backend)
                    started = time.perf_counter()
                    sample = core.sample_surface_voxels(
                        bpy.context,
                        source,
                        settings,
                        use_cache=False,
                        session=session,
                    )
                    elapsed = time.perf_counter() - started
                    diagnostics = core.sampling_diagnostics(source)
                    coordinates[label] = [
                        tuple(round(float(value), 8) for value in centre)
                        for centre in sample.centres
                    ]
                    level_reports[label] = {
                        "seconds": elapsed,
                        "voxels": sample.count,
                        "bvh_queries": diagnostics.get("bvh_query_count"),
                        "phase_timings": diagnostics.get("phase_timings"),
                        "occupancy_backend": diagnostics.get("occupancy_backend"),
                    }
                    mark(f"{path.name} {level} {label} complete {elapsed:.4f}")
                cpu_set = set(coordinates["CPU"])
                gpu_set = set(coordinates["GPU"])
                warm_set = set(coordinates["GPU_WARM"])
                comparison = {
                    "cpu_count": len(coordinates["CPU"]),
                    "gpu_count": len(coordinates["GPU"]),
                    "warm_count": len(coordinates["GPU_WARM"]),
                    "gpu_missing": len(cpu_set - gpu_set),
                    "gpu_extra": len(gpu_set - cpu_set),
                    "warm_missing": len(cpu_set - warm_set),
                    "warm_extra": len(warm_set - cpu_set),
                    "missing_examples": list(sorted(cpu_set - gpu_set))[:12],
                    "extra_examples": list(sorted(gpu_set - cpu_set))[:12],
                }
                mark(f"{path.name} {level} comparison {json.dumps(comparison, sort_keys=True)}")
                if comparison["gpu_missing"] or comparison["gpu_extra"] or comparison["warm_missing"] or comparison["warm_extra"]:
                    raise AssertionError(f"CPU/GPU coordinate mismatch: {comparison}")
                reports[level] = {
                    "voxel_size": size,
                    "runs": level_reports,
                    "comparison": comparison,
                }
        results.append({
            "model": str(path),
            "source_faces": len(source.data.polygons),
            "levels": reports,
            "source_prepare_seconds": prepare_seconds,
            "exact_coordinate_match": True,
        })
        for obj in tuple(bpy.data.objects):
            if obj.type == "MESH":
                cli._remove_object(obj)
    report = {"status": "PASS", "blender": bpy.app.version_string, "models": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS chromoxel_blender_0.9.0_tripo_gpu " + json.dumps(report, sort_keys=True))
    bpy.ops.wm.quit_blender()


def scheduled_main():
    window = bpy.context.window
    screen = window.screen if window is not None else None
    area = next((item for item in screen.areas if item.type == "VIEW_3D"), None) if screen else None
    region = next((item for item in area.regions if item.type == "WINDOW"), None) if area else None
    try:
        if window is None or area is None or region is None:
            raise RuntimeError("Interactive GPU benchmark requires a 3D View context")
        with bpy.context.temp_override(window=window, area=area, region=region):
            main(arguments())
    except Exception:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.1)
    return None


if __name__ == "__main__":
    bpy.app.timers.register(scheduled_main, first_interval=1.0)
