"""Blender operators for editing Chromoxel point carriers."""

from __future__ import annotations

import json
from collections import deque

import bpy
from bpy.props import (
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    IntVectorProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup
from mathutils import Vector

from . import editable


def translated(context, english: str, chinese: str) -> str:
    settings = getattr(context.scene, "voxelizer_settings", None)
    mode = str(getattr(settings, "ui_language", "AUTO"))
    if mode == "ZH":
        return chinese
    if mode == "EN":
        return english
    language = str(getattr(context.preferences.view, "language", "en_US"))
    return chinese if language.lower().startswith("zh") else english


class VOXELIZER_PG_palette_slot(PropertyGroup):
    name: StringProperty(name="Name", default="Material")
    color: FloatVectorProperty(
        name="Base Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.48, 0.8, 1.0),
    )
    roughness: FloatProperty(name="Roughness", default=0.5, min=0.0, max=1.0)
    metallic: FloatProperty(name="Metallic", default=0.0, min=0.0, max=1.0)
    emission: FloatProperty(name="Emission", default=0.0, min=0.0, soft_max=25.0)


def active_editable(context) -> bpy.types.Object:
    output = context.active_object
    if not editable.is_editable(output):
        raise editable.EditableError(
            translated(
                context,
                "Select an editable Chromoxel Preview.",
                "请选择一个可编辑的 Chromoxel 预览。",
            )
        )
    return output


def _leave_edit_mode(output: bpy.types.Object) -> None:
    if output.mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _selected_records(output: bpy.types.Object):
    indices = set(editable.selected_indices(output))
    records = editable.records_from_object(output)
    return records, [records[index] for index in sorted(indices) if index < len(records)]


def _palette_values(settings):
    if settings.color_mode == "PALETTE" and settings.palette_slots:
        index = max(0, min(settings.palette_active_index, len(settings.palette_slots) - 1))
        slot = settings.palette_slots[index]
        return (
            tuple(slot.color),
            index + 1,
            index + 1,
            float(slot.roughness),
            float(slot.metallic),
            float(slot.emission),
        )
    return (
        tuple(settings.edit_color),
        0,
        int(settings.edit_material_id),
        float(settings.edit_roughness),
        float(settings.edit_metallic),
        float(settings.edit_emission),
    )


def _select_ids(output, ids) -> None:
    selected = set(int(value) for value in ids)
    records = editable.records_from_object(output)
    for vertex, record in zip(output.data.vertices, records):
        vertex.select = record.voxel_id in selected
    output.data.update()


class _EditableOperator:
    @classmethod
    def poll(cls, context):
        return editable.is_editable(context.active_object)

    def fail(self, context, exc):
        self.report({"ERROR"}, str(exc))
        return {"CANCELLED"}


class VOXELIZER_OT_enter_edit(_EditableOperator, Operator):
    bl_idname = "voxelizer.enter_voxel_edit"
    bl_label = "Enter Voxel Edit"
    bl_description = "Edit Preview carrier points while cubes remain instanced"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            context.view_layer.objects.active = output
            output.select_set(True)
            output.show_in_front = True
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.context.tool_settings.mesh_select_mode = (True, False, False)
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_exit_edit(_EditableOperator, Operator):
    bl_idname = "voxelizer.exit_voxel_edit"
    bl_label = "Exit Voxel Edit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            _leave_edit_mode(output)
            output.show_in_front = False
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_revoxelize_edits(_EditableOperator, Operator):
    bl_idname = "voxelizer.revoxelize_edits"
    bl_label = "Re-voxelize + Replay Edits"
    bl_description = "Rebuild from the linked source and replay the integer-coordinate edit layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from . import core, preview

            output = active_editable(context)
            _leave_edit_mode(output)
            source_name = str(output.get(core.SOURCE_TAG, ""))
            source = bpy.data.objects.get(source_name)
            if source is None:
                raise editable.EditableError(
                    "The linked source object is unavailable; imported VOX models have no mesh source to re-voxelize."
                )
            update = preview.refresh_preview(
                context,
                source,
                context.scene.voxelizer_settings,
                force_rebuild=True,
            )
            for selected in context.selected_objects:
                selected.select_set(False)
            update.output.select_set(True)
            context.view_layer.objects.active = update.output
            self.report(
                {"INFO"},
                f"Re-voxelized {update.point_count:,} points and replayed the edit layer exactly.",
            )
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_select(_EditableOperator, Operator):
    bl_idname = "voxelizer.voxel_select"
    bl_label = "Voxel Selection"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(
        items=(
            ("ALL", "All", "Select every voxel"),
            ("NONE", "None", "Deselect every voxel"),
            ("INVERT", "Invert", "Invert voxel selection"),
        ),
        default="ALL",
    )

    def execute(self, context):
        try:
            output = active_editable(context)
            was_edit = output.mode == "EDIT"
            _leave_edit_mode(output)
            for vertex in output.data.vertices:
                if self.action == "ALL":
                    vertex.select = True
                elif self.action == "NONE":
                    vertex.select = False
                else:
                    vertex.select = not vertex.select
            output.data.update()
            if was_edit:
                bpy.ops.object.mode_set(mode="EDIT")
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_box_select(_EditableOperator, Operator):
    bl_idname = "voxelizer.box_select_voxels"
    bl_label = "Box Select Voxels"
    bl_description = "Start Blender's native box selection on editable voxel points"

    def invoke(self, context, _event):
        try:
            output = active_editable(context)
            if output.mode != "EDIT":
                bpy.ops.voxelizer.enter_voxel_edit()
            window_region = next(
                (region for region in context.area.regions if region.type == "WINDOW"),
                None,
            )
            if window_region is None:
                raise editable.EditableError("A 3D View window region is required.")
            with context.temp_override(region=window_region):
                bpy.ops.view3d.select_box("INVOKE_DEFAULT", mode="ADD")
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_delete_selected(_EditableOperator, Operator):
    bl_idname = "voxelizer.delete_selected_voxels"
    bl_label = "Delete Selected Voxels"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("No voxels are selected.")
            selected_ids = {record.voxel_id for record in selected}
            operation = {
                "op": "DELETE_SET",
                "coords": [list(record.coord) for record in selected],
            }
            _leave_edit_mode(output)
            editable.replace_records(
                output,
                [record for record in records if record.voxel_id not in selected_ids],
            )
            editable.append_delta(output, operation)
            self.report({"INFO"}, f"Deleted {len(selected):,} voxel(s).")
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_add_cursor(_EditableOperator, Operator):
    bl_idname = "voxelizer.add_voxel_at_cursor"
    bl_label = "Add Voxel at Cursor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            _leave_edit_mode(output)
            settings = context.scene.voxelizer_settings
            local_cursor = output.matrix_world.inverted() @ context.scene.cursor.location
            coordinate = editable.coordinate_for_center(
                local_cursor,
                tuple(output[editable.GRID_ORIGIN_TAG]),
                float(output[editable.GRID_SIZE_TAG]),
            )
            colour, palette, material, roughness, metallic, emission = _palette_values(settings)
            record = editable.new_record_at(
                output,
                coordinate,
                colour,
                palette_index=palette,
                material_id=material,
                roughness=roughness,
                metallic=metallic,
                emission=emission,
            )
            by_coordinate = {item.coord: item for item in editable.records_from_object(output)}
            by_coordinate[coordinate] = record
            editable.replace_records(output, sorted(by_coordinate.values(), key=lambda item: item.coord), selected_ids=(record.voxel_id,))
            editable.append_delta(output, editable.add_operation(record))
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_move_selected(_EditableOperator, Operator):
    bl_idname = "voxelizer.move_selected_voxels"
    bl_label = "Move Selected Voxels"
    bl_description = "Move selected voxels in minimum-grid steps; destinations overwrite"
    bl_options = {"REGISTER", "UNDO"}

    delta: IntVectorProperty(name="Grid Delta", size=3, default=(1, 0, 0))

    def execute(self, context):
        try:
            output = active_editable(context)
            records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("No voxels are selected.")
            delta = tuple(int(value) for value in self.delta)
            if delta == (0, 0, 0):
                return {"FINISHED"}
            selected_ids = {record.voxel_id for record in selected}
            by_coordinate = {
                record.coord: record
                for record in records
                if record.voxel_id not in selected_ids
            }
            origin = tuple(output[editable.GRID_ORIGIN_TAG])
            grid_size = float(output[editable.GRID_SIZE_TAG])
            moves = []
            for record in selected:
                old_coordinate = record.coord
                destination = tuple(old_coordinate[axis] + delta[axis] for axis in range(3))
                record.coord = destination
                record.center = editable.center_for_coordinate(destination, origin, grid_size)
                record.chunk_id = editable.chunk_id_for_coordinate(destination)
                by_coordinate[destination] = record
                moves.append({"coord": list(old_coordinate), "to": list(destination)})
            _leave_edit_mode(output)
            editable.replace_records(
                output,
                sorted(by_coordinate.values(), key=lambda item: item.coord),
                selected_ids=selected_ids,
            )
            editable.append_delta(output, {"op": "MOVE_SET", "moves": moves})
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_paint_selected(_EditableOperator, Operator):
    bl_idname = "voxelizer.paint_selected_voxels"
    bl_label = "Paint Selected Voxels"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("No voxels are selected.")
            settings = context.scene.voxelizer_settings
            colour, palette, material, roughness, metallic, emission = _palette_values(settings)
            selected_ids = {record.voxel_id for record in selected}
            coords = []
            for record in records:
                if record.voxel_id in selected_ids:
                    record.color = colour
                    record.palette_index = palette
                    record.material_id = material
                    record.roughness = roughness
                    record.metallic = metallic
                    record.emission = emission
                    coords.append(list(record.coord))
            _leave_edit_mode(output)
            editable.replace_records(output, records, selected_ids=selected_ids)
            editable.append_delta(
                output,
                {"op": "PAINT_SET", "coords": coords, "color": list(colour), "palette_index": palette},
            )
            editable.append_delta(
                output,
                {
                    "op": "MATERIAL_SET",
                    "coords": coords,
                    "material_id": material,
                    "roughness": roughness,
                    "metallic": metallic,
                    "emission": emission,
                },
            )
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_pick_selected(_EditableOperator, Operator):
    bl_idname = "voxelizer.pick_selected_voxel"
    bl_label = "Pick Selected Voxel"
    bl_description = "Load colour and material values from the first selected voxel"

    def execute(self, context):
        try:
            output = active_editable(context)
            _records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("Select a voxel to pick.")
            record = selected[0]
            settings = context.scene.voxelizer_settings
            settings.edit_color = record.color
            settings.edit_material_id = record.material_id
            settings.edit_roughness = record.roughness
            settings.edit_metallic = record.metallic
            settings.edit_emission = record.emission
            if record.palette_index > 0 and record.palette_index <= len(settings.palette_slots):
                settings.palette_active_index = record.palette_index - 1
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


def _same_colour(first, second, tolerance=1.0e-5):
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(first, second))


def _atomic_occupancy(records, grid_size):
    occupancy = {}
    for index, record in enumerate(records):
        counts = [max(1, int(round(record.extent[axis] / grid_size))) for axis in range(3)]
        starts = [record.coord[axis] - (counts[axis] - 1) // 2 for axis in range(3)]
        for x in range(starts[0], starts[0] + counts[0]):
            for y in range(starts[1], starts[1] + counts[1]):
                for z in range(starts[2], starts[2] + counts[2]):
                    occupancy[(x, y, z)] = index
    return occupancy


def _connected_indices(records, seed_indices, grid_size, same_colour=False):
    occupancy = _atomic_occupancy(records, grid_size)
    record_atoms = {}
    for atom, index in occupancy.items():
        record_atoms.setdefault(index, []).append(atom)
    queue = deque(seed_indices)
    visited = set(seed_indices)
    while queue:
        index = queue.popleft()
        for atom in record_atoms.get(index, (records[index].coord,)):
            for axis in range(3):
                for direction in (-1, 1):
                    neighbour = list(atom)
                    neighbour[axis] += direction
                    other = occupancy.get(tuple(neighbour))
                    if other is None or other in visited:
                        continue
                    if same_colour and not _same_colour(records[index].color, records[other].color):
                        continue
                    visited.add(other)
                    queue.append(other)
    return visited


class VOXELIZER_OT_select_similar(_EditableOperator, Operator):
    bl_idname = "voxelizer.select_similar_voxels"
    bl_label = "Select Similar Voxels"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        items=(
            ("COLOR", "Color", "Select matching direct colour"),
            ("MATERIAL", "Material", "Select matching material ID"),
            ("LEVEL", "Level", "Select matching adaptive level"),
            ("CONNECTED", "Connected", "Select six-connected voxels"),
            ("COLOR_CONNECTED", "Color Region", "Select connected matching colour"),
        ),
        default="COLOR",
    )

    def execute(self, context):
        try:
            output = active_editable(context)
            records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("Select at least one seed voxel.")
            seeds = {record.voxel_id for record in selected}
            seed_indices = [index for index, record in enumerate(records) if record.voxel_id in seeds]
            reference = selected[0]
            if self.mode == "COLOR":
                indices = {index for index, record in enumerate(records) if _same_colour(record.color, reference.color)}
            elif self.mode == "MATERIAL":
                indices = {index for index, record in enumerate(records) if record.material_id == reference.material_id}
            elif self.mode == "LEVEL":
                indices = {index for index, record in enumerate(records) if record.level == reference.level}
            else:
                indices = _connected_indices(
                    records,
                    seed_indices,
                    float(output[editable.GRID_SIZE_TAG]),
                    same_colour=self.mode == "COLOR_CONNECTED",
                )
            _leave_edit_mode(output)
            _select_ids(output, (records[index].voxel_id for index in indices))
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_flood_fill(_EditableOperator, Operator):
    bl_idname = "voxelizer.flood_fill_voxels"
    bl_label = "Flood Fill Color Region"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("Select at least one seed voxel.")
            seed_ids = {record.voxel_id for record in selected}
            seed_indices = [index for index, record in enumerate(records) if record.voxel_id in seed_ids]
            indices = _connected_indices(
                records,
                seed_indices,
                float(output[editable.GRID_SIZE_TAG]),
                same_colour=True,
            )
            _leave_edit_mode(output)
            _select_ids(output, (records[index].voxel_id for index in indices))
            return bpy.ops.voxelizer.paint_selected_voxels()
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_mirror_selected(_EditableOperator, Operator):
    bl_idname = "voxelizer.mirror_selected_voxels"
    bl_label = "Mirror Selected Voxels"
    bl_description = "Copy selected voxels across an object-local axis"
    bl_options = {"REGISTER", "UNDO"}

    axis: EnumProperty(items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")

    def execute(self, context):
        try:
            output = active_editable(context)
            records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("No voxels are selected.")
            _leave_edit_mode(output)
            axis = {"X": 0, "Y": 1, "Z": 2}[self.axis]
            origin = tuple(output[editable.GRID_ORIGIN_TAG])
            grid_size = float(output[editable.GRID_SIZE_TAG])
            by_coordinate = {record.coord: record for record in records}
            added = []
            selected_ids = []
            for source in selected:
                center = list(source.center)
                center[axis] *= -1.0
                coordinate = editable.coordinate_for_center(center, origin, grid_size)
                duplicate = editable.new_record_at(
                    output,
                    coordinate,
                    source.color,
                    palette_index=source.palette_index,
                    material_id=source.material_id,
                    roughness=source.roughness,
                    metallic=source.metallic,
                    emission=source.emission,
                )
                duplicate.level = source.level
                duplicate.size = source.size
                duplicate.extent = source.extent
                duplicate.source_uv = source.source_uv
                by_coordinate[coordinate] = duplicate
                added.append(editable.record_payload(duplicate))
                selected_ids.append(duplicate.voxel_id)
            editable.replace_records(output, sorted(by_coordinate.values(), key=lambda item: item.coord), selected_ids=selected_ids)
            editable.append_delta(output, {"op": "ADD_SET", "records": added})
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_copy_voxels(_EditableOperator, Operator):
    bl_idname = "voxelizer.copy_voxels"
    bl_label = "Copy Voxels"

    def execute(self, context):
        try:
            output = active_editable(context)
            _records, selected = _selected_records(output)
            if not selected:
                raise editable.EditableError("No voxels are selected.")
            minimum = tuple(min(record.coord[axis] for record in selected) for axis in range(3))
            payload = []
            for record in selected:
                value = editable.record_payload(record)
                value["coord"] = [record.coord[axis] - minimum[axis] for axis in range(3)]
                payload.append(value)
            context.scene.voxelizer_clipboard = json.dumps(payload, separators=(",", ":"))
            self.report({"INFO"}, f"Copied {len(payload):,} voxel(s).")
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_paste_voxels(_EditableOperator, Operator):
    bl_idname = "voxelizer.paste_voxels"
    bl_label = "Paste Voxels at Cursor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            raw = str(context.scene.voxelizer_clipboard or "[]")
            payloads = json.loads(raw)
            if not isinstance(payloads, list) or not payloads:
                raise editable.EditableError("Voxel clipboard is empty.")
            _leave_edit_mode(output)
            local_cursor = output.matrix_world.inverted() @ context.scene.cursor.location
            anchor = editable.coordinate_for_center(
                local_cursor,
                tuple(output[editable.GRID_ORIGIN_TAG]),
                float(output[editable.GRID_SIZE_TAG]),
            )
            by_coordinate = {record.coord: record for record in editable.records_from_object(output)}
            added = []
            selected_ids = []
            for payload in payloads:
                source = editable.record_from_payload(payload)
                coordinate = tuple(anchor[axis] + source.coord[axis] for axis in range(3))
                record = editable.new_record_at(
                    output,
                    coordinate,
                    source.color,
                    palette_index=source.palette_index,
                    material_id=source.material_id,
                    roughness=source.roughness,
                    metallic=source.metallic,
                    emission=source.emission,
                )
                record.level = source.level
                record.size = source.size
                record.extent = source.extent
                record.source_uv = source.source_uv
                by_coordinate[coordinate] = record
                selected_ids.append(record.voxel_id)
                added.append(editable.record_payload(record))
            editable.replace_records(output, sorted(by_coordinate.values(), key=lambda item: item.coord), selected_ids=selected_ids)
            editable.append_delta(output, {"op": "ADD_SET", "records": added})
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_palette_add(Operator):
    bl_idname = "voxelizer.palette_add"
    bl_label = "Add Palette Slot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        slot = settings.palette_slots.add()
        slot.name = f"Material {len(settings.palette_slots):03d}"
        slot.color = settings.edit_color
        slot.roughness = settings.edit_roughness
        slot.metallic = settings.edit_metallic
        slot.emission = settings.edit_emission
        settings.palette_active_index = len(settings.palette_slots) - 1
        return {"FINISHED"}


class VOXELIZER_OT_palette_remove(Operator):
    bl_idname = "voxelizer.palette_remove"
    bl_label = "Remove Palette Slot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        if settings.palette_slots:
            index = max(0, min(settings.palette_active_index, len(settings.palette_slots) - 1))
            settings.palette_slots.remove(index)
            settings.palette_active_index = min(index, len(settings.palette_slots) - 1)
        return {"FINISHED"}


class VOXELIZER_OT_palette_update_linked(_EditableOperator, Operator):
    bl_idname = "voxelizer.palette_update_linked"
    bl_label = "Update Linked Voxels"
    bl_description = "Apply the active palette slot to every voxel that references it"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            output = active_editable(context)
            settings = context.scene.voxelizer_settings
            if not settings.palette_slots:
                raise editable.EditableError("The palette has no slots.")
            index = max(0, min(settings.palette_active_index, len(settings.palette_slots) - 1))
            slot = settings.palette_slots[index]
            palette_index = index + 1
            records = editable.records_from_object(output)
            coords = []
            selected_ids = []
            for record in records:
                if record.palette_index != palette_index:
                    continue
                record.color = tuple(slot.color)
                record.material_id = palette_index
                record.roughness = slot.roughness
                record.metallic = slot.metallic
                record.emission = slot.emission
                coords.append(list(record.coord))
                selected_ids.append(record.voxel_id)
            _leave_edit_mode(output)
            editable.replace_records(output, records, selected_ids=selected_ids)
            editable.append_delta(output, {"op": "PAINT_SET", "coords": coords, "color": list(slot.color), "palette_index": palette_index})
            editable.append_delta(output, {"op": "MATERIAL_SET", "coords": coords, "material_id": palette_index, "roughness": slot.roughness, "metallic": slot.metallic, "emission": slot.emission})
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


class VOXELIZER_OT_palette_generate(_EditableOperator, Operator):
    bl_idname = "voxelizer.palette_generate"
    bl_label = "Generate Palette from Voxels"
    bl_description = "Deterministically quantize direct voxel colours to at most 255 palette slots"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from . import vox_io

            output = active_editable(context)
            _leave_edit_mode(output)
            records = editable.records_from_object(output)
            palette, indices = vox_io.quantize_colours(record.color for record in records)
            settings = context.scene.voxelizer_settings
            settings.palette_slots.clear()
            for index, rgba in enumerate(palette, start=1):
                slot = settings.palette_slots.add()
                slot.name = f"Material {index:03d}"
                slot.color = vox_io._linear_rgba(rgba)
            grouped = {}
            for record, palette_index in zip(records, indices):
                slot = settings.palette_slots[palette_index - 1]
                record.palette_index = palette_index
                record.material_id = palette_index
                record.color = tuple(slot.color)
                grouped.setdefault(palette_index, []).append(list(record.coord))
            editable.replace_records(output, records)
            for palette_index, coordinates in grouped.items():
                slot = settings.palette_slots[palette_index - 1]
                editable.append_delta(
                    output,
                    {
                        "op": "PAINT_SET",
                        "coords": coordinates,
                        "color": list(slot.color),
                        "palette_index": palette_index,
                    },
                )
                editable.append_delta(
                    output,
                    {
                        "op": "MATERIAL_SET",
                        "coords": coordinates,
                        "material_id": palette_index,
                        "roughness": slot.roughness,
                        "metallic": slot.metallic,
                        "emission": slot.emission,
                    },
                )
            settings.color_mode = "PALETTE"
            settings.palette_active_index = 0
            self.report({"INFO"}, f"Generated {len(palette)} palette slot(s) for {len(records):,} voxels.")
            return {"FINISHED"}
        except Exception as exc:
            return self.fail(context, exc)


CLASSES = (
    VOXELIZER_PG_palette_slot,
    VOXELIZER_OT_enter_edit,
    VOXELIZER_OT_exit_edit,
    VOXELIZER_OT_revoxelize_edits,
    VOXELIZER_OT_select,
    VOXELIZER_OT_box_select,
    VOXELIZER_OT_delete_selected,
    VOXELIZER_OT_add_cursor,
    VOXELIZER_OT_move_selected,
    VOXELIZER_OT_paint_selected,
    VOXELIZER_OT_pick_selected,
    VOXELIZER_OT_select_similar,
    VOXELIZER_OT_flood_fill,
    VOXELIZER_OT_mirror_selected,
    VOXELIZER_OT_copy_voxels,
    VOXELIZER_OT_paste_voxels,
    VOXELIZER_OT_palette_add,
    VOXELIZER_OT_palette_remove,
    VOXELIZER_OT_palette_update_linked,
    VOXELIZER_OT_palette_generate,
)
