"""MagicaVoxel VOX v150/v200 import and export for editable carriers."""

from __future__ import annotations

import math
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import core, editable, meshing, preview


VOX_MAGIC = b"VOX "
VOX_VERSION = 200


class VoxIOError(RuntimeError):
    """Raised for malformed or unrepresentable VOX data."""


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<i", len(encoded)) + encoded


def _dict(values: dict[str, object]) -> bytes:
    payload = struct.pack("<i", len(values))
    for key, value in values.items():
        payload += _string(str(key)) + _string(str(value))
    return payload


def _chunk(identifier: bytes, content: bytes = b"", children: bytes = b"") -> bytes:
    if len(identifier) != 4:
        raise VoxIOError("VOX chunk identifiers must be four bytes.")
    return identifier + struct.pack("<II", len(content), len(children)) + content + children


def _rgba8(colour: Sequence[float]) -> tuple[int, int, int, int]:
    def linear_to_srgb(value: float) -> float:
        value = max(0.0, min(1.0, value))
        if value <= 0.0031308:
            return value * 12.92
        return 1.055 * (value ** (1.0 / 2.4)) - 0.055

    return (
        int(round(linear_to_srgb(float(colour[0])) * 255.0)),
        int(round(linear_to_srgb(float(colour[1])) * 255.0)),
        int(round(linear_to_srgb(float(colour[2])) * 255.0)),
        int(round(max(0.0, min(1.0, float(colour[3]))) * 255.0)),
    )


def _linear_rgba(colour: Sequence[int]) -> tuple[float, float, float, float]:
    return (
        core._srgb_channel_to_scene_linear(int(colour[0]) / 255.0),
        core._srgb_channel_to_scene_linear(int(colour[1]) / 255.0),
        core._srgb_channel_to_scene_linear(int(colour[2]) / 255.0),
        int(colour[3]) / 255.0,
    )


def _median_cut(histogram: Counter, limit: int = 255):
    boxes = [list(histogram)]
    while len(boxes) < limit:
        candidates = [box for box in boxes if len(box) > 1]
        if not candidates:
            break
        box = max(
            candidates,
            key=lambda values: max(
                max(colour[channel] for colour in values) - min(colour[channel] for colour in values)
                for channel in range(4)
            ) * sum(histogram[colour] for colour in values),
        )
        ranges = [
            max(colour[channel] for colour in box) - min(colour[channel] for colour in box)
            for channel in range(4)
        ]
        channel = max(range(4), key=lambda value: ranges[value])
        ordered = sorted(box, key=lambda colour: colour[channel])
        total = sum(histogram[colour] for colour in ordered)
        accumulated = 0
        split = 1
        for index, colour in enumerate(ordered[:-1], start=1):
            accumulated += histogram[colour]
            if accumulated * 2 >= total:
                split = index
                break
        boxes.remove(box)
        boxes.extend((ordered[:split], ordered[split:]))

    palette = []
    for box in boxes:
        weight = sum(histogram[colour] for colour in box)
        palette.append(
            tuple(
                int(round(sum(colour[channel] * histogram[colour] for colour in box) / max(1, weight)))
                for channel in range(4)
            )
        )
    return palette


def quantize_colours(colours: Iterable[Sequence[float]]):
    rgba = [_rgba8(colour) for colour in colours]
    histogram = Counter(rgba)
    palette = list(histogram)
    if len(palette) > 255:
        palette = _median_cut(histogram, 255)
    lookup = {}
    for colour in histogram:
        lookup[colour] = min(
            range(len(palette)),
            key=lambda index: sum((colour[channel] - palette[index][channel]) ** 2 for channel in range(4)),
        ) + 1
    return palette, [lookup[colour] for colour in rgba]


def _node_transform(node_id: int, child_id: int, translation: Sequence[int]) -> bytes:
    return _chunk(
        b"nTRN",
        struct.pack("<i", node_id)
        + _dict({})
        + struct.pack("<iii", child_id, -1, 0)
        + struct.pack("<i", 1)
        + _dict({"_t": f"{translation[0]} {translation[1]} {translation[2]}"}),
    )


def _node_group(node_id: int, children: Sequence[int]) -> bytes:
    return _chunk(
        b"nGRP",
        struct.pack("<i", node_id)
        + _dict({})
        + struct.pack("<i", len(children))
        + b"".join(struct.pack("<i", child) for child in children),
    )


def _node_shape(node_id: int, model_id: int) -> bytes:
    return _chunk(
        b"nSHP",
        struct.pack("<i", node_id)
        + _dict({})
        + struct.pack("<i", 1)
        + struct.pack("<i", model_id)
        + _dict({}),
    )


def export_vox(output: bpy.types.Object, filepath: str) -> dict[str, object]:
    if not editable.is_editable(output):
        raise VoxIOError("VOX export requires an editable Chromoxel Preview.")
    records = editable.records_from_object(output)
    grid_size = float(output[editable.GRID_SIZE_TAG])
    origin = tuple(output[editable.GRID_ORIGIN_TAG])
    atoms = meshing.atomic_records(records, grid_size, origin)
    if not atoms:
        raise VoxIOError("VOX export requires at least one occupied voxel.")
    material_keys = [
        (
            _rgba8(record.color),
            int(record.material_id),
            round(float(record.roughness), 6),
            round(float(record.metallic), 6),
            round(float(record.emission), 6),
        )
        for record in atoms
    ]
    unique_material_keys = list(dict.fromkeys(material_keys))
    if len(unique_material_keys) <= 255:
        key_to_index = {key: index + 1 for index, key in enumerate(unique_material_keys)}
        palette = [key[0] for key in unique_material_keys]
        indices = [key_to_index[key] for key in material_keys]
    else:
        palette, indices = quantize_colours(record.color for record in atoms)

    minimum = tuple(min(record.coord[axis] for record in atoms) for axis in range(3))
    normalized = [
        tuple(record.coord[axis] - minimum[axis] for axis in range(3))
        for record in atoms
    ]
    models = defaultdict(list)
    for record, coordinate, palette_index in zip(atoms, normalized, indices):
        block = tuple(int(value // 256) for value in coordinate)
        local = tuple(int(value % 256) for value in coordinate)
        models[block].append((local, palette_index, record))

    children = _chunk(b"PACK", struct.pack("<i", len(models)))
    ordered_models = sorted(models.items())
    for _model_index, (_block, voxels) in enumerate(ordered_models):
        size = tuple(max(value[0][axis] for value in voxels) + 1 for axis in range(3))
        children += _chunk(b"SIZE", struct.pack("<iii", *size))
        payload = struct.pack("<i", len(voxels))
        payload += b"".join(
            struct.pack("<BBBB", coordinate[0], coordinate[1], coordinate[2], palette_index)
            for coordinate, palette_index, _record in voxels
        )
        children += _chunk(b"XYZI", payload)

    rgba = palette + [(0, 0, 0, 0)] * (256 - len(palette))
    children += _chunk(b"RGBA", b"".join(struct.pack("<BBBB", *colour) for colour in rgba[:256]))

    # Material properties are palette-scoped in VOX.  Average all atoms mapped
    # to the same palette entry to retain the most useful PBR subset.
    properties = defaultdict(list)
    for record, palette_index in zip(atoms, indices):
        properties[palette_index].append(record)
    for palette_index, values in sorted(properties.items()):
        roughness = sum(value.roughness for value in values) / len(values)
        metallic = sum(value.metallic for value in values) / len(values)
        emission = sum(value.emission for value in values) / len(values)
        material_type = "_emit" if emission > 0.0 else "_metal" if metallic >= 0.5 else "_diffuse"
        attributes = {"_type": material_type, "_rough": f"{roughness:.6g}", "_weight": "1"}
        if emission > 0.0:
            attributes["_flux"] = f"{emission:.6g}"
        children += _chunk(b"MATL", struct.pack("<i", palette_index) + _dict(attributes))

    transform_nodes = []
    root_children = []
    next_node = 2
    for model_index, (block, _voxels) in enumerate(ordered_models):
        transform_id = next_node
        shape_id = next_node + 1
        next_node += 2
        root_children.append(transform_id)
        transform_nodes.append(_node_transform(transform_id, shape_id, tuple(value * 256 for value in block)))
        transform_nodes.append(_node_shape(shape_id, model_index))
    children += _node_transform(0, 1, (0, 0, 0))
    children += _node_group(1, root_children)
    children += b"".join(transform_nodes)
    children += _chunk(b"LAYR", struct.pack("<i", 0) + _dict({"_name": output.name}) + struct.pack("<i", -1))

    data = VOX_MAGIC + struct.pack("<i", VOX_VERSION) + _chunk(b"MAIN", b"", children)
    Path(filepath).write_bytes(data)
    return {
        "voxels": len(atoms),
        "models": len(models),
        "palette_entries": len(palette),
        "quantized": len(unique_material_keys) > 255,
        "bytes": len(data),
    }


def _read_string(data: memoryview, offset: int):
    if offset + 4 > len(data):
        raise VoxIOError("Unexpected end of VOX string.")
    length = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    if length < 0 or offset + length > len(data):
        raise VoxIOError("Invalid VOX string length.")
    return bytes(data[offset:offset + length]).decode("utf-8", errors="replace"), offset + length


def _read_dict(data: memoryview, offset: int):
    count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    values = {}
    for _index in range(count):
        key, offset = _read_string(data, offset)
        value, offset = _read_string(data, offset)
        values[key] = value
    return values, offset


@dataclass
class ParsedChunk:
    identifier: bytes
    content: memoryview


def _walk_chunks(data: memoryview, start: int, end: int):
    offset = start
    while offset < end:
        if offset + 12 > end:
            raise VoxIOError("Truncated VOX chunk header.")
        identifier = bytes(data[offset:offset + 4])
        content_size, children_size = struct.unpack_from("<II", data, offset + 4)
        content_start = offset + 12
        content_end = content_start + content_size
        children_end = content_end + children_size
        if children_end > end:
            raise VoxIOError("VOX chunk exceeds its parent bounds.")
        yield ParsedChunk(identifier, data[content_start:content_end])
        if children_size:
            yield from _walk_chunks(data, content_end, children_end)
        offset = children_end


def parse_vox(filepath: str):
    raw = Path(filepath).read_bytes()
    if len(raw) < 20 or raw[:4] != VOX_MAGIC:
        raise VoxIOError("Not a MagicaVoxel VOX file.")
    version = struct.unpack_from("<i", raw, 4)[0]
    if raw[8:12] != b"MAIN":
        raise VoxIOError("VOX MAIN chunk is missing.")
    content_size, children_size = struct.unpack_from("<II", raw, 12)
    children_start = 20 + content_size
    children_end = children_start + children_size
    chunks = list(_walk_chunks(memoryview(raw), children_start, children_end))

    models = []
    pending_size = None
    palette = [(0, 0, 0, 0)] * 256
    materials = {}
    transforms = {}
    shapes = {}
    groups = {}
    for chunk in chunks:
        data = chunk.content
        if chunk.identifier == b"SIZE":
            pending_size = struct.unpack_from("<iii", data, 0)
        elif chunk.identifier == b"XYZI":
            count = struct.unpack_from("<i", data, 0)[0]
            voxels = [struct.unpack_from("<BBBB", data, 4 + index * 4) for index in range(count)]
            models.append({"size": pending_size, "voxels": voxels})
            pending_size = None
        elif chunk.identifier == b"RGBA":
            palette = [struct.unpack_from("<BBBB", data, index * 4) for index in range(256)]
        elif chunk.identifier == b"MATL":
            palette_index = struct.unpack_from("<i", data, 0)[0]
            values, _offset = _read_dict(data, 4)
            materials[palette_index] = values
        elif chunk.identifier == b"nTRN":
            node_id = struct.unpack_from("<i", data, 0)[0]
            _attributes, offset = _read_dict(data, 4)
            child, _reserved, _layer, frames = struct.unpack_from("<iiii", data, offset)
            offset += 16
            frame, _offset = _read_dict(data, offset) if frames else ({}, offset)
            translation = tuple(int(value) for value in frame.get("_t", "0 0 0").split())
            transforms[node_id] = (child, translation)
        elif chunk.identifier == b"nGRP":
            node_id = struct.unpack_from("<i", data, 0)[0]
            _attributes, offset = _read_dict(data, 4)
            count = struct.unpack_from("<i", data, offset)[0]
            groups[node_id] = list(struct.unpack_from(f"<{count}i", data, offset + 4)) if count else []
        elif chunk.identifier == b"nSHP":
            node_id = struct.unpack_from("<i", data, 0)[0]
            _attributes, offset = _read_dict(data, 4)
            count = struct.unpack_from("<i", data, offset)[0]
            offset += 4
            model_ids = []
            for _index in range(count):
                model_id = struct.unpack_from("<i", data, offset)[0]
                offset += 4
                _model_attributes, offset = _read_dict(data, offset)
                model_ids.append(model_id)
            shapes[node_id] = model_ids

    model_offsets = defaultdict(lambda: (0, 0, 0))
    def walk(node_id, offset=(0, 0, 0)):
        if node_id in transforms:
            child, translation = transforms[node_id]
            walk(child, tuple(offset[axis] + translation[axis] for axis in range(3)))
        elif node_id in groups:
            for child in groups[node_id]:
                walk(child, offset)
        elif node_id in shapes:
            for model_id in shapes[node_id]:
                model_offsets[model_id] = offset
    if 0 in transforms or 0 in groups or 0 in shapes:
        walk(0)

    return {
        "version": version,
        "models": models,
        "palette": palette,
        "materials": materials,
        "model_offsets": dict(model_offsets),
        "bytes": len(raw),
    }


def import_vox(context, filepath: str, voxel_size: float) -> tuple[bpy.types.Object, dict[str, object]]:
    parsed = parse_vox(filepath)
    records = []
    next_id = 1
    for model_index, model in enumerate(parsed["models"]):
        offset = parsed["model_offsets"].get(model_index, (0, 0, 0))
        for x, y, z, palette_index in model["voxels"]:
            coordinate = (x + offset[0], y + offset[1], z + offset[2])
            rgba = parsed["palette"][max(0, palette_index - 1)]
            material = parsed["materials"].get(palette_index, {})
            material_type = material.get("_type", "_diffuse")
            roughness = float(material.get("_rough", 0.5))
            metallic = 1.0 if material_type == "_metal" else 0.0
            emission = float(material.get("_flux", 1.0)) if material_type == "_emit" else 0.0
            records.append(
                editable.VoxelRecord(
                    voxel_id=next_id,
                    coord=coordinate,
                    center=tuple(value * voxel_size for value in coordinate),
                    color=_linear_rgba(rgba),
                    size=voxel_size,
                    extent=(voxel_size, voxel_size, voxel_size),
                    palette_index=palette_index,
                    material_id=palette_index,
                    roughness=roughness,
                    metallic=metallic,
                    emission=emission,
                    chunk_id=editable.chunk_id_for_coordinate(coordinate),
                )
            )
            next_id += 1
    if not records:
        raise VoxIOError("VOX file contains no occupied voxels.")
    name = Path(filepath).stem + "_VOX_EDITABLE"
    mesh = bpy.data.meshes.new(name + "_Carrier")
    output = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(output)
    material = core.ensure_colour_material()
    preview.configure_preview(
        output,
        [record.center for record in records],
        [record.color for record in records],
        [record.size for record in records],
        [record.extent for record in records],
        [record.level for record in records],
        1.0,
        material,
    )
    output[editable.GRID_SIZE_TAG] = voxel_size
    output[editable.GRID_ORIGIN_TAG] = (0.0, 0.0, 0.0)
    editable.initialize_carrier(output, reset_delta=True)
    editable.replace_records(output, records)
    settings = context.scene.voxelizer_settings
    settings.palette_slots.clear()
    used_palette_indices = sorted({record.palette_index for record in records})
    for palette_index in range(1, max(used_palette_indices) + 1):
        slot = settings.palette_slots.add()
        slot.name = f"Material {palette_index:03d}"
        slot.color = _linear_rgba(parsed["palette"][max(0, palette_index - 1)])
        material = parsed["materials"].get(palette_index, {})
        material_type = material.get("_type", "_diffuse")
        slot.roughness = float(material.get("_rough", 0.5))
        slot.metallic = 1.0 if material_type == "_metal" else 0.0
        slot.emission = float(material.get("_flux", 1.0)) if material_type == "_emit" else 0.0
    settings.color_mode = "PALETTE"
    settings.palette_active_index = 0
    output[core.TOOL_TAG] = core.TOOL_ID
    output[core.KIND_TAG] = core.PREVIEW_KIND
    output[core.SOURCE_TAG] = "VOX:" + str(filepath)
    for selected in context.selected_objects:
        selected.select_set(False)
    output.select_set(True)
    context.view_layer.objects.active = output
    return output, {
        "version": parsed["version"],
        "models": len(parsed["models"]),
        "voxels": len(records),
        "palette_entries": len({record.palette_index for record in records}),
    }


class VOXELIZER_OT_import_vox(Operator, ImportHelper):
    bl_idname = "voxelizer.import_vox"
    bl_label = "Import MagicaVoxel (.vox)"
    bl_description = "Import a MagicaVoxel .vox file as an editable Chromoxel carrier. 将 MagicaVoxel .vox 文件导入为可编辑 Chromoxel 载体"
    filename_ext = ".vox"
    filter_glob: StringProperty(default="*.vox", options={"HIDDEN"})

    def execute(self, context):
        try:
            output, report = import_vox(
                context,
                self.filepath,
                float(context.scene.voxelizer_settings.vox_import_size),
            )
            self.report({"INFO"}, f"Imported {report['voxels']:,} voxels into {output.name}.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class VOXELIZER_OT_export_vox(Operator, ExportHelper):
    bl_idname = "voxelizer.export_vox"
    bl_label = "Export MagicaVoxel (.vox)"
    bl_description = "Export the active editable carrier to MagicaVoxel .vox with chunked coordinates. 将活动可编辑载体按分块坐标导出为 MagicaVoxel .vox"
    filename_ext = ".vox"
    filter_glob: StringProperty(default="*.vox", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return editable.is_editable(context.active_object)

    def execute(self, context):
        try:
            report = export_vox(context.active_object, self.filepath)
            self.report(
                {"INFO"},
                f"Exported {report['voxels']:,} voxels, {report['palette_entries']} colours, {report['models']} model block(s).",
            )
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


CLASSES = (VOXELIZER_OT_import_vox, VOXELIZER_OT_export_vox)
