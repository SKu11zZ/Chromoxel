"""Editable voxel Bake backends: cubes, surface faces, and greedy quads."""

from __future__ import annotations

from array import array
from collections import defaultdict
from dataclasses import replace
from typing import Iterable, Sequence

import bpy
from mathutils import Vector

from . import core, editable


FACE_DIRECTIONS = (
    ((-1, 0, 0), (0, 4, 6, 2)),
    ((1, 0, 0), (1, 3, 7, 5)),
    ((0, -1, 0), (0, 1, 5, 4)),
    ((0, 1, 0), (2, 6, 7, 3)),
    ((0, 0, -1), (0, 2, 3, 1)),
    ((0, 0, 1), (4, 5, 7, 6)),
)
CUBE_CORNERS = (
    (-1, -1, -1),
    (1, -1, -1),
    (-1, 1, -1),
    (1, 1, -1),
    (-1, -1, 1),
    (1, -1, 1),
    (-1, 1, 1),
    (1, 1, 1),
)


def atomic_records(
    records: Iterable[editable.VoxelRecord],
    grid_size: float,
    grid_origin: Sequence[float],
) -> list[editable.VoxelRecord]:
    """Expand variable extents into a deduplicated minimum-cell grid."""

    records = list(records)
    result = {}
    next_id = max([record.voxel_id for record in records] + [0]) + 1
    for source in sorted(records, key=lambda item: (item.level, item.voxel_id)):
        counts = tuple(
            max(1, int(round(float(source.extent[axis]) / grid_size)))
            for axis in range(3)
        )
        first_center = tuple(
            float(source.center[axis]) - (counts[axis] - 1) * grid_size * 0.5
            for axis in range(3)
        )
        for x in range(counts[0]):
            for y in range(counts[1]):
                for z in range(counts[2]):
                    center = (
                        first_center[0] + x * grid_size,
                        first_center[1] + y * grid_size,
                        first_center[2] + z * grid_size,
                    )
                    coordinate = editable.coordinate_for_center(center, grid_origin, grid_size)
                    existing = result.get(coordinate)
                    voxel_id = existing.voxel_id if existing is not None else next_id
                    if existing is None:
                        next_id += 1
                    result[coordinate] = replace(
                        source,
                        voxel_id=voxel_id,
                        coord=coordinate,
                        center=editable.center_for_coordinate(coordinate, grid_origin, grid_size),
                        size=grid_size,
                        extent=(grid_size, grid_size, grid_size),
                        level=max(source.level, 0),
                        chunk_id=editable.chunk_id_for_coordinate(coordinate),
                    )
    return sorted(result.values(), key=lambda item: item.coord)


def _write_face_attributes(mesh, face_records):
    colour = mesh.color_attributes.new(
        name=core.COLOUR_ATTRIBUTE,
        type="FLOAT_COLOR",
        domain="CORNER",
    )
    size = mesh.attributes.new(name=core.SIZE_ATTRIBUTE, type="FLOAT", domain="FACE")
    extent = mesh.attributes.new(name=core.EXTENT_ATTRIBUTE, type="FLOAT_VECTOR", domain="FACE")
    level = mesh.attributes.new(name=core.LEVEL_ATTRIBUTE, type="INT", domain="FACE")
    voxel_id = mesh.attributes.new(name=editable.VOXEL_ID_ATTRIBUTE, type="INT", domain="FACE")
    palette = mesh.attributes.new(name=editable.PALETTE_ATTRIBUTE, type="INT", domain="FACE")
    material = mesh.attributes.new(name=editable.MATERIAL_ATTRIBUTE, type="INT", domain="FACE")
    chunk = mesh.attributes.new(name=editable.CHUNK_ATTRIBUTE, type="INT", domain="FACE")
    roughness = mesh.attributes.new(name=editable.ROUGHNESS_ATTRIBUTE, type="FLOAT", domain="FACE")
    metallic = mesh.attributes.new(name=editable.METALLIC_ATTRIBUTE, type="FLOAT", domain="FACE")
    emission = mesh.attributes.new(name=editable.EMISSION_ATTRIBUTE, type="FLOAT", domain="FACE")
    source_uv = mesh.attributes.new(name=editable.SOURCE_UV_ATTRIBUTE, type="FLOAT2", domain="FACE")
    records = list(face_records)
    size.data.foreach_set("value", array("f", (record.size for record in records)))
    extent.data.foreach_set(
        "vector",
        array("f", (component for record in records for component in record.extent)),
    )
    level.data.foreach_set("value", array("i", (record.level for record in records)))
    voxel_id.data.foreach_set("value", array("i", (record.voxel_id for record in records)))
    palette.data.foreach_set("value", array("i", (record.palette_index for record in records)))
    material.data.foreach_set("value", array("i", (record.material_id for record in records)))
    chunk.data.foreach_set("value", array("i", (record.chunk_id for record in records)))
    roughness.data.foreach_set("value", array("f", (record.roughness for record in records)))
    metallic.data.foreach_set("value", array("f", (record.metallic for record in records)))
    emission.data.foreach_set("value", array("f", (record.emission for record in records)))
    source_uv.data.foreach_set(
        "vector",
        array("f", (component for record in records for component in record.source_uv)),
    )
    colour.data.foreach_set(
        "color",
        array(
            "f",
            (
                component
                for polygon, record in zip(mesh.polygons, records)
                for _loop_index in polygon.loop_indices
                for component in record.color
            ),
        ),
    )
    mesh.materials.append(core.ensure_colour_material())
    mesh.update()


def build_realized_cubes(
    records: Sequence[editable.VoxelRecord],
    mesh_name: str,
    *,
    fill_ratio: float = 1.0,
) -> bpy.types.Mesh:
    vertices = []
    faces = []
    face_records = []
    for record in records:
        half = Vector(record.extent) * max(1.0e-6, min(1.0, fill_ratio)) * 0.5
        first = len(vertices)
        vertices.extend(
            (
                record.center[0] + sign[0] * half.x,
                record.center[1] + sign[1] * half.y,
                record.center[2] + sign[2] * half.z,
            )
            for sign in CUBE_CORNERS
        )
        for _direction, indices in FACE_DIRECTIONS:
            faces.append(tuple(first + index for index in indices))
            face_records.append(record)
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    _write_face_attributes(mesh, face_records)
    return mesh


def build_surface_mesh(
    records: Sequence[editable.VoxelRecord],
    mesh_name: str,
    grid_size: float,
) -> bpy.types.Mesh:
    occupancy = {record.coord: record for record in records}
    vertices = []
    faces = []
    face_records = []
    half = grid_size * 0.5
    for record in records:
        corners = [
            (
                record.center[0] + sign[0] * half,
                record.center[1] + sign[1] * half,
                record.center[2] + sign[2] * half,
            )
            for sign in CUBE_CORNERS
        ]
        for direction, indices in FACE_DIRECTIONS:
            neighbour = tuple(record.coord[axis] + direction[axis] for axis in range(3))
            if neighbour in occupancy:
                continue
            first = len(vertices)
            vertices.extend(corners[index] for index in indices)
            faces.append(tuple(first + index for index in range(4)))
            face_records.append(record)
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    _write_face_attributes(mesh, face_records)
    return mesh


def _material_key(record: editable.VoxelRecord):
    return (
        tuple(round(float(value), 6) for value in record.color),
        record.palette_index,
        record.material_id,
        round(record.roughness, 6),
        round(record.metallic, 6),
        round(record.emission, 6),
    )


def _greedy_rectangles(cells):
    remaining = dict(cells)
    # Sorting once avoids the previous repeated min(remaining.items()) scan,
    # which became quadratic on textured 100k-voxel meshes.
    for u0, v0 in sorted(remaining):
        record = remaining.get((u0, v0))
        if record is None:
            continue
        key = _material_key(record)
        width = 1
        while (u0 + width, v0) in remaining and _material_key(remaining[(u0 + width, v0)]) == key:
            width += 1
        height = 1
        while True:
            row = [(u0 + offset, v0 + height) for offset in range(width)]
            if not all(cell in remaining and _material_key(remaining[cell]) == key for cell in row):
                break
            height += 1
        for u in range(u0, u0 + width):
            for v in range(v0, v0 + height):
                remaining.pop((u, v), None)
        yield u0, v0, width, height, record


def build_greedy_mesh(
    records: Sequence[editable.VoxelRecord],
    mesh_name: str,
    grid_size: float,
    grid_origin: Sequence[float],
) -> bpy.types.Mesh:
    occupancy = {record.coord: record for record in records}
    planes = defaultdict(dict)
    for record in records:
        x, y, z = record.coord
        for axis in range(3):
            other_axes = [value for value in range(3) if value != axis]
            for sign in (-1, 1):
                neighbour = list(record.coord)
                neighbour[axis] += sign
                if tuple(neighbour) in occupancy:
                    continue
                plane = record.coord[axis] + (1 if sign > 0 else 0)
                u = record.coord[other_axes[0]]
                v = record.coord[other_axes[1]]
                planes[(axis, sign, plane)][(u, v)] = record

    vertices = []
    faces = []
    face_records = []
    for (axis, sign, plane), cells in sorted(planes.items()):
        other_axes = [value for value in range(3) if value != axis]
        for u, v, width, height, record in _greedy_rectangles(cells):
            boundary = float(grid_origin[axis]) + (plane - 0.5) * grid_size
            u_min = float(grid_origin[other_axes[0]]) + (u - 0.5) * grid_size
            u_max = u_min + width * grid_size
            v_min = float(grid_origin[other_axes[1]]) + (v - 0.5) * grid_size
            v_max = v_min + height * grid_size
            points = []
            for first, second in ((u_min, v_min), (u_max, v_min), (u_max, v_max), (u_min, v_max)):
                point = [0.0, 0.0, 0.0]
                point[axis] = boundary
                point[other_axes[0]] = first
                point[other_axes[1]] = second
                points.append(tuple(point))
            if sign < 0:
                points.reverse()
            first_vertex = len(vertices)
            vertices.extend(points)
            faces.append(tuple(first_vertex + index for index in range(4)))
            face_records.append(record)

    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    _write_face_attributes(mesh, face_records)
    return mesh


def build_from_editable(
    output: bpy.types.Object,
    mode: str,
    mesh_name: str,
    *,
    fill_ratio: float = 1.0,
) -> tuple[bpy.types.Mesh, int]:
    records = editable.records_from_object(output)
    grid_size = float(output[editable.GRID_SIZE_TAG])
    origin = tuple(output[editable.GRID_ORIGIN_TAG])
    if mode == "REALIZED":
        return build_realized_cubes(records, mesh_name, fill_ratio=fill_ratio), len(records)
    atoms = atomic_records(records, grid_size, origin)
    if mode == "SURFACE":
        return build_surface_mesh(atoms, mesh_name, grid_size), len(atoms)
    if mode == "GREEDY":
        return build_greedy_mesh(atoms, mesh_name, grid_size, origin), len(atoms)
    raise editable.EditableError(f"Unsupported editable Bake mode: {mode}")
