"""Validate the saved four-model Chromoxel 0.9 TripoTest project."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import meshing  # noqa: E402


EXPECTED_COUNTS = {
    "214730": (1_932, 19_674, 95_551),
    "220646": (1_903, 19_732, 99_293),
    "112043": (1_975, 19_654, 99_152),
    "112406": (1_965, 19_374, 98_215),
}


def main():
    report_path = Path(bpy.data.filepath).with_suffix(".json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "RENDERED"
    assert report["chromoxel"] == "0.9.0"
    assert report["render"]["engine"] == "CYCLES"
    assert report["render"]["backend"] == "OPTIX"
    assert report["render"]["samples"] == 32
    checked = []
    for key, expected in EXPECTED_COUNTS.items():
        original = bpy.data.objects[f"{key}_ORIGINAL"]
        assert abs(original.rotation_euler.z + 0.7853981633974483) < 1.0e-4
        carriers = sorted(
            (
                obj for obj in bpy.data.objects
                if obj.name.startswith(f"{key}_") and obj.name.endswith("_EDITABLE")
            ),
            key=lambda obj: int(obj.get("chromoxel_target_voxels", 0)),
        )
        assert tuple(len(obj.data.vertices) for obj in carriers) == expected
        for target, carrier in zip((2_000, 20_000, 100_000), carriers):
            assert abs(carrier.rotation_euler.z + 0.7853981633974483) < 1.0e-4
            count = len(carrier.data.vertices)
            assert int(target * 0.95) <= count <= target
            render_object = bpy.data.objects[f"V090_RENDER_{carrier.name}"]
            assert int(render_object.data[meshing.ENCLOSED_OUTPUT_TAG]) <= count
            assert bool(render_object.data[meshing.ENCLOSED_EXACT_TAG]) is True
            checked.append({
                "key": key,
                "target": target,
                "input": count,
                "visible": int(render_object.data[meshing.ENCLOSED_OUTPUT_TAG]),
                "faces": len(render_object.data.polygons),
            })
        render_path = Path(report["render"]["renders"][key]["path"])
        assert report["render"]["renders"][key]["camera_degrees"] == -45
        assert render_path.is_file() and render_path.stat().st_size > 1_000_000
    combined = Path(report["render"]["combined"])
    assert combined.is_file() and combined.stat().st_size > 2_000_000
    print(
        "PASS tripo_test_v090_saved_project "
        + json.dumps({"objects": checked, "combined_bytes": combined.stat().st_size}),
        flush=True,
    )


if __name__ == "__main__":
    main()
