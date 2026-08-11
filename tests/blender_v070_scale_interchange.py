"""Chromoxel 0.7 model-limit, spatial-chunk, and VOX block regression."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer
from voxelizer import core, editable, vox_io


def make_carrier(name: str, records: list[editable.VoxelRecord], grid_size: float = 0.1):
    mesh = bpy.data.meshes.new(name + "_Carrier")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj[editable.GRID_SIZE_TAG] = grid_size
    obj[editable.GRID_ORIGIN_TAG] = (0.0, 0.0, 0.0)
    editable.initialize_carrier(obj, reset_delta=True)
    editable.replace_records(obj, records)
    obj[core.TOOL_TAG] = core.TOOL_ID
    obj[core.KIND_TAG] = core.PREVIEW_KIND
    return obj


def record(voxel_id: int, coordinate: tuple[int, int, int], colour, grid_size=0.1):
    return editable.VoxelRecord(
        voxel_id=voxel_id,
        coord=coordinate,
        center=tuple(value * grid_size for value in coordinate),
        color=colour,
        size=grid_size,
        extent=(grid_size, grid_size, grid_size),
        source_uv=((coordinate[0] % 97) / 96.0, (coordinate[1] % 89) / 88.0),
        chunk_id=editable.chunk_id_for_coordinate(coordinate),
    )


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    started = time.perf_counter()
    count = editable.MODEL_POINT_LIMIT
    records = []
    for index in range(count):
        coordinate = (index % 100, (index // 100) % 100, index // 10_000)
        colour = (
            (coordinate[0] % 17) / 16.0,
            (coordinate[1] % 19) / 18.0,
            (coordinate[2] % 11) / 10.0,
            1.0,
        )
        records.append(record(index + 1, coordinate, colour))
    generated_seconds = time.perf_counter() - started

    write_started = time.perf_counter()
    carrier = make_carrier("V070_100K", records)
    write_seconds = time.perf_counter() - write_started
    diagnostics = editable.validate_editable(carrier)
    assert diagnostics["voxels"] == 100_000
    assert diagnostics["within_model_limit"]
    assert diagnostics["duplicate_coordinates"] == 0
    assert diagnostics["duplicate_ids"] == 0
    assert diagnostics["chunks"] >= 16

    # One more point must be reported as beyond the per-model edit limit.
    overflow = records + [record(count + 1, (100, 100, 10), (1.0, 0.0, 1.0, 1.0))]
    overflow_carrier = make_carrier("V070_100K_PLUS_ONE", overflow)
    assert not editable.validate_editable(overflow_carrier)["within_model_limit"]

    # Coordinates beyond a single VOX 256-cube block must round-trip exactly.
    interchange = make_carrier(
        "V070_VOX_BLOCKS",
        [
            record(1, (-4, 1, 2), (1.0, 0.0, 0.0, 1.0)),
            record(2, (300, 1, 2), (0.0, 1.0, 0.0, 1.0)),
            record(3, (300, 270, 2), (0.0, 0.0, 1.0, 1.0)),
        ],
    )
    output_dir = ROOT / "build_validation" / "v070_scale_interchange"
    output_dir.mkdir(parents=True, exist_ok=True)
    vox_path = output_dir / "multiblock.vox"
    export_report = vox_io.export_vox(interchange, str(vox_path))
    assert export_report["models"] == 3, export_report
    imported, import_report = vox_io.import_vox(bpy.context, str(vox_path), 0.1)
    imported_coordinates = {item.coord for item in editable.records_from_object(imported)}
    # VOX normalization intentionally rebases the minimum occupied coordinate
    # to zero, but all relative integer offsets must remain exact.
    assert imported_coordinates == {(0, 0, 0), (304, 0, 0), (304, 269, 0)}
    assert import_report["voxels"] == 3

    # More than 255 distinct colors must take the deterministic quantized path.
    colors = []
    for index in range(300):
        colors.append(
            record(
                index + 1,
                (index, 0, 0),
                ((index % 17) / 16.0, ((index // 17) % 18) / 17.0, index / 299.0, 1.0),
            )
        )
    palette_carrier = make_carrier("V070_300_COLORS", colors)
    palette_path = output_dir / "quantized.vox"
    quantized_report = vox_io.export_vox(palette_carrier, str(palette_path))
    assert quantized_report["quantized"]
    assert quantized_report["palette_entries"] == 255

    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "model_limit": editable.MODEL_POINT_LIMIT,
        "points_written": diagnostics["voxels"],
        "spatial_chunks": diagnostics["chunks"],
        "record_generation_seconds": round(generated_seconds, 4),
        "carrier_write_seconds": round(write_seconds, 4),
        "vox_models": export_report["models"],
        "quantized_palette_entries": quantized_report["palette_entries"],
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS chromoxel_blender_0.7.0_scale_interchange", json.dumps(report, sort_keys=True))
    voxelizer.unregister()


main()
