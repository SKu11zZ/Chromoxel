"""Exactness and bounded-performance smoke for the v0.5 sparse/cache paths."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
import sys
import time

import bpy
from mathutils import Vector


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import voxelizer  # noqa: E402
from voxelizer import core  # noqa: E402


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def centre_keys(centres):
    return {
        tuple(round(float(component), 7) for component in centre)
        for centre in centres
    }


def run():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    source = bpy.context.active_object
    source.name = "V050_PerformanceSphere"
    # Break every reflection proof so the benchmark measures the general path,
    # not the symmetric fundamental-domain shortcut covered by regression tests.
    source.data.vertices[137].co += Vector((0.013, 0.017, 0.023))
    source.data.update()
    settings = bpy.context.scene.voxelizer_settings
    settings.grid_origin_mode = "OBJECT"
    settings.sampling_mode = "UNIFORM"
    settings.voxel_size = 0.025
    settings.cube_gap = 0.01
    settings.auto_watertight_copy = True
    settings.sample_budget = 1_500_000
    settings.candidate_expansion_budget = 48_000_000
    settings.sampling_chunk_size = 512

    core.clear_sampling_cache()
    settings.sparse_grid_threshold = 0
    timings = {True: [], False: []}
    samples = {}
    reports = {}
    # Alternate order and compare medians so background scheduling noise does
    # not turn a structural performance regression into a flaky wall-clock test.
    for round_number in range(3):
        order = (True, False) if round_number % 2 == 0 else (False, True)
        for sparse_enabled in order:
            settings.use_sparse_candidates = sparse_enabled
            started = time.perf_counter()
            result = core.sample_surface_voxels(
                bpy.context, source, settings, use_cache=False
            )
            timings[sparse_enabled].append(time.perf_counter() - started)
            samples.setdefault(sparse_enabled, result)
            reports.setdefault(sparse_enabled, core.sampling_diagnostics(source))

    sparse, _colours, sparse_count, _used = samples[True]
    full, _colours, full_count, _used = samples[False]
    sparse_seconds = median(timings[True])
    full_seconds = median(timings[False])
    sparse_report = reports[True]
    full_report = reports[False]

    require(sparse_count == full_count, (sparse_count, full_count))
    require(centre_keys(sparse) == centre_keys(full), "sparse/full occupancy differs")
    require(
        sparse_report["candidate_count"] < sparse_report["full_grid_count"],
        sparse_report,
    )
    require(
        full_report["candidate_count"] == full_report["canonical_grid_count"],
        full_report,
    )
    require(
        sparse_seconds <= full_seconds * 1.10,
        (sparse_seconds, full_seconds, timings),
    )

    settings.use_sparse_candidates = True
    core.clear_sampling_cache()
    cold_started = time.perf_counter()
    core.sample_surface_voxels(bpy.context, source, settings)
    cold_seconds = time.perf_counter() - cold_started
    require(not core.sampling_diagnostics(source)["cache_hit"], "cold pass hit cache")
    warm_started = time.perf_counter()
    core.sample_surface_voxels(bpy.context, source, settings)
    warm_seconds = time.perf_counter() - warm_started
    require(core.sampling_diagnostics(source)["cache_hit"], "warm pass missed cache")
    require(warm_seconds < cold_seconds, (cold_seconds, warm_seconds))

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "voxels": sparse_count,
        "full_candidates": sparse_report["full_grid_count"],
        "sparse_candidates": sparse_report["candidate_count"],
        "candidate_reduction_ratio": sparse_report["candidate_reduction_ratio"],
        "sparse_seconds": round(sparse_seconds, 6),
        "full_seconds": round(full_seconds, 6),
        "timing_samples": {
            "sparse": [round(value, 6) for value in timings[True]],
            "full": [round(value, 6) for value in timings[False]],
        },
        "cache_cold_seconds": round(cold_seconds, 6),
        "cache_warm_seconds": round(warm_seconds, 6),
        "cache_entries": core.sampling_cache_stats()["entries"],
    }
    print("PASS chromoxel_blender_0.5.0_performance", json.dumps(report, sort_keys=True))


run()
