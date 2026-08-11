"""Chromoxel 0.8.2 enclosed-voxel optimization regression."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sys
import time

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import cli, core, editable, meshing, preview  # noqa: E402


def make_carrier(name: str, coordinates):
    coordinates = sorted(tuple(int(value) for value in coordinate) for coordinate in coordinates)
    mesh = bpy.data.meshes.new(name + "_Empty")
    output = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(output)
    count = len(coordinates)
    preview.configure_preview(
        output,
        [Vector(coordinate) for coordinate in coordinates],
        [(0.25, 0.55, 0.85, 1.0)] * count,
        [1.0] * count,
        [(1.0, 1.0, 1.0)] * count,
        [0] * count,
        1.0,
        core.ensure_colour_material(),
    )
    output[editable.GRID_SIZE_TAG] = 1.0
    output[editable.GRID_ORIGIN_TAG] = (0.0, 0.0, 0.0)
    editable.initialize_carrier(output, reset_delta=True)
    return output


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    settings = bpy.context.scene.voxelizer_settings
    assert settings.remove_enclosed_voxels is False
    settings.remove_enclosed_voxels = True

    solid_coordinates = [
        (x, y, z)
        for x in (-1, 0, 1)
        for y in (-1, 0, 1)
        for z in (-1, 0, 1)
    ]
    solid = make_carrier("V082_Solid", solid_coordinates)
    records = editable.records_from_object(solid)
    filtered, stats = meshing.remove_enclosed_records(records, 1.0, (0.0, 0.0, 0.0))
    assert len(records) == 27
    assert len(filtered) == 26
    assert stats["removed_voxels"] == 1
    assert stats["exact"] is True
    centre_coord = next(
        record.coord
        for record in records
        if all(abs(component) < 1.0e-6 for component in record.center)
    )
    assert centre_coord not in {record.coord for record in filtered}
    original_by_coord = {record.coord: record for record in records}
    assert all(record == original_by_coord[record.coord] for record in filtered)

    oversized_records = list(records)
    oversized_records[0] = replace(oversized_records[0], extent=(4.0, 4.0, 4.0))
    skipped_records, skipped_stats = meshing.remove_enclosed_records(
        oversized_records,
        1.0,
        (0.0, 0.0, 0.0),
        atomic_limit=32,
    )
    assert skipped_records == oversized_records
    assert skipped_stats["removed_voxels"] == 0
    assert skipped_stats["exact"] is False
    assert "safe limit" in skipped_stats["skip_reason"]

    adaptive_origin = (-0.5, -0.5, -0.5)
    central_atomic_coordinates = {
        (x, y, z)
        for x in (0, 1)
        for y in (0, 1)
        for z in (0, 1)
    }
    adaptive_records = [
        editable.VoxelRecord(
            voxel_id=1,
            coord=(0, 0, 0),
            center=(0.0, 0.0, 0.0),
            color=(0.8, 0.2, 0.1, 1.0),
            size=2.0,
            extent=(2.0, 2.0, 2.0),
            level=0,
        )
    ]
    for coordinate in (
        (x, y, z)
        for x in range(-1, 3)
        for y in range(-1, 3)
        for z in range(-1, 3)
        if (x, y, z) not in central_atomic_coordinates
    ):
        adaptive_records.append(
            editable.VoxelRecord(
                voxel_id=len(adaptive_records) + 1,
                coord=coordinate,
                center=tuple(
                    adaptive_origin[axis] + coordinate[axis]
                    for axis in range(3)
                ),
                color=(0.1, 0.7, 0.3, 1.0),
                size=1.0,
                extent=(1.0, 1.0, 1.0),
                level=1,
            )
        )
    adaptive_filtered, adaptive_stats = meshing.remove_enclosed_records(
        adaptive_records,
        1.0,
        adaptive_origin,
    )
    assert len(adaptive_records) == 57
    assert len(adaptive_filtered) == 56
    assert adaptive_stats["removed_voxels"] == 1
    assert adaptive_stats["atomic_cells"] == 64
    assert adaptive_stats["exact"] is True
    assert all(record.voxel_id != 1 for record in adaptive_filtered)

    adaptive_open = [
        record
        for record in adaptive_records
        if record.coord != (-1, 0, 0)
    ]
    adaptive_open_filtered, adaptive_open_stats = meshing.remove_enclosed_records(
        adaptive_open,
        1.0,
        adaptive_origin,
    )
    assert len(adaptive_open_filtered) == len(adaptive_open)
    assert adaptive_open_stats["removed_voxels"] == 0

    realized_full, full_count = meshing.build_from_editable(
        solid,
        "REALIZED",
        "V082_RealizedFull",
    )
    realized_filtered, filtered_count = meshing.build_from_editable(
        solid,
        "REALIZED",
        "V082_RealizedFiltered",
        remove_enclosed=True,
    )
    assert full_count == 27
    assert filtered_count == 26
    assert len(realized_full.polygons) == 162
    assert len(realized_filtered.polygons) == 156
    assert realized_filtered[meshing.ENCLOSED_REMOVED_TAG] == 1

    surface_full, surface_full_count = meshing.build_from_editable(
        solid,
        "SURFACE",
        "V082_SurfaceFull",
    )
    surface_filtered, surface_filtered_count = meshing.build_from_editable(
        solid,
        "SURFACE",
        "V082_SurfaceFiltered",
        remove_enclosed=True,
    )
    assert surface_full_count == 27
    assert surface_filtered_count == 26
    assert len(surface_full.polygons) == 54
    assert len(surface_filtered.polygons) == 54

    greedy_full, _ = meshing.build_from_editable(
        solid,
        "GREEDY",
        "V082_GreedyFull",
    )
    greedy_filtered, _ = meshing.build_from_editable(
        solid,
        "GREEDY",
        "V082_GreedyFiltered",
        remove_enclosed=True,
    )
    assert len(greedy_full.polygons) == 6
    assert len(greedy_filtered.polygons) == 6

    cli_surface = cli.bake_output(
        solid,
        "SURFACE",
        "V082_CLISurface",
        remove_enclosed=True,
    )
    assert len(cli_surface.data.polygons) == 54
    assert cli_surface.data[meshing.ENCLOSED_REMOVED_TAG] == 1
    assert len(editable.records_from_object(solid)) == 27

    for candidate in bpy.context.selected_objects:
        candidate.select_set(False)
    solid.select_set(True)
    bpy.context.view_layer.objects.active = solid
    settings.bake_mode = "REALIZED"
    assert bpy.ops.voxelizer.bake() == {"FINISHED"}
    operator_output = bpy.data.objects["V082_Solid_REALIZED"]
    assert len(operator_output.data.polygons) == 156
    assert operator_output["chromoxel_remove_enclosed_voxels"] is True
    assert operator_output["chromoxel_enclosed_removed_voxels"] == 1

    opened = make_carrier(
        "V082_Opened",
        [coordinate for coordinate in solid_coordinates if coordinate != (1, 0, 0)],
    )
    opened_filtered, opened_stats = meshing.remove_enclosed_records(
        editable.records_from_object(opened),
        1.0,
        (0.0, 0.0, 0.0),
    )
    assert len(opened_filtered) == 26
    assert opened_stats["removed_voxels"] == 0

    samples = core.VoxelSampleResult(
        centres=[Vector(coordinate) for coordinate in solid_coordinates],
        colours=[(0.25, 0.55, 0.85, 1.0)] * 27,
        sizes=[1.0] * 27,
        extents=[Vector((1.0, 1.0, 1.0))] * 27,
        levels=[0] * 27,
        used_image=True,
        source_uvs=[(0.25, 0.75)] * 27,
    )
    filtered_samples, sample_stats = core.remove_enclosed_uniform_samples(samples)
    assert filtered_samples.count == 26
    assert sample_stats["removed_voxels"] == 1
    assert len(filtered_samples.source_uvs) == 26

    parsed = cli.build_parser().parse_args(
        [
            "--input", "source.glb",
            "--output", "output.blend",
            "--voxel-size", "0.1",
            "--remove-enclosed-voxels",
        ]
    )
    assert parsed.remove_enclosed_voxels is True

    large_dimensions = (50, 50, 40)
    large_records = [
        editable.VoxelRecord(
            voxel_id=index + 1,
            coord=(x, y, z),
            center=(float(x), float(y), float(z)),
            color=(0.25, 0.55, 0.85, 1.0),
            size=1.0,
            extent=(1.0, 1.0, 1.0),
        )
        for index, (x, y, z) in enumerate(
            (x, y, z)
            for x in range(large_dimensions[0])
            for y in range(large_dimensions[1])
            for z in range(large_dimensions[2])
        )
    ]
    filter_started = time.perf_counter()
    large_filtered, large_stats = meshing.remove_enclosed_records(
        large_records,
        1.0,
        (0.0, 0.0, 0.0),
    )
    large_filter_seconds = time.perf_counter() - filter_started
    expected_interior = (
        (large_dimensions[0] - 2)
        * (large_dimensions[1] - 2)
        * (large_dimensions[2] - 2)
    )
    assert large_stats["removed_voxels"] == expected_interior
    assert len(large_filtered) == len(large_records) - expected_interior

    report = {
        "status": "PASS",
        "input_voxels": 27,
        "output_voxels": 26,
        "removed_voxels": 1,
        "realized_faces_before": len(realized_full.polygons),
        "realized_faces_after": len(realized_filtered.polygons),
        "surface_faces": len(surface_filtered.polygons),
        "greedy_faces": len(greedy_filtered.polygons),
        "large_input_voxels": len(large_records),
        "large_output_voxels": len(large_filtered),
        "large_filter_seconds": round(large_filter_seconds, 4),
        "adaptive_input_records": len(adaptive_records),
        "adaptive_output_records": len(adaptive_filtered),
        "adaptive_atomic_cells": adaptive_stats["atomic_cells"],
    }
    output_dir = ROOT / "build_validation" / "v082_enclosed"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print("PASS chromoxel_blender_0.8.2_enclosed", json.dumps(report, sort_keys=True))
    voxelizer.unregister()


if __name__ == "__main__":
    main()
