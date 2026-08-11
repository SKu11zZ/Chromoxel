"""Interactive Blender smoke test for the optional GPU sampler."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import traceback

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voxelizer import core, gpu_backend  # noqa: E402


def main() -> None:
    image = bpy.data.images.new(
        "Chromoxel_GPU_Smoke",
        width=2,
        height=2,
        alpha=True,
        float_buffer=True,
    )
    image.colorspace_settings.name = "Linear Rec.709"
    image.pixels = (
        1.0, 0.0, 0.0, 1.0,
        0.0, 1.0, 0.0, 1.0,
        0.0, 0.0, 1.0, 1.0,
        1.0, 1.0, 1.0, 1.0,
    )
    image.update()
    colours, decision = gpu_backend.sample_image(
        image,
        ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)),
        filter_mode="NEAREST",
        requested="GPU",
        batch_size=1024,
    )
    assert decision.used == "GPU", decision
    assert colours is not None and len(colours) == 4, (colours, decision)
    assert all(math.isfinite(component) for colour in colours for component in colour)
    expected = (
        (1.0, 0.0, 0.0, 1.0),
        (0.0, 1.0, 0.0, 1.0),
        (0.0, 0.0, 1.0, 1.0),
        (1.0, 1.0, 1.0, 1.0),
    )
    for actual, reference in zip(colours, expected):
        assert max(abs(a - b) for a, b in zip(actual, reference)) < 1.0e-5, (
            actual,
            reference,
        )
    bilinear_uvs = ((0.5, 0.5), (0.35, 0.65), (1.15, -0.1))
    gpu_bilinear, bilinear_decision = gpu_backend.sample_image(
        image,
        bilinear_uvs,
        extension="REPEAT",
        filter_mode="BILINEAR",
        requested="GPU",
        batch_size=1024,
    )
    cpu_buffer = core._ImageBuffer(image, "REPEAT")
    cpu_bilinear = [cpu_buffer.bilinear(Vector(uv)) for uv in bilinear_uvs]
    assert bilinear_decision.used == "GPU" and gpu_bilinear is not None
    for actual, reference in zip(gpu_bilinear, cpu_bilinear):
        assert reference is not None
        assert max(abs(a - b) for a, b in zip(actual, reference)) < 2.0e-5, (
            actual,
            reference,
        )
    print("CHROMOXEL_GPU_SMOKE PASS", decision, colours, flush=True)


def run_after_startup():
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run_after_startup, first_interval=0.5)
