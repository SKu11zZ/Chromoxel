"""Re-render an existing Mixamo comparison project without re-voxelizing."""

from pathlib import Path
import sys
import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from voxelizer import core, meshing


OUTPUT_DIR = ROOT.parents[1] / "mixamo_voxel_showcase_v080"
CHARACTERS = ("CH14", "CH15", "CH46")

for obj in bpy.data.objects:
    if obj.name.startswith("SRC_CH"):
        obj.hide_render = True

groups = {name: bpy.data.collections[f"CLI_{name}"] for name in CHARACTERS}
bpy.context.scene.camera.data.ortho_scale = 16.0


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


for name, location, energy, angle in (
    ("CLI Sun Key", (-6.0, -8.0, 9.0), 3.0, 0.16),
    ("CLI Sun Fill", (7.0, -5.0, 5.0), 1.6, 0.25),
):
    existing = bpy.data.objects.get(name)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    light = bpy.data.lights.new(name, "SUN")
    light.energy = energy
    light.angle = angle
    obj = bpy.data.objects.new(name, light)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    point_at(obj, (0.0, 0.0, 1.7))

for character in CHARACTERS:
    for other, group in groups.items():
        for obj in group.objects:
            obj.hide_render = other != character
    realized = []
    for point_object in sorted(
        (obj for obj in groups[character].objects if obj.name.endswith("_EDITABLE")),
        key=lambda obj: obj.name,
    ):
        mesh, _count = meshing.build_from_editable(
            point_object,
            "REALIZED",
            point_object.name + "_RENDER_MESH",
        )
        render_object = bpy.data.objects.new(point_object.name + "_RENDER", mesh)
        groups[character].objects.link(render_object)
        render_object.location = point_object.location
        render_object.data.materials.append(core.ensure_colour_material())
        realized.append(render_object)
        point_object.hide_render = True
    bpy.context.scene.render.filepath = str(
        OUTPUT_DIR / f"{character}_Original_2K_20K_100K.png"
    )
    bpy.ops.render.render(write_still=True)
    print("CHROMOXEL_RERENDER", character, flush=True)
    for render_object in realized:
        mesh = render_object.data
        bpy.data.objects.remove(render_object, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

for character, group in groups.items():
    for obj in group.objects:
        obj.hide_render = (
            character != CHARACTERS[0]
            if not obj.name.endswith("_EDITABLE")
            else True
        )
bpy.ops.wm.save_as_mainfile(
    filepath=str(OUTPUT_DIR / "Chromoxel_Mixamo_CLI_Levels.blend"),
    compress=True,
)
