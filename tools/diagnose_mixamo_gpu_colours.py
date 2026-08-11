"""Compare CPU/GPU colour sampling on one loaded Mixamo source."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import cli, core, editable  # noqa: E402


def statistics(colours):
    if not colours:
        return {}
    return {
        "minimum": [min(value[channel] for value in colours) for channel in range(4)],
        "maximum": [max(value[channel] for value in colours) for channel in range(4)],
        "mean": [sum(value[channel] for value in colours) / len(colours) for channel in range(4)],
        "first": [tuple(value) for value in colours[:8]],
    }


def main() -> None:
    voxelizer.register()
    source = bpy.data.objects.get("SRC_CH14")
    if source is None:
        raise RuntimeError("SRC_CH14 not found")
    settings = bpy.context.scene.voxelizer_settings
    settings["chromoxel_cli_repair_voxel_size"] = 0.06
    cli.configure_settings(
        settings,
        voxel_size=0.1128191,
        sampling_mode="UNIFORM",
        detail_level=0,
        max_voxels=editable.MODEL_POINT_LIMIT,
        compute_backend="CPU",
    )
    cli._select_only(source)
    with core.sampling_session(bpy.context, source, settings) as session:
        cpu = core.sample_surface_voxels(
            bpy.context, source, settings, use_cache=False, session=session
        )
        cpu_diagnostics = core.sampling_diagnostics(source)
        settings.compute_backend = "GPU"
        gpu = core.sample_surface_voxels(
            bpy.context, source, settings, use_cache=False, session=session
        )
        gpu_diagnostics = core.sampling_diagnostics(source)
        buffers = []
        for buffer in session.sampler._buffers.values():
            buffers.append({
                "image": buffer.image.name,
                "size": tuple(buffer.image.size),
                "colorspace": buffer.image.colorspace_settings.name,
                "bytes": buffer.estimated_bytes,
                "valid": buffer.valid,
                "raw_first": tuple(buffer.pixels[:16]),
            })
    differences = [
        max(abs(float(a) - float(b)) for a, b in zip(cpu_colour, gpu_colour))
        for cpu_colour, gpu_colour in zip(cpu.colours, gpu.colours)
    ]
    report = {
        "buffers": buffers,
        "cpu": statistics(cpu.colours),
        "gpu": statistics(gpu.colours),
        "maximum_difference": max(differences),
        "mean_difference": sum(differences) / len(differences),
        "cpu_backend": cpu_diagnostics.get("compute_backend"),
        "gpu_backend": gpu_diagnostics.get("compute_backend"),
    }
    print("CHROMOXEL_GPU_COLOUR_DIAGNOSTIC " + json.dumps(report), flush=True)


def run_after_startup() -> None:
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(run_after_startup, first_interval=0.5)
