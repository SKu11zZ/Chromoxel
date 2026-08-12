"""Chromoxel 0.9 source-session cache and staged-profile regression."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voxelizer import core, register, unregister  # noqa: E402


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    register()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
    source = bpy.context.object
    settings = bpy.context.scene.voxelizer_settings
    settings.voxel_size = 0.16
    settings.cube_gap = 0.01
    settings.compute_backend = "CPU"
    settings.sampling_mode = "UNIFORM"

    first = core.sample_surface_voxels(
        bpy.context,
        source,
        settings,
        use_cache=False,
        use_session_cache=True,
    )
    first_report = core.sampling_diagnostics(source)
    assert not first_report["source_session_cache_hit"]
    assert first_report["source_session_acquire_seconds"] > 0.0
    assert first_report["phase_timings"]["total"] > 0.0

    settings.voxel_size = 0.11
    second = core.sample_surface_voxels(
        bpy.context,
        source,
        settings,
        use_cache=False,
        use_session_cache=True,
    )
    second_report = core.sampling_diagnostics(source)
    assert second_report["source_session_cache_hit"]
    assert second.count > first.count
    stats = core.sampling_cache_stats()
    assert stats["session_entries"] == 1

    core.clear_sampling_cache()
    assert core.sampling_cache_stats()["session_entries"] == 0
    unregister()
    print("PASS chromoxel_blender_0.9.0_session_profile")


if __name__ == "__main__":
    main()
