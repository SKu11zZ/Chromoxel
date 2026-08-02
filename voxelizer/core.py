"""Geometry and data-safety core for Textured Voxelizer MVP.

The public functions in this module contain no UI state.  They build realized
cube meshes, tag only add-on-owned outputs, and refuse name collisions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import product
from typing import Iterable, Iterator, Optional

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


TOOL_ID = "org.openai.textured_voxelizer_mvp"
TOOL_TAG = "_textured_voxelizer_tool"
KIND_TAG = "_textured_voxelizer_kind"
SOURCE_TAG = "_textured_voxelizer_source"
PREVIEW_KIND = "preview"
BAKE_KIND = "bake"
HELPER_KIND = "watertight_helper"
COLOUR_ATTRIBUTE = "voxel_color"
MATERIAL_NAME = ".BTVM_voxel_color"
SOURCE_SIGNATURE_TAG = "_textured_voxelizer_source_signature"
REPAIR_SIZE_TAG = "_textured_voxelizer_repair_voxel_size"
SOURCE_SYMMETRY_TAG = "_textured_voxelizer_source_symmetry"
HELPER_SYMMETRY_TAG = "_textured_voxelizer_helper_symmetry"
SAMPLING_DIAGNOSTICS_TAG = "_textured_voxelizer_sampling_diagnostics"
MAX_GRID_SAMPLES = 1_500_000
MAX_VOXELS = 250_000
DEFAULT_CACHE_MEMORY_MB = 128
DEFAULT_CHUNK_SIZE = 4096
SYMMETRY_RELATIVE_TOLERANCE = 1.0e-6
SYMMETRY_ABSOLUTE_FLOOR = 1.0e-7
SYMMETRY_SCHEMA_VERSION = 2
_AXIS_NAMES = ("X", "Y", "Z")
_LAST_SAMPLING_DIAGNOSTICS: dict[int, dict[str, object]] = {}
_SAMPLE_CACHE: OrderedDict[str, dict[str, object]] = OrderedDict()
_SAMPLE_CACHE_BYTES = 0


class VoxelizerError(RuntimeError):
    """A concise validation failure suitable for an operator report."""


@dataclass(frozen=True)
class SamplingProgress:
    """One resumable sampling progress update."""

    phase: str
    completed: int
    total: int
    message: str

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.completed / self.total))


def _setting_int(settings, name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(getattr(settings, name, default)))
    except (AttributeError, TypeError, ValueError):
        return max(minimum, int(default))


def sample_budget(settings) -> int:
    return _setting_int(settings, "sample_budget", MAX_GRID_SAMPLES, 1_000)


def voxel_budget(settings) -> int:
    return _setting_int(settings, "voxel_budget", MAX_VOXELS, 1_000)


def sampling_chunk_size(settings) -> int:
    return _setting_int(settings, "sampling_chunk_size", DEFAULT_CHUNK_SIZE, 128)


def cache_budget_bytes(settings) -> int:
    megabytes = _setting_int(
        settings,
        "cache_memory_mb",
        DEFAULT_CACHE_MEMORY_MB,
        16,
    )
    return megabytes * 1024 * 1024


def clear_sampling_cache() -> None:
    global _SAMPLE_CACHE_BYTES
    _SAMPLE_CACHE.clear()
    _SAMPLE_CACHE_BYTES = 0


def sampling_cache_stats() -> dict[str, int]:
    return {
        "entries": len(_SAMPLE_CACHE),
        "bytes": int(_SAMPLE_CACHE_BYTES),
    }


def _cache_get(key: str):
    entry = _SAMPLE_CACHE.get(key)
    if entry is not None:
        _SAMPLE_CACHE.move_to_end(key)
    return entry


def _cache_put(
    key: str,
    centres: Iterable[Iterable[float]],
    colours: Iterable[Iterable[float]],
    used_image: bool,
    diagnostics: dict[str, object],
    settings,
) -> None:
    global _SAMPLE_CACHE_BYTES
    centre_values = tuple(
        tuple(float(component) for component in centre)
        for centre in centres
    )
    colour_values = tuple(
        tuple(float(component) for component in colour)
        for colour in colours
    )
    estimated_bytes = len(centre_values) * 80
    budget = cache_budget_bytes(settings)
    if estimated_bytes > budget:
        return
    previous = _SAMPLE_CACHE.pop(key, None)
    if previous is not None:
        _SAMPLE_CACHE_BYTES -= int(previous["estimated_bytes"])
    while _SAMPLE_CACHE and _SAMPLE_CACHE_BYTES + estimated_bytes > budget:
        _old_key, old = _SAMPLE_CACHE.popitem(last=False)
        _SAMPLE_CACHE_BYTES -= int(old["estimated_bytes"])
    _SAMPLE_CACHE[key] = {
        "centres": centre_values,
        "colours": colour_values,
        "used_image": bool(used_image),
        "diagnostics": json.loads(json.dumps(diagnostics)),
        "estimated_bytes": estimated_bytes,
    }
    _SAMPLE_CACHE_BYTES += estimated_bytes


def _canonical_cycle(indices: Iterable[int]) -> tuple[int, ...]:
    """Canonicalize a face boundary independent of start and winding."""

    values = tuple(int(index) for index in indices)
    if not values:
        return values
    reverse = tuple(reversed(values))
    candidates = [
        values[offset:] + values[:offset]
        for offset in range(len(values))
    ]
    candidates.extend(
        reverse[offset:] + reverse[:offset]
        for offset in range(len(reverse))
    )
    return min(candidates)


def _symmetry_bounds(
    mesh: bpy.types.Mesh,
) -> tuple[Vector, Vector, float, float]:
    if not mesh.vertices:
        origin = Vector((0.0, 0.0, 0.0))
        return origin.copy(), origin.copy(), 0.0, SYMMETRY_ABSOLUTE_FLOOR
    bounds_min = Vector(
        tuple(
            min(float(vertex.co[axis]) for vertex in mesh.vertices)
            for axis in range(3)
        )
    )
    bounds_max = Vector(
        tuple(
            max(float(vertex.co[axis]) for vertex in mesh.vertices)
            for axis in range(3)
        )
    )
    diagonal = float((bounds_max - bounds_min).length)
    tolerance = max(
        diagonal * SYMMETRY_RELATIVE_TOLERANCE,
        SYMMETRY_ABSOLUTE_FLOOR,
    )
    return bounds_min, bounds_max, diagonal, tolerance


def _spatial_key(coordinate: Iterable[float], tolerance: float) -> tuple[int, int, int]:
    return tuple(
        int(math.floor(float(value) / tolerance))
        for value in coordinate
    )


def _reflection_vertex_map(
    mesh: bpy.types.Mesh,
    axis: int,
    plane: float,
    tolerance: float,
) -> tuple[Optional[tuple[int, ...]], str, dict[str, object]]:
    buckets: dict[tuple[int, int, int], list[int]] = {}
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    for index, coordinate in enumerate(coordinates):
        buckets.setdefault(_spatial_key(coordinate, tolerance), []).append(index)

    neighbours: list[set[int]] = [set() for _vertex in mesh.vertices]
    edge_face_counts: Counter[tuple[int, int]] = Counter()
    incident_face_sizes: list[list[int]] = [[] for _vertex in mesh.vertices]
    for edge in mesh.edges:
        first, second = (int(value) for value in edge.vertices)
        neighbours[first].add(second)
        neighbours[second].add(first)
    for polygon in mesh.polygons:
        polygon_indices = tuple(int(index) for index in polygon.vertices)
        for index in polygon_indices:
            incident_face_sizes[index].append(len(polygon_indices))
        for offset, first in enumerate(polygon_indices):
            second = polygon_indices[(offset + 1) % len(polygon_indices)]
            edge_face_counts[tuple(sorted((first, second)))] += 1

    def local_signature(index: int) -> tuple[object, ...]:
        edge_incidence = sorted(
            edge_face_counts[tuple(sorted((index, neighbour)))]
            for neighbour in neighbours[index]
        )
        return (
            len(neighbours[index]),
            tuple(sorted(incident_face_sizes[index])),
            tuple(edge_incidence),
        )

    def reflected_neighbour_coordinates(index: int) -> list[Vector]:
        result = []
        for neighbour in neighbours[index]:
            reflected = coordinates[neighbour].copy()
            reflected[axis] = 2.0 * plane - reflected[axis]
            result.append(reflected)
        return result

    def neighbours_match(source_index: int, candidate_index: int) -> bool:
        reflected_neighbours = reflected_neighbour_coordinates(source_index)
        candidate_neighbours = sorted(neighbours[candidate_index])
        matched_target_to_source: dict[int, int] = {}

        def assign_neighbour(source_offset: int, visited: set[int]) -> bool:
            target_coordinate = reflected_neighbours[source_offset]
            for target_offset, target_index in enumerate(candidate_neighbours):
                if target_offset in visited:
                    continue
                if (
                    float(
                        (
                            coordinates[target_index]
                            - target_coordinate
                        ).length
                    )
                    > tolerance
                ):
                    continue
                visited.add(target_offset)
                previous_source = matched_target_to_source.get(target_offset)
                if (
                    previous_source is None
                    or assign_neighbour(previous_source, visited)
                ):
                    matched_target_to_source[target_offset] = source_offset
                    return True
            return False

        return all(
            assign_neighbour(source_offset, set())
            for source_offset in range(len(reflected_neighbours))
        )

    def diagnostic_neighbour_signature(
        index: int,
        *,
        reflect: bool,
    ) -> tuple[tuple[float, float, float], ...]:
        values = (
            reflected_neighbour_coordinates(index)
            if reflect
            else [coordinates[neighbour] for neighbour in neighbours[index]]
        )
        return tuple(
            sorted(
                tuple(round(float(value[component]), 7) for component in range(3))
                for value in values
            )
        )

    candidate_lists: list[tuple[int, ...]] = []
    statistics: dict[str, object] = {
        "raw_ambiguous_vertices": 0,
        "topology_ambiguous_vertices": 0,
        "max_raw_candidates": 0,
        "max_topology_candidates": 0,
        "bipartite_pairs": 0,
    }
    for index, coordinate in enumerate(coordinates):
        reflected = coordinate.copy()
        reflected[axis] = 2.0 * plane - reflected[axis]
        bucket_key = _spatial_key(reflected, tolerance)
        raw_candidates = []
        for offset in product((-1, 0, 1), repeat=3):
            neighbour_key = tuple(
                bucket_key[component] + offset[component]
                for component in range(3)
            )
            for candidate in buckets.get(neighbour_key, ()):
                distance = float((coordinates[candidate] - reflected).length)
                if distance <= tolerance:
                    raw_candidates.append((distance, candidate))
        if not raw_candidates:
            return (
                None,
                f"vertex {index} has no reflected correspondence",
                statistics,
            )
        raw_candidates.sort()
        source_signature = local_signature(index)
        topology_candidates = [
            candidate
            for _distance, candidate in raw_candidates
            if (
                local_signature(candidate) == source_signature
                and neighbours_match(index, candidate)
            )
        ]
        statistics["max_raw_candidates"] = max(
            int(statistics["max_raw_candidates"]),
            len(raw_candidates),
        )
        statistics["max_topology_candidates"] = max(
            int(statistics["max_topology_candidates"]),
            len(topology_candidates),
        )
        if len(raw_candidates) > 1:
            statistics["raw_ambiguous_vertices"] = (
                int(statistics["raw_ambiguous_vertices"]) + 1
            )
        if len(topology_candidates) > 1:
            statistics["topology_ambiguous_vertices"] = (
                int(statistics["topology_ambiguous_vertices"]) + 1
            )
        if index == 14 and len(raw_candidates) > 1:
            statistics["vertex_14"] = {
                "source_signature": repr(source_signature),
                "reflected_neighbours": repr(
                    diagnostic_neighbour_signature(index, reflect=True)
                ),
                "raw_candidates": [
                    candidate
                    for _distance, candidate in raw_candidates
                ],
                "topology_candidates": topology_candidates,
                "candidate_signatures": {
                    str(candidate): {
                        "local": repr(local_signature(candidate)),
                        "neighbours": repr(
                            diagnostic_neighbour_signature(
                                candidate,
                                reflect=False,
                            )
                        ),
                        "compatible": neighbours_match(index, candidate),
                    }
                    for _distance, candidate in raw_candidates
                },
            }
        if not topology_candidates:
            return (
                None,
                f"vertex {index} has no topology-compatible reflection",
                statistics,
            )
        candidate_lists.append(tuple(sorted(topology_candidates)))

    mapping = [-1] * len(coordinates)
    negative_vertices = [
        index
        for index, coordinate in enumerate(coordinates)
        if float(coordinate[axis]) < plane - tolerance
    ]
    positive_vertices = {
        index
        for index, coordinate in enumerate(coordinates)
        if float(coordinate[axis]) > plane + tolerance
    }
    plane_vertices = [
        index
        for index in range(len(coordinates))
        if index not in positive_vertices and index not in negative_vertices
    ]
    for index in plane_vertices:
        if index not in candidate_lists[index]:
            return (
                None,
                f"on-plane vertex {index} is not self-compatible under reflection",
                statistics,
            )
        mapping[index] = index

    target_to_source: dict[int, int] = {}

    def assign(source_index: int, visited: set[int]) -> bool:
        for target_index in candidate_lists[source_index]:
            if (
                target_index not in positive_vertices
                or source_index not in candidate_lists[target_index]
                or target_index in visited
            ):
                continue
            visited.add(target_index)
            previous_source = target_to_source.get(target_index)
            if previous_source is None or assign(previous_source, visited):
                target_to_source[target_index] = source_index
                return True
        return False

    for source_index in sorted(negative_vertices):
        if not assign(source_index, set()):
            return (
                None,
                f"vertex {source_index} has no one-to-one topology-compatible reflection",
                statistics,
            )
    for target_index, source_index in target_to_source.items():
        mapping[source_index] = target_index
        mapping[target_index] = source_index
    statistics["bipartite_pairs"] = len(target_to_source)

    if -1 in mapping or len(set(mapping)) != len(mapping):
        return (
            None,
            "reflected vertex correspondence is not one-to-one",
            statistics,
        )
    for index, reflected_index in enumerate(mapping):
        if mapping[reflected_index] != index:
            return (
                None,
                "reflected vertex correspondence is not involutive",
                statistics,
            )
    return tuple(mapping), "vertex correspondence proved", statistics


def _reflection_topology_matches(
    mesh: bpy.types.Mesh,
    mapping: tuple[int, ...],
) -> tuple[bool, str]:
    edge_counter = Counter(
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1]))))
        for edge in mesh.edges
    )
    reflected_edges = Counter(
        tuple(sorted((mapping[int(edge.vertices[0])], mapping[int(edge.vertices[1])])))
        for edge in mesh.edges
    )
    if reflected_edges != edge_counter:
        return False, "reflected edge connectivity differs"

    face_counter = Counter(
        _canonical_cycle(polygon.vertices)
        for polygon in mesh.polygons
    )
    reflected_faces = Counter(
        _canonical_cycle(mapping[int(index)] for index in polygon.vertices)
        for polygon in mesh.polygons
    )
    if reflected_faces != face_counter:
        return False, "reflected polygon boundary connectivity differs"
    return True, "vertex, edge, and polygon connectivity proved"


def reflection_symmetry_diagnostics(mesh: bpy.types.Mesh) -> dict[str, object]:
    """Conservatively prove local-space reflection symmetry for X, Y, and Z."""

    bounds_min, bounds_max, diagonal, tolerance = _symmetry_bounds(mesh)
    diagnostics: dict[str, object] = {
        "schema": SYMMETRY_SCHEMA_VERSION,
        "coordinate_space": "OBJECT_LOCAL",
        "scale_diagonal": diagonal,
        "tolerance": tolerance,
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "polygon_count": len(mesh.polygons),
        "axes": {},
        "proven_axes": [],
    }
    axes = diagnostics["axes"]
    proven_axes = diagnostics["proven_axes"]
    assert isinstance(axes, dict)
    assert isinstance(proven_axes, list)
    for axis, axis_name in enumerate(_AXIS_NAMES):
        plane = (float(bounds_min[axis]) + float(bounds_max[axis])) * 0.5
        axis_result: dict[str, object] = {
            "axis": axis_name,
            "plane": plane,
            "tolerance": tolerance,
            "proven": False,
            "vertex_pairs": 0,
            "self_vertices": 0,
            "reason": "",
        }
        mapping, reason, match_statistics = _reflection_vertex_map(
            mesh,
            axis,
            plane,
            tolerance,
        )
        axis_result["matching"] = match_statistics
        if mapping is None:
            axis_result["reason"] = reason
        else:
            topology_matches, topology_reason = _reflection_topology_matches(
                mesh,
                mapping,
            )
            axis_result["reason"] = topology_reason
            if topology_matches:
                axis_result["proven"] = True
                axis_result["vertex_pairs"] = sum(
                    mapping[index] != index
                    for index in range(len(mapping))
                ) // 2
                axis_result["self_vertices"] = sum(
                    mapping[index] == index
                    for index in range(len(mapping))
                )
                proven_axes.append(axis_name)
        axes[axis_name] = axis_result
    return diagnostics


def _symmetry_json(diagnostics: dict[str, object]) -> str:
    return json.dumps(
        diagnostics,
        sort_keys=True,
        separators=(",", ":"),
    )


def _symmetry_cache_fingerprint(diagnostics: dict[str, object]) -> bytes:
    digest = hashlib.sha256()
    digest.update(_symmetry_json(diagnostics).encode("utf-8"))
    return digest.digest()


def _required_axes_preserved(
    source_diagnostics: dict[str, object],
    candidate_diagnostics: dict[str, object],
) -> tuple[bool, list[str]]:
    source_axes = source_diagnostics["axes"]
    candidate_axes = candidate_diagnostics["axes"]
    assert isinstance(source_axes, dict)
    assert isinstance(candidate_axes, dict)
    missing = []
    for axis_name in source_diagnostics["proven_axes"]:
        source_axis = source_axes[axis_name]
        candidate_axis = candidate_axes[axis_name]
        assert isinstance(source_axis, dict)
        assert isinstance(candidate_axis, dict)
        plane_tolerance = max(
            float(source_axis["tolerance"]),
            float(candidate_axis["tolerance"]),
        )
        if (
            not bool(candidate_axis["proven"])
            or abs(float(source_axis["plane"]) - float(candidate_axis["plane"]))
            > plane_tolerance
        ):
            missing.append(str(axis_name))
    return not missing, missing


def sampling_diagnostics(source: bpy.types.Object) -> dict[str, object]:
    """Return a detached copy of the most recent sampling diagnostics."""

    diagnostics = _LAST_SAMPLING_DIAGNOSTICS.get(source.as_pointer(), {})
    return json.loads(json.dumps(diagnostics))


def attach_sampling_diagnostics(
    output: bpy.types.Object,
    source: bpy.types.Object,
) -> None:
    diagnostics = _LAST_SAMPLING_DIAGNOSTICS.get(source.as_pointer())
    if diagnostics:
        output[SAMPLING_DIAGNOSTICS_TAG] = _symmetry_json(diagnostics)


def is_tool_output(obj: object, kind: Optional[str] = None) -> bool:
    if not isinstance(obj, bpy.types.Object):
        return False
    if obj.get(TOOL_TAG) != TOOL_ID:
        return False
    return kind is None or obj.get(KIND_TAG) == kind


def _safe_source_token(name: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return (token or "Mesh")[:38]


def preview_name(source: bpy.types.Object) -> str:
    return f".BTVM_PREVIEW_{_safe_source_token(source.name)}"


def watertight_name(source: bpy.types.Object) -> str:
    return f".BTVM_WATERTIGHT_{_safe_source_token(source.name)}"


def bake_name(source: bpy.types.Object) -> str:
    return f"{source.name}_VOX"


def assert_name_available(
    name: str,
    *,
    replace_owned_preview_for: Optional[bpy.types.Object] = None,
) -> Optional[bpy.types.Object]:
    existing = bpy.data.objects.get(name)
    if existing is None:
        return None
    if (
        replace_owned_preview_for is not None
        and is_tool_output(existing, PREVIEW_KIND)
        and existing.get(SOURCE_TAG) == replace_owned_preview_for.name
    ):
        return existing
    raise VoxelizerError(
        f'Object name "{name}" already exists; refusing to overwrite it. '
        "Rename/delete that object, or use Clear for a tool output."
    )


def mesh_diagnostics(mesh: bpy.types.Mesh) -> dict[str, int | bool]:
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        boundary_edges = sum(len(edge.link_faces) == 1 for edge in bm.edges)
        overfull_edges = sum(len(edge.link_faces) > 2 for edge in bm.edges)
        wire_edges = sum(len(edge.link_faces) == 0 for edge in bm.edges)
        nonmanifold_edges = sum(not edge.is_manifold for edge in bm.edges)
        degenerate_faces = sum(face.calc_area() <= 1.0e-12 for face in bm.faces)
        unseen = set(bm.verts)
        components = 0
        while unseen:
            components += 1
            stack = [unseen.pop()]
            while stack:
                vertex = stack.pop()
                for edge in vertex.link_edges:
                    neighbour = edge.other_vert(vertex)
                    if neighbour in unseen:
                        unseen.remove(neighbour)
                        stack.append(neighbour)
        empty = len(bm.verts) < 4 or len(bm.faces) < 4
        return {
            "vertices": len(bm.verts),
            "edges": len(bm.edges),
            "faces": len(bm.faces),
            "boundary_edges": boundary_edges,
            "overfull_edges": overfull_edges,
            "wire_edges": wire_edges,
            "nonmanifold_edges": nonmanifold_edges,
            "degenerate_faces": degenerate_faces,
            "components": components,
            "empty": empty,
        }
    finally:
        bm.free()


def _diagnostics_ready(diagnostics: dict[str, int | bool]) -> bool:
    return (
        not diagnostics["empty"]
        and diagnostics["boundary_edges"] == 0
        and diagnostics["overfull_edges"] == 0
        and diagnostics["wire_edges"] == 0
        and diagnostics["nonmanifold_edges"] == 0
        and diagnostics["degenerate_faces"] == 0
        and diagnostics["components"] == 1
    )


def is_closed_manifold(mesh: bpy.types.Mesh) -> bool:
    return _diagnostics_ready(mesh_diagnostics(mesh))


def source_signature(mesh: bpy.types.Mesh, repair_voxel_size: float) -> str:
    digest = hashlib.sha256()
    digest.update(struct.pack("<dIII", float(repair_voxel_size), len(mesh.vertices), len(mesh.edges), len(mesh.polygons)))
    for vertex in mesh.vertices:
        digest.update(struct.pack("<3d", float(vertex.co.x), float(vertex.co.y), float(vertex.co.z)))
    for edge in mesh.edges:
        digest.update(struct.pack("<2I", int(edge.vertices[0]), int(edge.vertices[1])))
    for polygon in mesh.polygons:
        indices = tuple(int(index) for index in polygon.vertices)
        digest.update(struct.pack("<I", len(indices)))
        if indices:
            digest.update(struct.pack(f"<{len(indices)}I", *indices))
    return digest.hexdigest()


def _watertight_source_signature(
    mesh: bpy.types.Mesh,
    repair_voxel_size: float,
    symmetry: dict[str, object],
) -> str:
    digest = hashlib.sha256()
    digest.update(source_signature(mesh, repair_voxel_size).encode("ascii"))
    digest.update(_symmetry_cache_fingerprint(symmetry))
    return digest.hexdigest()


@contextmanager
def evaluated_local_mesh(
    context: bpy.types.Context,
    source: bpy.types.Object,
    *,
    preserve_all_data_layers: bool = True,
) -> Iterator[bpy.types.Mesh]:
    """Lease an evaluated object-local mesh and always clear its owner."""

    depsgraph = context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(
        preserve_all_data_layers=preserve_all_data_layers,
        depsgraph=depsgraph,
    )
    if mesh is None:
        raise VoxelizerError(
            f'Could not obtain evaluated mesh geometry for "{source.name}".'
        )
    try:
        yield mesh
    finally:
        evaluated.to_mesh_clear()


def evaluated_geometry_signature(
    context: bpy.types.Context,
    source: bpy.types.Object,
) -> str:
    """Hash evaluated object-local geometry without including object transforms."""

    with evaluated_local_mesh(
        context,
        source,
        preserve_all_data_layers=False,
    ) as mesh:
        return source_signature(mesh, 0.0)


def _image_fingerprint(image: Optional[bpy.types.Image]) -> bytes:
    """Return a bounded fingerprint that notices metadata and sampled pixel edits."""

    if image is None:
        return b"NO_IMAGE"
    digest = hashlib.sha256()
    digest.update(str(getattr(image, "name_full", image.name)).encode("utf-8"))
    digest.update(str(getattr(image, "filepath_raw", "")).encode("utf-8"))
    digest.update(str(getattr(image, "source", "")).encode("ascii", "ignore"))
    digest.update(str(getattr(image.colorspace_settings, "name", "")).encode("utf-8"))
    digest.update(b"\x01" if bool(getattr(image, "is_dirty", False)) else b"\x00")
    try:
        width, height = (int(value) for value in image.size)
        digest.update(struct.pack("<II", width, height))
        pixels = image.pixels
        pixel_count = len(pixels)
        digest.update(struct.pack("<Q", pixel_count))
        if pixel_count:
            stride = max(1, pixel_count // 512)
            for index in range(0, pixel_count, stride):
                digest.update(struct.pack("<f", float(pixels[index])))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        digest.update(b"UNREADABLE")
    return digest.digest()


def _colour_inputs_fingerprint(mesh: bpy.types.Mesh, settings) -> bytes:
    digest = hashlib.sha256()
    uv_name = str(getattr(settings, "uv_map", ""))
    digest.update(uv_name.encode("utf-8"))
    uv_layer = mesh.uv_layers.get(uv_name) if uv_name else None
    if uv_layer is not None:
        digest.update(struct.pack("<I", len(uv_layer.data)))
        for datum in uv_layer.data:
            digest.update(struct.pack("<2f", float(datum.uv.x), float(datum.uv.y)))
    fallback = tuple(float(value) for value in getattr(
        settings,
        "fallback_color",
        (0.18, 0.48, 0.8, 1.0),
    ))
    digest.update(struct.pack("<4f", *fallback))
    digest.update(_image_fingerprint(getattr(settings, "base_color_image", None)))
    return digest.digest()


def preview_sampling_key(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
) -> str:
    """Key occupancy and colour inputs; display gap is intentionally absent."""

    digest = hashlib.sha256()
    with evaluated_local_mesh(context, source) as mesh:
        digest.update(source_signature(mesh, 0.0).encode("ascii"))
        digest.update(_colour_inputs_fingerprint(mesh, settings))
    digest.update(struct.pack("<d", float(settings.voxel_size)))
    digest.update(b"\x01" if settings.auto_watertight_copy else b"\x00")
    digest.update(struct.pack("<d", float(settings.repair_voxel_size)))
    grid_mode = str(getattr(settings, "grid_origin_mode", "BOUNDS"))
    digest.update(grid_mode.encode("ascii", "ignore"))
    grid_origin = tuple(float(value) for value in getattr(
        settings,
        "grid_origin",
        (0.0, 0.0, 0.0),
    ))
    digest.update(struct.pack("<3d", *grid_origin))
    digest.update(
        b"\x01" if bool(getattr(settings, "use_sparse_candidates", True)) else b"\x00"
    )
    digest.update(struct.pack(
        "<I",
        _setting_int(settings, "sparse_grid_threshold", 50_000, 0),
    ))
    return digest.hexdigest()


def _diagnostic_message(prefix: str, diagnostics: dict[str, int | bool]) -> str:
    return (
        f"{prefix}: {diagnostics['boundary_edges']} boundary edge(s), "
        f"{diagnostics['overfull_edges']} edge(s) with more than two faces, "
        f"{diagnostics['wire_edges']} wire edge(s), "
        f"{diagnostics['nonmanifold_edges']} total non-manifold edge(s), "
        f"{diagnostics['degenerate_faces']} degenerate face(s), "
        f"{diagnostics['components']} component(s), "
        f"{diagnostics['vertices']} vertices, {diagnostics['faces']} faces."
    )


def _hide_helper(helper: bpy.types.Object) -> None:
    helper.hide_render = True
    helper.hide_select = True
    helper.hide_viewport = True
    try:
        helper.hide_set(True)
    except RuntimeError:
        pass


def _remesh_working_object(
    context: bpy.types.Context,
    working: bpy.types.Object,
    voxel_size: float,
) -> None:
    if context.mode != "OBJECT":
        raise VoxelizerError("Automatic watertight repair requires Object Mode.")
    previous_active = context.view_layer.objects.active
    previous_selected = tuple(context.selected_objects)
    try:
        for selected in previous_selected:
            selected.select_set(False)
        working.hide_viewport = False
        working.hide_select = False
        working.hide_set(False)
        working.select_set(True)
        context.view_layer.objects.active = working
        mesh = working.data
        mesh.remesh_voxel_size = float(voxel_size)
        mesh.remesh_voxel_adaptivity = 0.0
        if hasattr(mesh, "use_remesh_fix_poles"):
            mesh.use_remesh_fix_poles = True
        if hasattr(mesh, "use_remesh_preserve_volume"):
            mesh.use_remesh_preserve_volume = True
        if hasattr(mesh, "use_remesh_preserve_attributes"):
            mesh.use_remesh_preserve_attributes = False
        result = bpy.ops.object.voxel_remesh()
        if result != {"FINISHED"}:
            raise VoxelizerError(f"Blender Voxel Remesh returned {result}.")
    finally:
        if working.name in bpy.data.objects:
            working.select_set(False)
        for selected in previous_selected:
            if selected.name in bpy.data.objects:
                try:
                    selected.select_set(True)
                except RuntimeError:
                    pass
        if previous_active is not None and previous_active.name in bpy.data.objects:
            context.view_layer.objects.active = previous_active


def _shift_mesh_for_symmetry(
    mesh: bpy.types.Mesh,
    source_symmetry: dict[str, object],
    factor: float,
) -> None:
    axes = source_symmetry["axes"]
    assert isinstance(axes, dict)
    offsets = Vector((0.0, 0.0, 0.0))
    for axis, axis_name in enumerate(_AXIS_NAMES):
        axis_diagnostics = axes[axis_name]
        assert isinstance(axis_diagnostics, dict)
        if axis_diagnostics["proven"]:
            offsets[axis] = float(axis_diagnostics["plane"]) * factor
    if offsets.length_squared == 0.0:
        return
    for vertex in mesh.vertices:
        vertex.co += offsets
    mesh.update()


def _mirror_missing_helper_axes(
    context: bpy.types.Context,
    working: bpy.types.Object,
    source_symmetry: dict[str, object],
    missing_axes: Iterable[str],
) -> None:
    """Bisect and mirror only axes already proved on the untouched source."""

    missing = set(missing_axes)
    if not missing:
        return
    previous_active = context.view_layer.objects.active
    previous_selected = tuple(context.selected_objects)
    try:
        for selected in previous_selected:
            selected.select_set(False)
        working.hide_viewport = False
        working.hide_select = False
        working.hide_set(False)
        working.select_set(True)
        context.view_layer.objects.active = working

        modifier = working.modifiers.new(".BTVM Symmetry Preservation", "MIRROR")
        for axis, axis_name in enumerate(_AXIS_NAMES):
            modifier.use_axis[axis] = axis_name in missing
            modifier.use_bisect_axis[axis] = axis_name in missing
            modifier.use_bisect_flip_axis[axis] = False
        modifier.use_clip = True
        modifier.use_mirror_merge = True
        modifier.merge_threshold = max(
            float(source_symmetry["tolerance"]),
            SYMMETRY_ABSOLUTE_FLOOR,
        )
        result = bpy.ops.object.modifier_apply(modifier=modifier.name)
        if result != {"FINISHED"}:
            raise VoxelizerError(
                f"Symmetry-preservation Mirror returned {result}."
            )
    finally:
        if working.name in bpy.data.objects:
            working.select_set(False)
        for selected in previous_selected:
            if selected.name in bpy.data.objects:
                try:
                    selected.select_set(True)
                except RuntimeError:
                    pass
        if previous_active is not None and previous_active.name in bpy.data.objects:
            context.view_layer.objects.active = previous_active


def _evaluated_mesh_diagnostics_and_symmetry(
    context: bpy.types.Context,
    source: bpy.types.Object,
) -> tuple[dict[str, int | bool], dict[str, object]]:
    context.view_layer.update()
    with evaluated_local_mesh(context, source) as mesh:
        return mesh_diagnostics(mesh), reflection_symmetry_diagnostics(mesh)


def ensure_sampling_object(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    source_mesh: bpy.types.Mesh,
    source_diagnostics: dict[str, int | bool],
    source_symmetry: dict[str, object],
) -> tuple[bpy.types.Object, bool]:
    if _diagnostics_ready(source_diagnostics):
        return source, False
    if not settings.auto_watertight_copy:
        raise VoxelizerError(
            _diagnostic_message(
                "Source is not a single closed manifold and Auto Watertight Copy is off",
                source_diagnostics,
            )
        )

    repair_size = float(settings.repair_voxel_size)
    if repair_size <= 0.0:
        raise VoxelizerError("Repair Voxel Size must be greater than zero.")
    signature = _watertight_source_signature(
        source_mesh,
        repair_size,
        source_symmetry,
    )
    name = watertight_name(source)
    existing = bpy.data.objects.get(name)
    if existing is not None and not (
        is_tool_output(existing, HELPER_KIND)
        and existing.get(SOURCE_TAG) == source.name
    ):
        raise VoxelizerError(
            f'Object name "{name}" already exists; refusing to overwrite '
            "an unowned watertight helper."
        )
    if existing is not None:
        existing_diagnostics, existing_symmetry = (
            _evaluated_mesh_diagnostics_and_symmetry(context, existing)
        )
        symmetry_preserved, _missing_axes = _required_axes_preserved(
            source_symmetry,
            existing_symmetry,
        )
        if (
            existing.get(SOURCE_SIGNATURE_TAG) == signature
            and _diagnostics_ready(existing_diagnostics)
            and symmetry_preserved
        ):
            existing.matrix_world = source.matrix_world.copy()
            existing[SOURCE_SYMMETRY_TAG] = _symmetry_json(source_symmetry)
            existing[HELPER_SYMMETRY_TAG] = _symmetry_json(existing_symmetry)
            _hide_helper(existing)
            return existing, False

    working_mesh = source_mesh.copy()
    working_mesh.name = f"{name}_BuildMesh"
    working = bpy.data.objects.new(f"{name}_BUILD", working_mesh)
    collection = source.users_collection[0] if source.users_collection else context.collection
    collection.objects.link(working)
    working.matrix_world = source.matrix_world.copy()
    tag_output(working, source, HELPER_KIND)
    working.hide_render = True
    try:
        _shift_mesh_for_symmetry(working.data, source_symmetry, -1.0)
        _remesh_working_object(context, working, repair_size)
        _shift_mesh_for_symmetry(working.data, source_symmetry, 1.0)
        repaired_diagnostics, repaired_symmetry = (
            _evaluated_mesh_diagnostics_and_symmetry(context, working)
        )
        symmetry_preserved, missing_axes = _required_axes_preserved(
            source_symmetry,
            repaired_symmetry,
        )
        if not symmetry_preserved:
            _shift_mesh_for_symmetry(working.data, source_symmetry, -1.0)
            try:
                _mirror_missing_helper_axes(
                    context,
                    working,
                    source_symmetry,
                    missing_axes,
                )
            finally:
                _shift_mesh_for_symmetry(working.data, source_symmetry, 1.0)
            repaired_diagnostics, repaired_symmetry = (
                _evaluated_mesh_diagnostics_and_symmetry(context, working)
            )
            symmetry_preserved, missing_axes = _required_axes_preserved(
                source_symmetry,
                repaired_symmetry,
            )
        if not symmetry_preserved:
            raise VoxelizerError(
                "Automatic watertight repair could not preserve proved local "
                f"reflection symmetry on axis/axes: {', '.join(missing_axes)}."
            )
        if not _diagnostics_ready(repaired_diagnostics):
            raise VoxelizerError(
                _diagnostic_message(
                    "Automatic watertight repair did not produce one closed manifold",
                    repaired_diagnostics,
                )
            )
        working.data.materials.clear()
        working[SOURCE_SIGNATURE_TAG] = signature
        working[REPAIR_SIZE_TAG] = repair_size
        working[SOURCE_SYMMETRY_TAG] = _symmetry_json(source_symmetry)
        working[HELPER_SYMMETRY_TAG] = _symmetry_json(repaired_symmetry)
        if existing is None:
            working.name = name
            helper = working
        else:
            old_mesh = existing.data
            existing.data = working.data
            bpy.data.objects.remove(working, do_unlink=True)
            if old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
            helper = existing
            tag_output(helper, source, HELPER_KIND)
            helper[SOURCE_SIGNATURE_TAG] = signature
            helper[REPAIR_SIZE_TAG] = repair_size
            helper[SOURCE_SYMMETRY_TAG] = _symmetry_json(source_symmetry)
            helper[HELPER_SYMMETRY_TAG] = _symmetry_json(repaired_symmetry)
        helper.matrix_world = source.matrix_world.copy()
        _hide_helper(helper)
        return helper, True
    except Exception:
        if working.name in bpy.data.objects:
            failed_mesh = working.data
            bpy.data.objects.remove(working, do_unlink=True)
            if failed_mesh.users == 0:
                bpy.data.meshes.remove(failed_mesh)
        raise


def selected_source(context: bpy.types.Context) -> bpy.types.Object:
    if context.mode != "OBJECT":
        raise VoxelizerError("Voxelizer requires Object Mode.")
    source = context.active_object
    if source is None or source.type != "MESH" or source not in context.selected_objects:
        raise VoxelizerError("Select one active Mesh object.")
    if is_tool_output(source):
        raise VoxelizerError("Select the original source Mesh, not a Voxelizer output.")
    return source


def source_objects(context: bpy.types.Context, settings) -> list[bpy.types.Object]:
    """Resolve active, selected, or collection sources in deterministic order."""

    if context.mode != "OBJECT":
        raise VoxelizerError("Chromoxel requires Object Mode.")
    scope = str(getattr(settings, "source_scope", "ACTIVE"))
    if scope == "ACTIVE":
        return [selected_source(context)]
    if scope == "SELECTED":
        candidates = tuple(context.selected_objects)
    elif scope == "COLLECTION":
        collection = getattr(settings, "source_collection", None)
        if collection is None:
            raise VoxelizerError("Choose a Source Collection.")
        candidates = tuple(collection.all_objects)
    else:
        raise VoxelizerError(f'Unknown Source Scope "{scope}".')
    include_hidden = bool(getattr(settings, "include_hidden", False))
    sources = []
    for candidate in candidates:
        if candidate.type != "MESH" or is_tool_output(candidate):
            continue
        if not include_hidden and (
            candidate.hide_viewport
            or candidate.hide_get()
        ):
            continue
        sources.append(candidate)
    sources.sort(key=lambda item: item.name_full.casefold())
    if not sources:
        raise VoxelizerError(
            "The selected scope contains no eligible Mesh objects."
        )
    return sources


def estimate_sources(
    context: bpy.types.Context,
    sources: Iterable[bpy.types.Object],
    settings,
) -> dict[str, object]:
    """Estimate candidate work and transient memory without building voxels."""

    validate_settings(settings)
    items = []
    total_grid = 0
    total_candidates = 0
    total_bytes = 0
    for source in sources:
        with evaluated_local_mesh(context, source) as mesh:
            if not mesh.vertices:
                continue
            bounds_min = Vector(tuple(
                min(float(vertex.co[axis]) for vertex in mesh.vertices)
                for axis in range(3)
            ))
            bounds_max = Vector(tuple(
                max(float(vertex.co[axis]) for vertex in mesh.vertices)
                for axis in range(3)
            ))
            symmetry = reflection_symmetry_diagnostics(mesh)
            indices, coordinates, _report = _build_sampling_lattice(
                bounds_min,
                bounds_max,
                float(settings.voxel_size),
                symmetry,
                settings,
            )
            counts = [len(axis) for axis in coordinates]
            full_grid = counts[0] * counts[1] * counts[2]
            surface_area = sum(float(polygon.area) for polygon in mesh.polygons)
            sparse_estimate = min(
                full_grid,
                max(1, int(math.ceil(
                    surface_area / max(float(settings.voxel_size) ** 2, 1.0e-12)
                    * 8.0
                ))),
            )
            estimated_bytes = sparse_estimate * 112
            item = {
                "name": source.name,
                "axis_counts": counts,
                "full_grid_samples": full_grid,
                "estimated_candidates": sparse_estimate,
                "estimated_memory_bytes": estimated_bytes,
                "lattice_index_ranges": [
                    (axis.start, axis.stop - 1) for axis in indices
                ],
            }
            items.append(item)
            total_grid += full_grid
            total_candidates += sparse_estimate
            total_bytes += estimated_bytes
    return {
        "sources": items,
        "source_count": len(items),
        "full_grid_samples": total_grid,
        "estimated_candidates": total_candidates,
        "estimated_memory_bytes": total_bytes,
        "within_sample_budget": all(
            int(item["estimated_candidates"]) <= sample_budget(settings)
            for item in items
        ),
        "within_cache_budget": total_bytes <= cache_budget_bytes(settings),
    }


def validate_settings(settings) -> None:
    if settings.voxel_size <= 0.0:
        raise VoxelizerError("Voxel Size must be greater than zero.")
    if settings.cube_gap < 0.0 or settings.cube_gap >= settings.voxel_size:
        raise VoxelizerError("Cube Gap must be non-negative and smaller than Voxel Size.")


def ensure_colour_material() -> bpy.types.Material:
    material = bpy.data.materials.get(MATERIAL_NAME)
    if material is not None and material.get(TOOL_TAG) != TOOL_ID:
        raise VoxelizerError(
            f'Material name "{MATERIAL_NAME}" is occupied by user data; '
            "refusing to overwrite it."
        )
    if material is None:
        material = bpy.data.materials.new(MATERIAL_NAME)
        material[TOOL_TAG] = TOOL_ID
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    colour = nodes.new("ShaderNodeVertexColor")
    colour.layer_name = COLOUR_ATTRIBUTE
    links.new(colour.outputs["Color"], shader.inputs["Base Color"])
    links.new(colour.outputs["Alpha"], shader.inputs["Alpha"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (0.18, 0.48, 0.8, 1.0)
    return material


def _barycentric_weights(point: Vector, a: Vector, b: Vector, c: Vector):
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1.0e-16:
        return None
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return (1.0 - v - w, v, w)


def _srgb_channel_to_scene_linear(value: float) -> float:
    """Decode one normalized sRGB channel for a scene-linear color attribute."""

    value = max(0.0, min(1.0, float(value)))
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


class ColourSampler:
    """Nearest-polygon UV/image sampler with an unconditional fallback path."""

    def __init__(
        self,
        mesh: bpy.types.Mesh,
        uv_name: str,
        image: Optional[bpy.types.Image],
        fallback: Iterable[float],
    ):
        self.mesh = mesh
        self.fallback = tuple(float(component) for component in fallback)
        self.uv_layer = mesh.uv_layers.get(uv_name) if uv_name else None
        self.image = image if self.uv_layer is not None else None
        self.width = 0
        self.height = 0
        self.pixels = None
        self.source_bvh = None
        self.triangles_by_polygon = {}
        if self.image is not None:
            try:
                self.width, self.height = (int(value) for value in self.image.size)
                if self.width > 0 and self.height > 0:
                    self.pixels = tuple(self.image.pixels[:])
            except (RuntimeError, TypeError, ValueError):
                self.pixels = None
        if self.pixels:
            source_vertices = [vertex.co.copy() for vertex in mesh.vertices]
            source_polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
            self.source_bvh = BVHTree.FromPolygons(
                source_vertices,
                source_polygons,
                all_triangles=False,
            )
            mesh.calc_loop_triangles()
            for triangle in mesh.loop_triangles:
                self.triangles_by_polygon.setdefault(
                    triangle.polygon_index, []
                ).append(triangle)

    @property
    def uses_image(self) -> bool:
        return bool(self.pixels and self.uv_layer)

    def sample(self, point: Vector, polygon_index: int):
        if not self.uses_image:
            return self.fallback
        best = None
        best_penalty = math.inf
        for triangle in self.triangles_by_polygon.get(polygon_index, ()):
            a, b, c = (self.mesh.vertices[index].co for index in triangle.vertices)
            weights = _barycentric_weights(point, a, b, c)
            if weights is None:
                continue
            penalty = sum(
                max(0.0, -weight) + max(0.0, weight - 1.0)
                for weight in weights
            )
            if penalty < best_penalty:
                best = (triangle, weights)
                best_penalty = penalty
            if penalty <= 1.0e-5:
                break
        if best is None:
            return self.fallback
        triangle, weights = best
        uv_data = self.uv_layer.data
        uvs = [uv_data[loop_index].uv for loop_index in triangle.loops]
        uv = uvs[0] * weights[0] + uvs[1] * weights[1] + uvs[2] * weights[2]
        x = min(self.width - 1, max(0, int((float(uv.x) % 1.0) * self.width)))
        y = min(self.height - 1, max(0, int((float(uv.y) % 1.0) * self.height)))
        offset = (y * self.width + x) * 4
        if offset + 3 >= len(self.pixels):
            return self.fallback
        raw = tuple(float(self.pixels[offset + channel]) for channel in range(4))
        return (
            _srgb_channel_to_scene_linear(raw[0]),
            _srgb_channel_to_scene_linear(raw[1]),
            _srgb_channel_to_scene_linear(raw[2]),
            raw[3],
        )

    def sample_nearest_original(self, query_point: Vector):
        if not self.uses_image or self.source_bvh is None:
            return self.fallback
        nearest = self.source_bvh.find_nearest(query_point)
        if nearest is None or nearest[0] is None or nearest[2] is None:
            return self.fallback
        location, _normal, polygon_index, _distance = nearest
        return self.sample(location, polygon_index)


_CUBE_CORNERS = (
    (-1, -1, -1),
    (1, -1, -1),
    (1, 1, -1),
    (-1, 1, -1),
    (-1, -1, 1),
    (1, -1, 1),
    (1, 1, 1),
    (-1, 1, 1),
)
_CUBE_FACES = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


def _build_sampling_lattice(
    bounds_min: Vector,
    bounds_max: Vector,
    voxel_size: float,
    source_symmetry: dict[str, object],
    settings,
) -> tuple[list[range], list[list[float]], dict[str, object]]:
    """Build deterministic local-space axes for bounds or fixed-origin grids."""

    shell_distance = voxel_size * math.sqrt(3.0) * 0.52
    source_axes = source_symmetry["axes"]
    assert isinstance(source_axes, dict)
    proven_axes = set(str(axis) for axis in source_symmetry["proven_axes"])
    grid_mode = str(getattr(settings, "grid_origin_mode", "BOUNDS"))
    if grid_mode not in {"BOUNDS", "OBJECT", "CUSTOM"}:
        grid_mode = "BOUNDS"
    custom_origin = tuple(float(value) for value in getattr(
        settings,
        "grid_origin",
        (0.0, 0.0, 0.0),
    ))
    lattice_indices: list[range] = []
    lattice_coordinates: list[list[float]] = []
    lattice_report: dict[str, object] = {}
    for axis, axis_name in enumerate(_AXIS_NAMES):
        if axis_name in proven_axes:
            axis_diagnostics = source_axes[axis_name]
            assert isinstance(axis_diagnostics, dict)
            plane = float(axis_diagnostics["plane"])
            radius = max(
                plane - float(bounds_min[axis]),
                float(bounds_max[axis]) - plane,
            )
            half_steps = max(0, int(math.ceil(radius / voxel_size)))
            indices = range(-half_steps, half_steps + 1)
            if len(indices) > sample_budget(settings):
                raise VoxelizerError(
                    f"The {axis_name} grid axis would require {len(indices):,} "
                    "cells; increase Voxel Size."
                )
            coordinates = [plane + index * voxel_size for index in indices]
            lattice_report[axis_name] = {
                "mode": "PROVEN_PLANE_CENTERED",
                "plane": plane,
                "index_min": -half_steps,
                "index_max": half_steps,
                "count": len(coordinates),
            }
        elif grid_mode == "BOUNDS":
            count = max(
                1,
                int(math.ceil(
                    (float(bounds_max[axis]) - float(bounds_min[axis]))
                    / voxel_size
                )),
            )
            indices = range(count)
            if len(indices) > sample_budget(settings):
                raise VoxelizerError(
                    f"The {axis_name} grid axis would require {len(indices):,} "
                    "cells; increase Voxel Size."
                )
            coordinates = [
                float(bounds_min[axis]) + (index + 0.5) * voxel_size
                for index in indices
            ]
            lattice_report[axis_name] = {
                "mode": "BOUNDS_HALF_CELL",
                "bounds_min": float(bounds_min[axis]),
                "index_min": 0,
                "index_max": count - 1,
                "count": len(coordinates),
            }
        else:
            anchor = 0.0 if grid_mode == "OBJECT" else custom_origin[axis]
            minimum = int(math.ceil(
                (float(bounds_min[axis]) - shell_distance - anchor) / voxel_size
            ))
            maximum = int(math.floor(
                (float(bounds_max[axis]) + shell_distance - anchor) / voxel_size
            ))
            if minimum > maximum:
                middle = int(round(
                    (((float(bounds_min[axis]) + float(bounds_max[axis])) * 0.5) - anchor)
                    / voxel_size
                ))
                minimum = maximum = middle
            indices = range(minimum, maximum + 1)
            if len(indices) > sample_budget(settings):
                raise VoxelizerError(
                    f"The {axis_name} grid axis would require {len(indices):,} "
                    "cells; increase Voxel Size."
                )
            coordinates = [anchor + index * voxel_size for index in indices]
            lattice_report[axis_name] = {
                "mode": f"{grid_mode}_FIXED_ORIGIN",
                "origin": anchor,
                "index_min": minimum,
                "index_max": maximum,
                "count": len(coordinates),
            }
        lattice_indices.append(indices)
        lattice_coordinates.append(coordinates)
    return lattice_indices, lattice_coordinates, lattice_report


def _sample_surface_voxels_from_meshes_iter(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    source_mesh: bpy.types.Mesh,
    source_symmetry: dict[str, object],
    sampling_object: bpy.types.Object,
    helper_rebuilt: bool,
    sampling_mesh: bpy.types.Mesh,
) -> Iterator[SamplingProgress]:
    """Incrementally sample while evaluated mesh leases remain live."""

    sampling_symmetry = reflection_symmetry_diagnostics(sampling_mesh)
    symmetry_preserved, missing_axes = _required_axes_preserved(
        source_symmetry,
        sampling_symmetry,
    )
    if not symmetry_preserved:
        raise VoxelizerError(
            "Sampling geometry does not preserve proved source reflection "
            f"symmetry on axis/axes: {', '.join(missing_axes)}."
        )
    sampling_vertices = [vertex.co.copy() for vertex in sampling_mesh.vertices]
    sampling_polygons = [tuple(polygon.vertices) for polygon in sampling_mesh.polygons]
    bvh = BVHTree.FromPolygons(
        sampling_vertices,
        sampling_polygons,
        all_triangles=False,
    )
    if bvh is None:
        raise VoxelizerError("Could not build a surface acceleration structure.")

    bounds_min = Vector(
        tuple(
            min(vertex.co[axis] for vertex in sampling_mesh.vertices)
            for axis in range(3)
        )
    )
    bounds_max = Vector(
        tuple(
            max(vertex.co[axis] for vertex in sampling_mesh.vertices)
            for axis in range(3)
        )
    )
    voxel_size = float(settings.voxel_size)
    proven_axes = set(str(axis) for axis in source_symmetry["proven_axes"])
    lattice_indices, lattice_coordinates, lattice_report = _build_sampling_lattice(
        bounds_min,
        bounds_max,
        voxel_size,
        source_symmetry,
        settings,
    )
    counts = [len(coordinates) for coordinates in lattice_coordinates]
    full_grid_count = counts[0] * counts[1] * counts[2]
    canonical_offset_floors = [
        max(0, min(counts[axis], -lattice_indices[axis].start))
        if _AXIS_NAMES[axis] in proven_axes
        else 0
        for axis in range(3)
    ]
    canonical_counts = [
        counts[axis] - canonical_offset_floors[axis]
        for axis in range(3)
    ]
    canonical_grid_count = (
        canonical_counts[0] * canonical_counts[1] * canonical_counts[2]
    )
    work_limit = sample_budget(settings)
    if max(counts) > work_limit:
        raise VoxelizerError(
            f"One grid axis would require {max(counts):,} cells; increase "
            f"Voxel Size (limit {work_limit:,})."
        )

    shell_distance = voxel_size * math.sqrt(3.0) * 0.52
    chunk_size = sampling_chunk_size(settings)
    sparse_requested = bool(getattr(settings, "use_sparse_candidates", True))
    sparse_threshold = _setting_int(
        settings,
        "sparse_grid_threshold",
        50_000,
        0,
    )
    use_sparse_candidates = (
        sparse_requested and canonical_grid_count >= sparse_threshold
    )
    candidate_expansion_budget = _setting_int(
        settings,
        "candidate_expansion_budget",
        work_limit * 32,
        work_limit,
    )
    candidate_expansion_tests = 0
    if use_sparse_candidates:
        sampling_mesh.calc_loop_triangles()
        triangles = tuple(sampling_mesh.loop_triangles)
        candidate_set: set[tuple[int, int, int]] = set()
        next_yield = chunk_size
        for triangle_offset, triangle in enumerate(triangles):
            triangle_coordinates = [
                sampling_mesh.vertices[index].co
                for index in triangle.vertices
            ]
            lower = []
            upper = []
            for axis in range(3):
                minimum = min(float(point[axis]) for point in triangle_coordinates)
                maximum = max(float(point[axis]) for point in triangle_coordinates)
                coordinates = lattice_coordinates[axis]
                lower.append(bisect_left(coordinates, minimum - shell_distance))
                upper.append(bisect_right(coordinates, maximum + shell_distance))
            for axis in range(3):
                lower[axis] = max(lower[axis], canonical_offset_floors[axis])
            expansion_count = (
                (upper[0] - lower[0])
                * (upper[1] - lower[1])
                * (upper[2] - lower[2])
            )
            candidate_expansion_tests += expansion_count
            if candidate_expansion_tests > candidate_expansion_budget:
                raise VoxelizerError(
                    "Triangle candidate expansion exceeded the configured "
                    f"budget ({candidate_expansion_budget:,}); increase "
                    "Voxel Size or Candidate Expansion Budget."
                )
            # itertools.product plus set.update performs the hot insertion loop
            # in C while preserving the exact expanded-triangle candidate set.
            candidate_set.update(product(
                range(lower[0], upper[0]),
                range(lower[1], upper[1]),
                range(lower[2], upper[2]),
            ))
            if len(candidate_set) > work_limit:
                raise VoxelizerError(
                    f"Sparse surface candidates exceeded {work_limit:,}; "
                    "increase Voxel Size or the Sample Budget."
                )
            if candidate_expansion_tests >= next_yield:
                yield SamplingProgress(
                    "CANDIDATES",
                    triangle_offset + 1,
                    max(1, len(triangles)),
                    f"Building sparse candidates for {source.name}",
                )
                next_yield = (
                    (candidate_expansion_tests // chunk_size) + 1
                ) * chunk_size
        candidate_offsets = sorted(
            candidate_set,
            key=lambda key: (key[2], key[1], key[0]),
        )
    else:
        if canonical_grid_count > work_limit:
            raise VoxelizerError(
                f"Grid would require {canonical_grid_count:,} canonical samples; increase "
                f"Voxel Size (limit {work_limit:,})."
            )
        candidate_offsets = [
            (x_offset, y_offset, z_offset)
            for z_offset in range(canonical_offset_floors[2], counts[2])
            for y_offset in range(canonical_offset_floors[1], counts[1])
            for x_offset in range(canonical_offset_floors[0], counts[0])
        ]
        candidate_expansion_tests = len(candidate_offsets)
    candidate_count = len(candidate_offsets)
    if not candidate_offsets:
        raise VoxelizerError("No sampling candidates were produced.")
    yield SamplingProgress(
        "CANDIDATES",
        candidate_count,
        candidate_count,
        f"Prepared {candidate_count:,} candidates for {source.name}",
    )

    sampler = ColourSampler(
        source_mesh,
        settings.uv_map,
        settings.base_color_image,
        settings.fallback_color,
    )
    centres: list[Vector] = []
    colours: list[tuple[float, ...]] = []
    occupied_seed_count = 0
    orbit_added_count = 0
    maximum_voxels = voxel_budget(settings)
    if not proven_axes:
        for candidate_number, (x_offset, y_offset, z_offset) in enumerate(
            candidate_offsets,
            start=1,
        ):
            centre = Vector((
                lattice_coordinates[0][x_offset],
                lattice_coordinates[1][y_offset],
                lattice_coordinates[2][z_offset],
            ))
            nearest = bvh.find_nearest(centre, shell_distance)
            if nearest is not None and nearest[0] is not None and nearest[3] is not None:
                location, _normal, _polygon_index, distance = nearest
                if distance <= shell_distance:
                    centres.append(centre)
                    colours.append(sampler.sample_nearest_original(location))
                    occupied_seed_count += 1
                    if len(centres) > maximum_voxels:
                        raise VoxelizerError(
                            f"Surface exceeded {maximum_voxels:,} voxels; "
                            "increase Voxel Size or the Voxel Budget."
                        )
            if candidate_number % chunk_size == 0:
                yield SamplingProgress(
                    "OCCUPANCY",
                    candidate_number,
                    candidate_count,
                    f"Sampling {source.name}",
                )
    else:
        selected_indices: set[tuple[int, int, int]] = set()
        for candidate_number, (x_offset, y_offset, z_offset) in enumerate(
            candidate_offsets,
            start=1,
        ):
            centre = Vector((
                lattice_coordinates[0][x_offset],
                lattice_coordinates[1][y_offset],
                lattice_coordinates[2][z_offset],
            ))
            nearest = bvh.find_nearest(centre, shell_distance)
            if nearest is not None and nearest[0] is not None and nearest[3] is not None:
                if nearest[3] <= shell_distance:
                    occupied_seed_count += 1
                    key = (
                        lattice_indices[0][x_offset],
                        lattice_indices[1][y_offset],
                        lattice_indices[2][z_offset],
                    )
                    axis_variants = [
                        (value, -value)
                        if _AXIS_NAMES[axis] in proven_axes and value != 0
                        else (value,)
                        for axis, value in enumerate(key)
                    ]
                    selected_indices.update(product(*axis_variants))
                    if len(selected_indices) > maximum_voxels:
                        raise VoxelizerError(
                            f"Surface exceeded {maximum_voxels:,} voxels; "
                            "increase Voxel Size or the Voxel Budget."
                        )
            if candidate_number % chunk_size == 0:
                yield SamplingProgress(
                    "OCCUPANCY",
                    candidate_number,
                    candidate_count,
                    f"Sampling symmetric occupancy for {source.name}",
                )

        coordinate_lookup = [
            {
                index: lattice_coordinates[axis][offset]
                for offset, index in enumerate(lattice_indices[axis])
            }
            for axis in range(3)
        ]
        ordered_indices = sorted(
            selected_indices,
            key=lambda key: (key[2], key[1], key[0]),
        )
        for colour_number, (x_index, y_index, z_index) in enumerate(
            ordered_indices,
            start=1,
        ):
            centre = Vector(
                (
                    coordinate_lookup[0][x_index],
                    coordinate_lookup[1][y_index],
                    coordinate_lookup[2][z_index],
                )
            )
            nearest = bvh.find_nearest(centre)
            if nearest is None or nearest[0] is None:
                raise VoxelizerError(
                    "Could not independently colour-sample a symmetry orbit centre."
                )
            centres.append(centre)
            colours.append(sampler.sample_nearest_original(nearest[0]))
            if colour_number % chunk_size == 0:
                yield SamplingProgress(
                    "COLOUR",
                    colour_number,
                    len(ordered_indices),
                    f"Sampling colours for {source.name}",
                )
        orbit_added_count = max(0, len(centres) - occupied_seed_count)
    if not centres:
        raise VoxelizerError("No surface voxels were produced; decrease Voxel Size.")
    diagnostics = {
        "schema": SYMMETRY_SCHEMA_VERSION,
        "source_symmetry": source_symmetry,
        "sampling_symmetry": sampling_symmetry,
        "proven_axes": sorted(proven_axes),
        "helper_used": sampling_object is not source,
        "helper_rebuilt": bool(helper_rebuilt),
        "voxel_size": voxel_size,
        "shell_distance": shell_distance,
        "lattice": lattice_report,
        "grid_origin_mode": str(getattr(settings, "grid_origin_mode", "BOUNDS")),
        "candidate_strategy": (
            "TRIANGLE_AABB_SPARSE"
            if use_sparse_candidates
            else "FULL_GRID_DISABLED"
            if not sparse_requested
            else "FULL_GRID_SMALL_VOLUME"
        ),
        "full_grid_count": full_grid_count,
        "canonical_grid_count": canonical_grid_count,
        "candidate_count": candidate_count,
        "candidate_expansion_tests": candidate_expansion_tests,
        "candidate_reduction_ratio": (
            0.0
            if full_grid_count <= 0
            else 1.0 - (candidate_count / full_grid_count)
        ),
        "chunk_size": chunk_size,
        "cache_hit": False,
        "occupied_seed_count": occupied_seed_count,
        "orbit_added_count": orbit_added_count,
        "selected_count": len(centres),
        "selection": (
            "PROVEN_AXIS_INTEGER_ORBIT_CLOSURE"
            if proven_axes
            else "LEGACY_NO_CLOSURE"
        ),
    }
    _LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()] = diagnostics
    yield SamplingProgress(
        "FINALIZE",
        len(centres),
        len(centres),
        f"Finalized {len(centres):,} voxels for {source.name}",
    )
    return centres, colours, len(centres), sampler.uses_image


def _sampling_cache_key(source: bpy.types.Object, sampling_key: str) -> str:
    return f"{source.as_pointer()}:{sampling_key}"


def sample_surface_voxels_iter(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    cache_key: Optional[str] = None,
    use_cache: bool = True,
) -> Iterator[SamplingProgress]:
    """Incrementally sample one source and return the result on completion.

    Consumers advance this generator between UI events.  The final voxel tuple is
    carried by ``StopIteration.value`` so the same implementation serves modal
    operators and the synchronous/background API.
    """

    validate_settings(settings)
    sampling_key = cache_key or preview_sampling_key(context, source, settings)
    cache_id = _sampling_cache_key(source, sampling_key)
    if use_cache:
        entry = _cache_get(cache_id)
        if entry is not None:
            diagnostics = json.loads(json.dumps(entry["diagnostics"]))
            diagnostics["cache_hit"] = True
            diagnostics["cache_entries"] = len(_SAMPLE_CACHE)
            diagnostics["cache_bytes"] = int(_SAMPLE_CACHE_BYTES)
            _LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()] = diagnostics
            centres = [Vector(value) for value in entry["centres"]]
            colours = [tuple(value) for value in entry["colours"]]
            yield SamplingProgress(
                "CACHE",
                1,
                1,
                f"Reused {len(centres):,} cached voxels for {source.name}",
            )
            return centres, colours, len(centres), bool(entry["used_image"])

    with evaluated_local_mesh(context, source) as source_mesh:
        source_diagnostics = mesh_diagnostics(source_mesh)
        source_symmetry = reflection_symmetry_diagnostics(source_mesh)
        sampling_object, helper_rebuilt = ensure_sampling_object(
            context,
            source,
            settings,
            source_mesh=source_mesh,
            source_diagnostics=source_diagnostics,
            source_symmetry=source_symmetry,
        )
        if sampling_object is source:
            result = yield from _sample_surface_voxels_from_meshes_iter(
                context,
                source,
                settings,
                source_mesh=source_mesh,
                source_symmetry=source_symmetry,
                sampling_object=sampling_object,
                helper_rebuilt=helper_rebuilt,
                sampling_mesh=source_mesh,
            )
        else:
            with evaluated_local_mesh(context, sampling_object) as sampling_mesh:
                result = yield from _sample_surface_voxels_from_meshes_iter(
                    context,
                    source,
                    settings,
                    source_mesh=source_mesh,
                    source_symmetry=source_symmetry,
                    sampling_object=sampling_object,
                    helper_rebuilt=helper_rebuilt,
                    sampling_mesh=sampling_mesh,
                )

    centres, colours, count, used_image = result
    diagnostics = dict(_LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()])
    diagnostics["cache_hit"] = False
    _cache_put(
        cache_id,
        centres,
        colours,
        used_image,
        diagnostics,
        settings,
    )
    diagnostics["cache_entries"] = len(_SAMPLE_CACHE)
    diagnostics["cache_bytes"] = int(_SAMPLE_CACHE_BYTES)
    _LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()] = diagnostics
    return centres, colours, count, used_image


def _consume_progress_generator(generator, progress_callback=None):
    while True:
        try:
            progress = next(generator)
        except StopIteration as stop:
            return stop.value
        if progress_callback is not None:
            progress_callback(progress)


def sample_surface_voxels(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    cache_key: Optional[str] = None,
    use_cache: bool = True,
    progress_callback=None,
) -> tuple[list[Vector], list[tuple[float, ...]], int, bool]:
    """Synchronous sampling API used by scripts and background tests."""

    return _consume_progress_generator(
        sample_surface_voxels_iter(
            context,
            source,
            settings,
            cache_key=cache_key,
            use_cache=use_cache,
        ),
        progress_callback,
    )


def build_voxel_mesh_iter(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    mesh_name: str,
    *,
    cache_key: Optional[str] = None,
) -> Iterator[SamplingProgress]:
    """Incrementally build the realized cube mesh used by Bake."""

    centres, colours, count, used_image = yield from sample_surface_voxels_iter(
        context, source, settings, cache_key=cache_key
    )
    voxel_size = float(settings.voxel_size)
    half_extent = (voxel_size - float(settings.cube_gap)) * 0.5
    result_vertices = []
    result_faces = []
    chunk_size = sampling_chunk_size(settings)
    for voxel_number, centre in enumerate(centres, start=1):
        first_vertex = len(result_vertices)
        result_vertices.extend(
            (
                centre.x + x_sign * half_extent,
                centre.y + y_sign * half_extent,
                centre.z + z_sign * half_extent,
            )
            for x_sign, y_sign, z_sign in _CUBE_CORNERS
        )
        result_faces.extend(
            tuple(first_vertex + index for index in face)
            for face in _CUBE_FACES
        )
        if voxel_number % chunk_size == 0:
            yield SamplingProgress(
                "BAKE_GEOMETRY",
                voxel_number,
                count,
                f"Building cube geometry for {source.name}",
            )

    result = bpy.data.meshes.new(mesh_name)
    completed = False
    try:
        result.from_pydata(result_vertices, (), result_faces)
        result.update()
        attribute = result.color_attributes.new(
            name=COLOUR_ATTRIBUTE,
            type="FLOAT_COLOR",
            domain="CORNER",
        )
        polygon_count = len(result.polygons)
        for polygon_number, polygon in enumerate(result.polygons, start=1):
            colour = colours[polygon.index // 6]
            for loop_index in polygon.loop_indices:
                attribute.data[loop_index].color = colour
            if polygon_number % (chunk_size * 6) == 0:
                yield SamplingProgress(
                    "BAKE_COLOUR",
                    polygon_number,
                    polygon_count,
                    f"Writing voxel colours for {source.name}",
                )
        result.materials.append(ensure_colour_material())
        result.update()
        completed = True
    finally:
        if not completed and result.name in bpy.data.meshes:
            bpy.data.meshes.remove(result)
    return result, count, used_image


def build_voxel_mesh(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    mesh_name: str,
    *,
    cache_key: Optional[str] = None,
    progress_callback=None,
) -> tuple[bpy.types.Mesh, int, bool]:
    """Synchronous realized-mesh API used by scripts and background tests."""

    return _consume_progress_generator(
        build_voxel_mesh_iter(
            context,
            source,
            settings,
            mesh_name,
            cache_key=cache_key,
        ),
        progress_callback,
    )


def tag_output(
    output: bpy.types.Object,
    source: bpy.types.Object,
    kind: str,
) -> None:
    output[TOOL_TAG] = TOOL_ID
    output[KIND_TAG] = kind
    output[SOURCE_TAG] = source.name
    if kind in {PREVIEW_KIND, BAKE_KIND}:
        attach_sampling_diagnostics(output, source)


def link_output(
    context: bpy.types.Context,
    source: bpy.types.Object,
    mesh: bpy.types.Mesh,
    name: str,
    kind: str,
) -> bpy.types.Object:
    output = bpy.data.objects.new(name, mesh)
    collection = source.users_collection[0] if source.users_collection else context.collection
    collection.objects.link(output)
    output.matrix_world = source.matrix_world.copy()
    tag_output(output, source, kind)
    return output


def clear_tagged_outputs() -> int:
    clear_sampling_cache()
    outputs = [output for output in bpy.data.objects if is_tool_output(output)]
    for output in outputs:
        mesh = output.data if output.type == "MESH" else None
        bpy.data.objects.remove(output, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for group in tuple(bpy.data.node_groups):
        if group.get(TOOL_TAG) == TOOL_ID:
            bpy.data.node_groups.remove(group, do_unlink=True)
    for material in tuple(bpy.data.materials):
        if material.get(TOOL_TAG) == TOOL_ID:
            bpy.data.materials.remove(material, do_unlink=True)
    return len(outputs)
