"""Chromoxel 0.8 prepared-session and batched-carrier regression."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voxelizer import cli, core, register, unregister  # noqa: E402


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    register()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    source = bpy.context.object
    source.name = "SessionSphere"
    settings = bpy.context.scene.voxelizer_settings
    cli.configure_settings(
        settings,
        voxel_size=0.18,
        sampling_mode="UNIFORM",
        detail_level=0,
        max_voxels=100_000,
        compute_backend="AUTO",
    )

    started = time.perf_counter()
    with core.sampling_session(bpy.context, source, settings) as session:
        prepare_seconds = time.perf_counter() - started
        samples = []
        elapsed = []
        for size in (0.18, 0.12, 0.08):
            settings.voxel_size = size
            started = time.perf_counter()
            sample = core.sample_surface_voxels(
                bpy.context,
                source,
                settings,
                use_cache=False,
                session=session,
            )
            elapsed.append(time.perf_counter() - started)
            diagnostics = core.sampling_diagnostics(source)
            assert diagnostics["source_session_reused"] is True
            assert diagnostics["compute_backend"]["used"] == "CPU"
            samples.append(sample)

        settings.voxel_size = 0.12
        direct = core.sample_surface_voxels(
            bpy.context,
            source,
            settings,
            use_cache=False,
        )
        assert [tuple(value) for value in samples[1].centres] == [
            tuple(value) for value in direct.centres
        ]
        assert samples[1].colours == direct.colours

        started = time.perf_counter()
        output = cli.create_editable_output(
            bpy.context,
            source,
            samples[-1],
            0.08,
            name="SessionSphere_Editable",
        )
        carrier_seconds = time.perf_counter() - started
        assert len(output.data.vertices) == samples[-1].count

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "prepare_seconds": round(prepare_seconds, 4),
        "sample_seconds": [round(value, 4) for value in elapsed],
        "counts": [sample.count for sample in samples],
        "carrier_seconds": round(carrier_seconds, 4),
        "cache": core.sampling_cache_stats(),
    }
    print("PASS chromoxel_blender_0.8.0_performance " + json.dumps(report, sort_keys=True))
    unregister()


if __name__ == "__main__":
    main()
