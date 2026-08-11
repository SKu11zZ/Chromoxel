"""Measure passive Chromoxel panel draws against an imported source mesh."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import bpy


class DummyLayout:
    enabled = True

    def box(self):
        return self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def grid_flow(self, **_kwargs):
        return self

    def label(self, **_kwargs):
        return None

    def prop(self, *_args, **_kwargs):
        return None

    def prop_search(self, *_args, **_kwargs):
        return None

    def template_list(self, *_args, **_kwargs):
        return None

    def operator(self, *_args, **_kwargs):
        return SimpleNamespace()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--draws", type=int, default=100)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])

    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository))
    import voxelizer
    from voxelizer import cli, core

    voxelizer.register()
    imported = cli.import_input(args.input)
    source = cli.join_evaluated_meshes(imported, name="Panel_Benchmark_Source")
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.context.view_layer.update()

    original_diagnostics = core.mesh_diagnostics
    original_closed = core.is_closed_manifold

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Passive panel draw traversed mesh topology")

    panel = SimpleNamespace(layout=DummyLayout())
    try:
        core.mesh_diagnostics = forbidden
        core.is_closed_manifold = forbidden
        started = time.perf_counter()
        for _index in range(max(1, args.draws)):
            voxelizer.VOXELIZER_PT_panel.draw(panel, bpy.context)
        seconds = time.perf_counter() - started
    finally:
        core.mesh_diagnostics = original_diagnostics
        core.is_closed_manifold = original_closed

    settings = bpy.context.scene.voxelizer_settings
    started = time.perf_counter()
    first_key = core.preview_sampling_key(bpy.context, source, settings)
    first_key_seconds = time.perf_counter() - started
    started = time.perf_counter()
    for _index in range(max(1, args.draws)):
        assert core.preview_sampling_key(bpy.context, source, settings) == first_key
    repeated_key_seconds = time.perf_counter() - started

    print(
        "PASS chromoxel_panel_draw "
        + json.dumps(
            {
                "draws": max(1, args.draws),
                "total_seconds": round(seconds, 6),
                "milliseconds_per_draw": round(
                    seconds * 1000.0 / max(1, args.draws), 6
                ),
                "first_preview_key_ms": round(first_key_seconds * 1000.0, 6),
                "repeated_preview_key_ms": round(
                    repeated_key_seconds * 1000.0 / max(1, args.draws), 6
                ),
                "vertices": len(source.data.vertices),
                "polygons": len(source.data.polygons),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
