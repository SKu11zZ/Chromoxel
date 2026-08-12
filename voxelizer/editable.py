"""Editable point-carrier data model for Chromoxel 0.7.

The source voxelizer remains responsible for sampling.  This module adds a
durable, sparse edit layer on top of Preview points without realizing cubes.
All edit operations are expressed in minimum-cell integer coordinates so they
can be replayed exactly after re-voxelizing with the same grid.
"""

from __future__ import annotations

import json
import math
from array import array
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import bmesh
import bpy
from mathutils import Vector


EDITABLE_TAG = "_chromoxel_editable"
GRID_SIZE_TAG = "_chromoxel_grid_size"
GRID_ORIGIN_TAG = "_chromoxel_grid_origin"
NEXT_ID_TAG = "_chromoxel_next_id"
DELTA_TAG = "_chromoxel_edit_delta_v1"
CHUNK_EDGE_TAG = "_chromoxel_chunk_edge"
CHUNK_POINT_LIMIT_TAG = "_chromoxel_chunk_point_limit"

VOXEL_ID_ATTRIBUTE = "voxel_id"
GRID_X_ATTRIBUTE = "grid_x"
GRID_Y_ATTRIBUTE = "grid_y"
GRID_Z_ATTRIBUTE = "grid_z"
PALETTE_ATTRIBUTE = "palette_index"
MATERIAL_ATTRIBUTE = "material_id"
CHUNK_ATTRIBUTE = "chunk_id"
SOURCE_UV_ATTRIBUTE = "source_uv"
ROUGHNESS_ATTRIBUTE = "voxel_roughness"
METALLIC_ATTRIBUTE = "voxel_metallic"
EMISSION_ATTRIBUTE = "voxel_emission"

CHUNK_EDGE = 32
CHUNK_POINT_LIMIT = 65_536
MODEL_POINT_LIMIT = 100_000


class EditableError(RuntimeError):
    """Raised when an object is not a valid editable voxel carrier."""


@dataclass
class VoxelRecord:
    voxel_id: int
    coord: tuple[int, int, int]
    center: tuple[float, float, float]
    color: tuple[float, float, float, float]
    size: float
    extent: tuple[float, float, float]
    level: int = 0
    palette_index: int = 0
    material_id: int = 0
    roughness: float = 0.5
    metallic: float = 0.0
    emission: float = 0.0
    source_uv: tuple[float, float] = (0.0, 0.0)
    chunk_id: int = 0


def _point_attribute(mesh, name: str, data_type: str):
    attribute = mesh.attributes.get(name)
    if attribute is not None and (
        attribute.domain != "POINT" or attribute.data_type != data_type
    ):
        mesh.attributes.remove(attribute)
        attribute = None
    if attribute is None:
        attribute = mesh.attributes.new(name=name, type=data_type, domain="POINT")
    return attribute


def _colour_attribute(mesh, name: str):
    attribute = mesh.color_attributes.get(name)
    if attribute is not None and (
        attribute.domain != "POINT" or attribute.data_type != "FLOAT_COLOR"
    ):
        mesh.color_attributes.remove(attribute)
        attribute = None
    if attribute is None:
        attribute = mesh.color_attributes.new(
            name=name,
            type="FLOAT_COLOR",
            domain="POINT",
        )
    return attribute


def _int_value(attribute, index: int, default: int = 0) -> int:
    if attribute is None or index >= len(attribute.data):
        return default
    return int(attribute.data[index].value)


def _float_value(attribute, index: int, default: float = 0.0) -> float:
    if attribute is None or index >= len(attribute.data):
        return default
    return float(attribute.data[index].value)


def _vector_value(attribute, index: int, default: Sequence[float]):
    if attribute is None or index >= len(attribute.data):
        return tuple(float(value) for value in default)
    datum = attribute.data[index]
    value = getattr(datum, "vector", getattr(datum, "value", default))
    return tuple(float(component) for component in value)


def _colour_value(attribute, index: int):
    if attribute is None or index >= len(attribute.data):
        return (0.18, 0.48, 0.8, 1.0)
    return tuple(float(value) for value in attribute.data[index].color)


def minimum_grid_size(mesh) -> float:
    size_attribute = mesh.attributes.get("voxel_size")
    values = (
        [float(datum.value) for datum in size_attribute.data]
        if size_attribute is not None
        else []
    )
    positive = [value for value in values if value > 1.0e-9]
    if positive:
        return min(positive)
    if len(mesh.vertices) > 1:
        distances = []
        coordinates = [vertex.co for vertex in mesh.vertices[: min(512, len(mesh.vertices))]]
        for first, second in zip(coordinates, coordinates[1:]):
            delta = (first - second).length
            if delta > 1.0e-9:
                distances.append(delta)
        if distances:
            return min(distances)
    return 1.0


def grid_origin_for_mesh(mesh) -> tuple[float, float, float]:
    if not mesh.vertices:
        return (0.0, 0.0, 0.0)
    return tuple(
        min(float(vertex.co[axis]) for vertex in mesh.vertices)
        for axis in range(3)
    )


def coordinate_for_center(
    center: Sequence[float],
    grid_origin: Sequence[float],
    grid_size: float,
) -> tuple[int, int, int]:
    return tuple(
        int(round((float(center[axis]) - float(grid_origin[axis])) / grid_size))
        for axis in range(3)
    )


def center_for_coordinate(
    coordinate: Sequence[int],
    grid_origin: Sequence[float],
    grid_size: float,
) -> tuple[float, float, float]:
    return tuple(
        float(grid_origin[axis]) + int(coordinate[axis]) * grid_size
        for axis in range(3)
    )


def chunk_coordinate(coordinate: Sequence[int]) -> tuple[int, int, int]:
    return tuple(math.floor(int(value) / CHUNK_EDGE) for value in coordinate)


def chunk_id_for_coordinate(coordinate: Sequence[int]) -> int:
    # Signed 10-bit coordinates packed into a stable positive 30-bit ID.
    x, y, z = (value & 0x3FF for value in chunk_coordinate(coordinate))
    return int(x | (y << 10) | (z << 20))


def load_delta(output: bpy.types.Object) -> list[dict[str, object]]:
    raw = str(output.get(DELTA_TAG, "[]"))
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EditableError("Editable voxel delta is corrupt.") from exc
    if not isinstance(value, list):
        raise EditableError("Editable voxel delta is not a list.")
    return [entry for entry in value if isinstance(entry, dict)]


def save_delta(output: bpy.types.Object, operations: Sequence[dict[str, object]]) -> None:
    output[DELTA_TAG] = json.dumps(
        list(operations),
        separators=(",", ":"),
        ensure_ascii=True,
    )


def append_delta(output: bpy.types.Object, operation: dict[str, object]) -> None:
    operations = load_delta(output)
    operations.append(operation)
    save_delta(output, operations)


def is_editable(output: bpy.types.Object | None) -> bool:
    return bool(
        output is not None
        and output.type == "MESH"
        and output.get(EDITABLE_TAG, False)
        and len(output.data.polygons) == 0
        and output.data.attributes.get(VOXEL_ID_ATTRIBUTE) is not None
    )


def initialize_carrier(
    output: bpy.types.Object,
    *,
    reset_delta: bool = False,
    coordinate_ordered: bool = False,
) -> int:
    """Add durable editable attributes to an existing Preview carrier."""

    mesh = output.data
    if output.type != "MESH" or len(mesh.polygons) != 0:
        raise EditableError("Editable voxels require a point-only Preview carrier.")
    point_count = len(mesh.vertices)
    grid_size = float(output.get(GRID_SIZE_TAG, 0.0))
    if grid_size <= 0.0:
        grid_size = minimum_grid_size(mesh)
    origin = output.get(GRID_ORIGIN_TAG)
    if not isinstance(origin, (list, tuple)) or len(origin) != 3:
        origin = grid_origin_for_mesh(mesh)
    origin = tuple(float(value) for value in origin)

    ids = _point_attribute(mesh, VOXEL_ID_ATTRIBUTE, "INT")
    xs = _point_attribute(mesh, GRID_X_ATTRIBUTE, "INT")
    ys = _point_attribute(mesh, GRID_Y_ATTRIBUTE, "INT")
    zs = _point_attribute(mesh, GRID_Z_ATTRIBUTE, "INT")
    palettes = _point_attribute(mesh, PALETTE_ATTRIBUTE, "INT")
    materials = _point_attribute(mesh, MATERIAL_ATTRIBUTE, "INT")
    chunks = _point_attribute(mesh, CHUNK_ATTRIBUTE, "INT")
    _point_attribute(mesh, SOURCE_UV_ATTRIBUTE, "FLOAT2")
    roughness = _point_attribute(mesh, ROUGHNESS_ATTRIBUTE, "FLOAT")
    metallic = _point_attribute(mesh, METALLIC_ATTRIBUTE, "FLOAT")
    emission = _point_attribute(mesh, EMISSION_ATTRIBUTE, "FLOAT")

    existing_ids = array("i", [0]) * point_count
    ids.data.foreach_get("value", existing_ids)
    coordinates = [
        coordinate_for_center(vertex.co, origin, grid_size)
        for vertex in mesh.vertices
    ]
    if coordinate_ordered:
        # Core sampling emits z/y/x lattice order.  New carriers can therefore
        # assign the same stable 1-based IDs without an O(N log N) sort.  Old
        # or externally edited carriers keep the conservative sorting path.
        generated_ids = None
    else:
        sorted_indices = sorted(range(point_count), key=lambda index: coordinates[index])
        generated_ids = {index: order + 1 for order, index in enumerate(sorted_indices)}
    id_values = array(
        "i",
        (
            int(existing_ids[index])
            if int(existing_ids[index]) > 0
            else index + 1
            if generated_ids is None
            else generated_ids[index]
            for index in range(point_count)
        ),
    )
    ids.data.foreach_set("value", id_values)
    xs.data.foreach_set("value", array("i", (coordinate[0] for coordinate in coordinates)))
    ys.data.foreach_set("value", array("i", (coordinate[1] for coordinate in coordinates)))
    zs.data.foreach_set("value", array("i", (coordinate[2] for coordinate in coordinates)))

    palette_values = array("i", [0]) * point_count
    material_values = array("i", [0]) * point_count
    roughness_values = array("f", [0.0]) * point_count
    metallic_values = array("f", [0.0]) * point_count
    emission_values = array("f", [0.0]) * point_count
    palettes.data.foreach_get("value", palette_values)
    materials.data.foreach_get("value", material_values)
    roughness.data.foreach_get("value", roughness_values)
    metallic.data.foreach_get("value", metallic_values)
    emission.data.foreach_get("value", emission_values)
    palettes.data.foreach_set("value", array("i", (max(0, value) for value in palette_values)))
    materials.data.foreach_set("value", array("i", (max(0, value) for value in material_values)))
    chunks.data.foreach_set(
        "value",
        array("i", (chunk_id_for_coordinate(coordinate) for coordinate in coordinates)),
    )
    roughness.data.foreach_set(
        "value",
        array("f", (0.5 if float(value) == 0.0 else value for value in roughness_values)),
    )
    metallic.data.foreach_set(
        "value",
        array("f", (max(0.0, min(1.0, value)) for value in metallic_values)),
    )
    emission.data.foreach_set(
        "value",
        array("f", (max(0.0, value) for value in emission_values)),
    )

    output[EDITABLE_TAG] = True
    output[GRID_SIZE_TAG] = grid_size
    output[GRID_ORIGIN_TAG] = origin
    output[NEXT_ID_TAG] = max(
        list(id_values) + [0]
    ) + 1
    output[CHUNK_EDGE_TAG] = CHUNK_EDGE
    output[CHUNK_POINT_LIMIT_TAG] = CHUNK_POINT_LIMIT
    if reset_delta or DELTA_TAG not in output:
        save_delta(output, [])
    mesh.update()
    return point_count


def records_from_object(output: bpy.types.Object) -> list[VoxelRecord]:
    if not is_editable(output):
        initialize_carrier(output)
    mesh = output.data
    ids = mesh.attributes.get(VOXEL_ID_ATTRIBUTE)
    xs = mesh.attributes.get(GRID_X_ATTRIBUTE)
    ys = mesh.attributes.get(GRID_Y_ATTRIBUTE)
    zs = mesh.attributes.get(GRID_Z_ATTRIBUTE)
    colours = mesh.color_attributes.get("voxel_color")
    sizes = mesh.attributes.get("voxel_size")
    extents = mesh.attributes.get("voxel_extent")
    levels = mesh.attributes.get("voxel_level")
    palettes = mesh.attributes.get(PALETTE_ATTRIBUTE)
    materials = mesh.attributes.get(MATERIAL_ATTRIBUTE)
    chunks = mesh.attributes.get(CHUNK_ATTRIBUTE)
    source_uv = mesh.attributes.get(SOURCE_UV_ATTRIBUTE)
    roughness = mesh.attributes.get(ROUGHNESS_ATTRIBUTE)
    metallic = mesh.attributes.get(METALLIC_ATTRIBUTE)
    emission = mesh.attributes.get(EMISSION_ATTRIBUTE)
    grid_size = float(output[GRID_SIZE_TAG])

    records = []
    for index, vertex in enumerate(mesh.vertices):
        coordinate = (
            _int_value(xs, index),
            _int_value(ys, index),
            _int_value(zs, index),
        )
        records.append(
            VoxelRecord(
                voxel_id=_int_value(ids, index, index + 1),
                coord=coordinate,
                center=tuple(float(value) for value in vertex.co),
                color=_colour_value(colours, index),
                size=_float_value(sizes, index, grid_size),
                extent=_vector_value(extents, index, (grid_size,) * 3),
                level=_int_value(levels, index),
                palette_index=_int_value(palettes, index),
                material_id=_int_value(materials, index),
                roughness=_float_value(roughness, index, 0.5),
                metallic=_float_value(metallic, index),
                emission=_float_value(emission, index),
                source_uv=_vector_value(source_uv, index, (0.0, 0.0))[:2],
                chunk_id=_int_value(chunks, index, chunk_id_for_coordinate(coordinate)),
            )
        )
    return records


def _record_payload(record: VoxelRecord) -> dict[str, object]:
    payload = asdict(record)
    for key in ("coord", "center", "color", "extent", "source_uv"):
        payload[key] = list(payload[key])
    return payload


def record_payload(record: VoxelRecord) -> dict[str, object]:
    """Return a JSON-safe representation used by batch edit operations."""

    return _record_payload(record)


def record_from_payload(payload: dict[str, object]) -> VoxelRecord:
    return VoxelRecord(
        voxel_id=int(payload["voxel_id"]),
        coord=tuple(int(value) for value in payload["coord"]),
        center=tuple(float(value) for value in payload["center"]),
        color=tuple(float(value) for value in payload["color"]),
        size=float(payload["size"]),
        extent=tuple(float(value) for value in payload["extent"]),
        level=int(payload.get("level", 0)),
        palette_index=int(payload.get("palette_index", 0)),
        material_id=int(payload.get("material_id", 0)),
        roughness=float(payload.get("roughness", 0.5)),
        metallic=float(payload.get("metallic", 0.0)),
        emission=float(payload.get("emission", 0.0)),
        source_uv=tuple(float(value) for value in payload.get("source_uv", (0.0, 0.0))),
        chunk_id=int(payload.get("chunk_id", 0)),
    )


def apply_delta(
    records: Iterable[VoxelRecord],
    operations: Sequence[dict[str, object]],
    *,
    grid_origin: Sequence[float],
    grid_size: float,
) -> list[VoxelRecord]:
    """Replay edits by exact integer coordinates; later edits overwrite earlier."""

    by_coordinate = {tuple(record.coord): record for record in records}
    for operation in operations:
        kind = str(operation.get("op", ""))
        if kind == "DELETE_SET":
            for value in operation.get("coords", ()):
                coordinate = tuple(int(component) for component in value)
                if len(coordinate) == 3:
                    by_coordinate.pop(coordinate, None)
            continue
        if kind == "ADD_SET":
            for payload in operation.get("records", ()):
                if not isinstance(payload, dict):
                    continue
                record = record_from_payload(payload)
                record.center = center_for_coordinate(record.coord, grid_origin, grid_size)
                record.chunk_id = chunk_id_for_coordinate(record.coord)
                by_coordinate[record.coord] = record
            continue
        if kind == "MOVE_SET":
            entries = []
            for value in operation.get("moves", ()):
                if not isinstance(value, dict):
                    continue
                source_coordinate = tuple(int(component) for component in value.get("coord", ()))
                destination = tuple(int(component) for component in value.get("to", ()))
                if len(source_coordinate) == 3 and len(destination) == 3:
                    entries.append((source_coordinate, destination))
            moved = [(by_coordinate.pop(source, None), destination) for source, destination in entries]
            for record, destination in moved:
                if record is None:
                    continue
                record.coord = destination
                record.center = center_for_coordinate(destination, grid_origin, grid_size)
                record.chunk_id = chunk_id_for_coordinate(destination)
                by_coordinate[destination] = record
            continue
        if kind == "PAINT_SET":
            colour = tuple(float(value) for value in operation.get("color", (0.18, 0.48, 0.8, 1.0)))
            palette_index = int(operation.get("palette_index", 0))
            for value in operation.get("coords", ()):
                coordinate = tuple(int(component) for component in value)
                record = by_coordinate.get(coordinate)
                if record is not None:
                    record.color = colour
                    record.palette_index = palette_index
            continue
        if kind == "MATERIAL_SET":
            for value in operation.get("coords", ()):
                coordinate = tuple(int(component) for component in value)
                record = by_coordinate.get(coordinate)
                if record is not None:
                    record.material_id = int(operation.get("material_id", record.material_id))
                    record.roughness = float(operation.get("roughness", record.roughness))
                    record.metallic = float(operation.get("metallic", record.metallic))
                    record.emission = float(operation.get("emission", record.emission))
            continue
        coordinate = tuple(int(value) for value in operation.get("coord", ()))
        if len(coordinate) != 3:
            continue
        if kind == "DELETE":
            by_coordinate.pop(coordinate, None)
        elif kind == "ADD":
            payload = operation.get("record")
            if isinstance(payload, dict):
                record = record_from_payload(payload)
                record.center = center_for_coordinate(record.coord, grid_origin, grid_size)
                record.chunk_id = chunk_id_for_coordinate(record.coord)
                by_coordinate[record.coord] = record
        elif kind == "MOVE":
            destination = tuple(int(value) for value in operation.get("to", ()))
            if len(destination) != 3:
                continue
            record = by_coordinate.pop(coordinate, None)
            if record is not None:
                record.coord = destination
                record.center = center_for_coordinate(destination, grid_origin, grid_size)
                record.chunk_id = chunk_id_for_coordinate(destination)
                by_coordinate[destination] = record
        elif kind == "PAINT":
            record = by_coordinate.get(coordinate)
            if record is not None:
                colour = operation.get("color", record.color)
                record.color = tuple(float(value) for value in colour)
                record.palette_index = int(operation.get("palette_index", record.palette_index))
        elif kind == "MATERIAL":
            record = by_coordinate.get(coordinate)
            if record is not None:
                record.material_id = int(operation.get("material_id", record.material_id))
                record.roughness = float(operation.get("roughness", record.roughness))
                record.metallic = float(operation.get("metallic", record.metallic))
                record.emission = float(operation.get("emission", record.emission))
    return sorted(by_coordinate.values(), key=lambda item: item.coord)


def selected_indices(output: bpy.types.Object) -> list[int]:
    if output.mode == "EDIT":
        bm = bmesh.from_edit_mesh(output.data)
        bm.verts.ensure_lookup_table()
        return [vertex.index for vertex in bm.verts if vertex.select]
    return [vertex.index for vertex in output.data.vertices if vertex.select]


def replace_records(
    output: bpy.types.Object,
    records: Sequence[VoxelRecord],
    *,
    selected_ids: Iterable[int] = (),
) -> None:
    """Replace the point mesh while keeping the object's GN modifier and tags."""

    old_mesh = output.data
    mesh = bpy.data.meshes.new(f"{output.name}_EditableCarrier")
    mesh.from_pydata([record.center for record in records], (), ())
    mesh.update()
    colours = _colour_attribute(mesh, "voxel_color")
    sizes = _point_attribute(mesh, "voxel_size", "FLOAT")
    extents = _point_attribute(mesh, "voxel_extent", "FLOAT_VECTOR")
    levels = _point_attribute(mesh, "voxel_level", "INT")
    ids = _point_attribute(mesh, VOXEL_ID_ATTRIBUTE, "INT")
    xs = _point_attribute(mesh, GRID_X_ATTRIBUTE, "INT")
    ys = _point_attribute(mesh, GRID_Y_ATTRIBUTE, "INT")
    zs = _point_attribute(mesh, GRID_Z_ATTRIBUTE, "INT")
    palettes = _point_attribute(mesh, PALETTE_ATTRIBUTE, "INT")
    materials = _point_attribute(mesh, MATERIAL_ATTRIBUTE, "INT")
    chunks = _point_attribute(mesh, CHUNK_ATTRIBUTE, "INT")
    uvs = _point_attribute(mesh, SOURCE_UV_ATTRIBUTE, "FLOAT2")
    roughness = _point_attribute(mesh, ROUGHNESS_ATTRIBUTE, "FLOAT")
    metallic = _point_attribute(mesh, METALLIC_ATTRIBUTE, "FLOAT")
    emission = _point_attribute(mesh, EMISSION_ATTRIBUTE, "FLOAT")

    selected = set(int(value) for value in selected_ids)
    colours.data.foreach_set(
        "color",
        array("f", (value for record in records for value in record.color)),
    )
    sizes.data.foreach_set("value", array("f", (record.size for record in records)))
    extents.data.foreach_set(
        "vector",
        array("f", (value for record in records for value in record.extent)),
    )
    levels.data.foreach_set("value", array("i", (record.level for record in records)))
    ids.data.foreach_set("value", array("i", (record.voxel_id for record in records)))
    xs.data.foreach_set("value", array("i", (record.coord[0] for record in records)))
    ys.data.foreach_set("value", array("i", (record.coord[1] for record in records)))
    zs.data.foreach_set("value", array("i", (record.coord[2] for record in records)))
    palettes.data.foreach_set("value", array("i", (record.palette_index for record in records)))
    materials.data.foreach_set("value", array("i", (record.material_id for record in records)))
    chunks.data.foreach_set("value", array("i", (record.chunk_id for record in records)))
    uvs.data.foreach_set(
        "vector",
        array("f", (value for record in records for value in record.source_uv)),
    )
    roughness.data.foreach_set("value", array("f", (record.roughness for record in records)))
    metallic.data.foreach_set("value", array("f", (record.metallic for record in records)))
    emission.data.foreach_set("value", array("f", (record.emission for record in records)))
    mesh.vertices.foreach_set(
        "select",
        [record.voxel_id in selected for record in records],
    )

    output.data = mesh
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    output[NEXT_ID_TAG] = max([record.voxel_id for record in records] + [0]) + 1
    mesh.update()


def new_record_at(
    output: bpy.types.Object,
    coordinate: Sequence[int],
    color: Sequence[float],
    *,
    palette_index: int = 0,
    material_id: int = 0,
    roughness: float = 0.5,
    metallic: float = 0.0,
    emission: float = 0.0,
) -> VoxelRecord:
    grid_size = float(output[GRID_SIZE_TAG])
    origin = tuple(float(value) for value in output[GRID_ORIGIN_TAG])
    voxel_id = int(output.get(NEXT_ID_TAG, 1))
    output[NEXT_ID_TAG] = voxel_id + 1
    coordinate = tuple(int(value) for value in coordinate)
    return VoxelRecord(
        voxel_id=voxel_id,
        coord=coordinate,
        center=center_for_coordinate(coordinate, origin, grid_size),
        color=tuple(float(value) for value in color),
        size=grid_size,
        extent=(grid_size, grid_size, grid_size),
        palette_index=palette_index,
        material_id=material_id,
        roughness=roughness,
        metallic=metallic,
        emission=emission,
        chunk_id=chunk_id_for_coordinate(coordinate),
    )


def add_operation(record: VoxelRecord) -> dict[str, object]:
    return {"op": "ADD", "coord": list(record.coord), "record": _record_payload(record)}


def validate_editable(output: bpy.types.Object) -> dict[str, int | float | bool]:
    records = records_from_object(output)
    coordinates = [record.coord for record in records]
    ids = [record.voxel_id for record in records]
    return {
        "editable": is_editable(output),
        "voxels": len(records),
        "unique_coordinates": len(set(coordinates)),
        "unique_ids": len(set(ids)),
        "duplicate_coordinates": len(records) - len(set(coordinates)),
        "duplicate_ids": len(records) - len(set(ids)),
        "chunks": len({record.chunk_id for record in records}),
        "grid_size": float(output.get(GRID_SIZE_TAG, 0.0)),
        "within_model_limit": len(records) <= MODEL_POINT_LIMIT,
    }
