"""Interactive Blender 5.1 regression for the 0.9 GPU occupancy prefilter.

Run without ``--background``.  The script creates a deterministic UV sphere,
compares exact CPU and GPU-prefiltered coordinates, writes a JSON report, and
closes Blender.  It intentionally avoids rendering or other unrelated GPU work.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import traceback

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voxelizer import cli, core, register  # noqa: E402


REPORT = ROOT / "outputs" / "v090_gpu_occupancy_interactive.json"
LOG = ROOT / "outputs" / "v090_gpu_occupancy_interactive.log"


def mark(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(f"{time.perf_counter():.6f} {message}\n")


def sample(source, settings, backend: str):
    mark(f"{backend} configure start")
    cli.configure_settings(
        settings,
        voxel_size=0.12,
        sampling_mode="UNIFORM",
        detail_level=0,
        max_voxels=100_000,
        compute_backend=backend,
        gpu_batch_size=65_536,
        gpu_memory_limit_mb=512,
    )
    started = time.perf_counter()
    mark(f"{backend} session start")
    with core.sampling_session(bpy.context, source, settings) as session:
        mark(f"{backend} session prepared")
        result = core.sample_surface_voxels(
            bpy.context,
            source,
            settings,
            use_cache=False,
            session=session,
        )
        mark(f"{backend} sampled")
    elapsed = time.perf_counter() - started
    diagnostics = core.sampling_diagnostics(source)
    coordinates = [tuple(round(float(value), 8) for value in centre) for centre in result.centres]
    return result, coordinates, elapsed, diagnostics


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    mark("main start")
    register()
    mark("registered")
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
    mark("sphere created")
    source = bpy.context.object
    source.name = "Chromoxel090GPUSphere"
    settings = bpy.context.scene.voxelizer_settings

    cpu, cpu_coordinates, cpu_seconds, cpu_diagnostics = sample(source, settings, "CPU")
    mark("cpu complete")
    gpu, gpu_coordinates, gpu_seconds, gpu_diagnostics = sample(source, settings, "GPU")
    mark("gpu complete")
    occupancy = gpu_diagnostics.get("occupancy_backend", {})
    assert occupancy.get("used") is True, occupancy
    assert cpu.count == gpu.count
    assert cpu_coordinates == gpu_coordinates

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "gpu_backend": occupancy,
        "cpu_seconds": cpu_seconds,
        "gpu_seconds": gpu_seconds,
        "voxel_count": gpu.count,
        "cpu_bvh_queries": cpu_diagnostics.get("bvh_query_count"),
        "gpu_bvh_queries": gpu_diagnostics.get("bvh_query_count"),
        "exact_coordinate_match": True,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS chromoxel_blender_0.9.0_gpu_occupancy " + json.dumps(report, sort_keys=True))
    bpy.ops.wm.quit_blender()


def scheduled_main():
    try:
        main()
    except Exception:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(scheduled_main, first_interval=1.0)
