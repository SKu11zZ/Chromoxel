"""One-shot Chromoxel source-preparation profiler for Blender background mode."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import bpy


def emit(stage: str, **payload) -> None:
    print(
        "CHROMOXEL_PROFILE "
        + json.dumps({"stage": stage, **payload}, sort_keys=True),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--target", type=int, default=2000)
    parser.add_argument("--normalize-height", type=float, default=4.0)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])

    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository))
    from voxelizer import cli, core, register

    register()
    total_started = time.perf_counter()

    started = time.perf_counter()
    imported = cli.import_input(args.input)
    import_seconds = time.perf_counter() - started
    emit(
        "IMPORT",
        seconds=import_seconds,
        mesh_objects=len(imported),
        vertices=sum(len(obj.data.vertices) for obj in imported),
        polygons=sum(len(obj.data.polygons) for obj in imported),
        loops=sum(len(obj.data.loops) for obj in imported),
        images=len(bpy.data.images),
    )

    started = time.perf_counter()
    source = cli.join_evaluated_meshes(
        imported,
        name="Chromoxel_Profile_Source",
        normalize_height=args.normalize_height,
    )
    join_seconds = time.perf_counter() - started
    emit(
        "JOIN_EVALUATED",
        seconds=join_seconds,
        vertices=len(source.data.vertices),
        polygons=len(source.data.polygons),
        loops=len(source.data.loops),
    )

    started = time.perf_counter()
    area = cli._surface_area(bpy.context, source)
    area_seconds = time.perf_counter() - started
    emit("SURFACE_AREA", seconds=area_seconds, area=area)

    desired = args.target * (1.0 - 0.05 * 0.45)
    voxel_size = math.sqrt(max(1.0e-9, area) * 1.65 / max(1.0, desired))
    settings = bpy.context.scene.voxelizer_settings
    cli.configure_settings(
        settings,
        voxel_size=voxel_size,
        sampling_mode="UNIFORM",
        detail_level=0,
        compute_backend="CPU",
    )

    started = time.perf_counter()
    with core.sampling_session(bpy.context, source, settings) as session:
        session_seconds = time.perf_counter() - started
        emit("SOURCE_SESSION", seconds=session_seconds, timings=session.timings)

        started = time.perf_counter()
        occupancy = core.sample_surface_voxels(
            bpy.context,
            source,
            settings,
            use_cache=False,
            session=session,
            occupancy_only=True,
        )
        occupancy_seconds = time.perf_counter() - started
        emit("OCCUPANCY", seconds=occupancy_seconds, voxels=occupancy.count)

        started = time.perf_counter()
        coloured = core.sample_surface_voxels(
            bpy.context,
            source,
            settings,
            use_cache=False,
            session=session,
            occupancy_only=False,
        )
        colour_seconds = time.perf_counter() - started
        emit("COLOUR", seconds=colour_seconds, voxels=coloured.count)

    started = time.perf_counter()
    cli.create_editable_output(
        bpy.context,
        source,
        coloured,
        voxel_size,
        name="Chromoxel_Profile_Output",
    )
    carrier_seconds = time.perf_counter() - started
    emit("EDITABLE_CARRIER", seconds=carrier_seconds, voxels=coloured.count)
    emit(
        "TOTAL",
        seconds=time.perf_counter() - total_started,
        voxel_size=voxel_size,
        target=args.target,
    )


if __name__ == "__main__":
    main()
