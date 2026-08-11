"""Benchmark one already-imported Mixamo source across the 2K/20K/100K levels."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import traceback

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from tools import render_mixamo_cli_levels as showcase  # noqa: E402


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    source_name = arguments[0] if arguments else "CH14"
    report_path = Path(arguments[1]).resolve() if len(arguments) > 1 else None
    voxelizer.register()
    source = bpy.data.objects.get(source_name)
    if source is None:
        source = bpy.data.objects.get("SRC_" + source_name)
    if source is None or source.type != "MESH":
        raise RuntimeError(f"Mixamo source not found: {source_name}")
    if source.name not in showcase.CALIBRATED_SIZES:
        showcase.CALIBRATED_SIZES[source.name] = showcase.CALIBRATED_SIZES[source_name]
    settings = bpy.context.scene.voxelizer_settings
    settings["chromoxel_cli_repair_voxel_size"] = 0.06
    started = time.perf_counter()
    levels = showcase.fit_levels(source, settings)
    elapsed = time.perf_counter() - started
    report = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "chromoxel": "0.8.0-dev",
        "source": source_name,
        "elapsed_seconds": round(elapsed, 4),
        "levels": [
            {
                "target": target,
                "actual": sample.count,
                "voxel_size": voxel_size,
                "attempts": attempts,
            }
            for target, sample, voxel_size, attempts in levels
        ],
        "sampling_diagnostics": voxelizer.core.sampling_diagnostics(source),
        "cache": voxelizer.core.sampling_cache_stats(),
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS chromoxel_mixamo_performance " + json.dumps(report, sort_keys=True), flush=True)


def _run_interactive() -> None:
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    if bpy.app.background:
        main()
    else:
        # Delay until the window owns a valid compute context.
        bpy.app.timers.register(_run_interactive, first_interval=0.5)
