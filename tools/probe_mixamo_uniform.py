"""One-shot uniform character probe used to calibrate the acceptance render."""

from pathlib import Path
import sys
import time

import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import voxelizer
from voxelizer import cli, core


voxelizer.register()
source = bpy.data.objects[sys.argv[sys.argv.index("--") + 1]]
size = float(sys.argv[sys.argv.index("--") + 2])
settings = bpy.context.scene.voxelizer_settings
settings["chromoxel_cli_repair_voxel_size"] = 0.06
cli.configure_settings(settings, voxel_size=size, sampling_mode="UNIFORM", detail_level=0)
cli._select_only(source)
started = time.perf_counter()
sample = core.sample_surface_voxels(bpy.context, source, settings, use_cache=False)
print(
    "CHROMOXEL_PROBE",
    source.name,
    f"size={size:.8f}",
    f"voxels={sample.count}",
    f"seconds={time.perf_counter() - started:.3f}",
    flush=True,
)
