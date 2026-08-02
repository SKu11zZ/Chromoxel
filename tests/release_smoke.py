"""Portable Blender 5.1 release smoke test."""

from __future__ import annotations

import math
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import voxelizer  # noqa: E402
from voxelizer import core  # noqa: E402


def check_close(encoded: float, expected: float) -> None:
    actual = core._srgb_channel_to_scene_linear(encoded)
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-9):
        raise AssertionError(
            f"sRGB decode mismatch for {encoded}: {actual} != {expected}"
        )


check_close(0.0, 0.0)
check_close(0.04045, 0.0031308049535603713)
check_close(0.20392156862745098, 0.03433980680868217)
check_close(0.5764705882352941, 0.29177064981753587)
check_close(0.807843137254902, 0.6172065624196511)
check_close(1.0, 1.0)

voxelizer.register()
voxelizer.unregister()

print("PASS chromoxel_blender_0.5.0_release_smoke")
