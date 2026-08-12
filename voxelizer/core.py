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
import time
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import product
from typing import Iterable, Iterator, Optional, Sequence

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import gpu_backend


TOOL_ID = "org.openai.textured_voxelizer_mvp"
TOOL_TAG = "_textured_voxelizer_tool"
KIND_TAG = "_textured_voxelizer_kind"
SOURCE_TAG = "_textured_voxelizer_source"
PREVIEW_KIND = "preview"
BAKE_KIND = "bake"
HELPER_KIND = "watertight_helper"
COLOUR_ATTRIBUTE = "voxel_color"
SIZE_ATTRIBUTE = "voxel_size"
EXTENT_ATTRIBUTE = "voxel_extent"
LEVEL_ATTRIBUTE = "voxel_level"
MATERIAL_NAME = ".BTVM_voxel_color"
SOURCE_SIGNATURE_TAG = "_textured_voxelizer_source_signature"
REPAIR_SIZE_TAG = "_textured_voxelizer_repair_voxel_size"
REPAIR_STRATEGY_TAG = "_textured_voxelizer_repair_strategy"
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
ADAPTIVE_SCHEMA_VERSION = 2
ADAPTIVE_CELL_AXIS_MARGIN = 0.10
ADAPTIVE_PLANAR_NORMAL_ALIGNMENT = 0.95
_AXIS_NAMES = ("X", "Y", "Z")
_LAST_SAMPLING_DIAGNOSTICS: dict[int, dict[str, object]] = {}
_SAMPLE_CACHE: OrderedDict[str, dict[str, object]] = OrderedDict()
_SAMPLE_CACHE_BYTES = 0
_IMAGE_BUFFER_CACHE: OrderedDict[tuple[object, ...], "_ImageBuffer"] = OrderedDict()
_IMAGE_BUFFER_CACHE_BYTES = 0
_SOURCE_SESSION_CACHE: OrderedDict[str, "SourceSamplingSession"] = OrderedDict()
_SOURCE_SESSION_CACHE_LIMIT = 2
SEPARATE_PART_REPAIR_LIMIT = 8
_RUNTIME_ID_REVISIONS: dict[int, int] = {}
_RUNTIME_REVISION_SERIAL = 0
_RUNTIME_KEY_EPOCH = hashlib.sha256(
    f"{time.time_ns()}:{id(_RUNTIME_ID_REVISIONS)}".encode("ascii")
).digest()


class VoxelizerError(RuntimeError):
    """A concise validation failure suitable for an operator report."""


class SamplingInputError(VoxelizerError):
    """Input topology prevented repair; callers may offer direct shell sampling."""


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


@dataclass
class VoxelSampleResult:
    """Voxel samples with backward-compatible four-value unpacking.

    Chromoxel 0.5 callers unpacked ``centres, colours, count, used_image``.
    Keeping that iterator contract lets old scripts continue to run while 0.6
    carries the per-cell size and refinement level required by adaptive output.
    """

    centres: list[Vector]
    colours: list[tuple[float, ...]]
    sizes: list[float]
    extents: list[Vector]
    levels: list[int]
    used_image: bool
    source_uvs: list[tuple[float, float]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.centres)

    def __iter__(self):
        yield self.centres
        yield self.colours
        yield self.count
        yield self.used_image


class _CanonicalGridOffsets(Sequence[tuple[int, int, int]]):
    """Lazy z/y/x full-grid view with bounded slicing for GPU batches."""

    def __init__(self, floors: Sequence[int], counts: Sequence[int]):
        self.floors = tuple(int(value) for value in floors)
        self.counts = tuple(int(value) for value in counts)
        self.widths = tuple(
            max(0, self.counts[axis] - self.floors[axis])
            for axis in range(3)
        )
        self.length = self.widths[0] * self.widths[1] * self.widths[2]

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[offset] for offset in range(*index.indices(self.length))]
        index = int(index)
        if index < 0:
            index += self.length
        if index < 0 or index >= self.length:
            raise IndexError(index)
        width_x, width_y, _width_z = self.widths
        plane = width_x * width_y
        z_offset, remainder = divmod(index, plane)
        y_offset, x_offset = divmod(remainder, width_x)
        return (
            self.floors[0] + x_offset,
            self.floors[1] + y_offset,
            self.floors[2] + z_offset,
        )

    def __iter__(self):
        return (
            (x_offset, y_offset, z_offset)
            for z_offset, y_offset, x_offset in product(
                range(self.floors[2], self.counts[2]),
                range(self.floors[1], self.counts[1]),
                range(self.floors[0], self.counts[0]),
            )
        )


@dataclass(frozen=True)
class _ColourAnalysis:
    colour: tuple[float, ...]
    texture_error: float
    geometry_angle: float
    source_uv: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class _TriangleView:
    """Small triangle proxy used without materializing all loop triangles."""

    vertices: tuple[int, int, int]
    loops: tuple[int, int, int]


@dataclass
class _VoxelCell:
    centre: Vector
    size: float
    extent: Vector
    level: int
    colour: tuple[float, ...]
    texture_error: float
    geometry_angle: float
    source_uv: tuple[float, float] = (0.0, 0.0)

    def error_score(self, texture_threshold: float, geometry_angle: float) -> float:
        texture_score = self.texture_error / max(texture_threshold, 1.0e-9)
        geometry_score = self.geometry_angle / max(geometry_angle, 1.0e-9)
        return max(texture_score, geometry_score)


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
    global _SAMPLE_CACHE_BYTES, _IMAGE_BUFFER_CACHE_BYTES
    _SAMPLE_CACHE.clear()
    _SAMPLE_CACHE_BYTES = 0
    _IMAGE_BUFFER_CACHE.clear()
    _IMAGE_BUFFER_CACHE_BYTES = 0
    while _SOURCE_SESSION_CACHE:
        _key, session = _SOURCE_SESSION_CACHE.popitem(last=False)
        session.close()
    gpu_backend.clear_runtime_cache()


def sampling_cache_stats() -> dict[str, int]:
    session_gpu_bytes = sum(
        int(getattr(session.gpu_occupancy_resource, "gpu_bytes", 0) or 0)
        for session in _SOURCE_SESSION_CACHE.values()
    )
    return {
        "entries": len(_SAMPLE_CACHE),
        "bytes": int(_SAMPLE_CACHE_BYTES),
        "image_entries": len(_IMAGE_BUFFER_CACHE),
        "image_bytes": int(_IMAGE_BUFFER_CACHE_BYTES),
        "session_entries": len(_SOURCE_SESSION_CACHE),
        "session_gpu_bytes": session_gpu_bytes,
    }


def _runtime_id_pointer(datablock) -> int:
    if datablock is None:
        return 0
    try:
        original = getattr(datablock, "original", None) or datablock
        return int(original.as_pointer())
    except (AttributeError, ReferenceError, TypeError):
        return 0


def mark_runtime_id_updated(datablock) -> None:
    """Advance the cheap preview fingerprint for one changed Blender ID."""

    global _RUNTIME_REVISION_SERIAL
    pointer = _runtime_id_pointer(datablock)
    if pointer == 0:
        return
    _RUNTIME_REVISION_SERIAL += 1
    _RUNTIME_ID_REVISIONS[pointer] = _RUNTIME_REVISION_SERIAL


def clear_runtime_id_revisions() -> None:
    """Reset revisions and force saved Preview keys to miss after file load."""

    global _RUNTIME_KEY_EPOCH, _RUNTIME_REVISION_SERIAL
    _RUNTIME_ID_REVISIONS.clear()
    _RUNTIME_REVISION_SERIAL = 0
    _RUNTIME_KEY_EPOCH = hashlib.sha256(
        f"{time.time_ns()}:{id(object())}".encode("ascii")
    ).digest()


def _runtime_id_revision(datablock) -> int:
    return _RUNTIME_ID_REVISIONS.get(_runtime_id_pointer(datablock), 0)


def _cache_get(key: str):
    entry = _SAMPLE_CACHE.get(key)
    if entry is not None:
        _SAMPLE_CACHE.move_to_end(key)
    return entry


def _cache_put(
    key: str,
    centres: Iterable[Iterable[float]],
    colours: Iterable[Iterable[float]],
    sizes: Iterable[float],
    extents: Iterable[Iterable[float]],
    levels: Iterable[int],
    source_uvs: Iterable[Iterable[float]],
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
    size_values = tuple(float(value) for value in sizes)
    extent_values = tuple(
        tuple(float(component) for component in extent)
        for extent in extents
    )
    level_values = tuple(int(value) for value in levels)
    source_uv_values = tuple(
        tuple(float(component) for component in value)
        for value in source_uvs
    )
    if not (
        len(centre_values)
        == len(colour_values)
        == len(size_values)
        == len(extent_values)
        == len(level_values)
        == len(source_uv_values)
    ):
        raise VoxelizerError("Cached voxel arrays have inconsistent lengths.")
    estimated_bytes = len(centre_values) * 120
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
        "sizes": size_values,
        "extents": extent_values,
        "levels": level_values,
        "source_uvs": source_uv_values,
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
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        values = array("f", [0.0]) * (len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", values)
        coordinates = np.frombuffer(values, dtype=np.float32).reshape((-1, 3))
        bounds_min = Vector(tuple(float(value) for value in coordinates.min(axis=0)))
        bounds_max = Vector(tuple(float(value) for value in coordinates.max(axis=0)))
    else:
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


def _axis_distribution_rejections(
    mesh: bpy.types.Mesh,
    bounds_min: Vector,
    bounds_max: Vector,
    tolerance: float,
) -> dict[str, float]:
    """Reject impossible axes from a necessary 1D reflection condition.

    A valid 3D reflection bijection implies that the sorted coordinates on
    the reflected axis pair within the exact proof tolerance.  Failure is
    therefore conclusive; passing this check is not treated as proof.
    """

    if len(mesh.vertices) < 2:
        return {}
    try:
        import numpy as np
    except ImportError:
        return {}
    values = array("f", [0.0]) * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", values)
    coordinates = np.frombuffer(values, dtype=np.float32).reshape((-1, 3))
    limit = float(tolerance) * 1.01 + 1.0e-12
    rejected: dict[str, float] = {}
    for axis, axis_name in enumerate(_AXIS_NAMES):
        ordered = np.sort(coordinates[:, axis].astype(np.float64, copy=True))
        pair_errors = np.abs(
            ordered
            + ordered[::-1]
            - (float(bounds_min[axis]) + float(bounds_max[axis]))
        )
        maximum_error = float(np.max(pair_errors)) if len(pair_errors) else 0.0
        if maximum_error > limit:
            rejected[axis_name] = maximum_error
    return rejected


def _reflection_vertex_map(
    mesh: bpy.types.Mesh,
    axis: int,
    plane: float,
    tolerance: float,
    *,
    coordinates: Optional[list[Vector]] = None,
    buckets: Optional[dict[tuple[int, int, int], list[int]]] = None,
    topology_cache: Optional[dict[str, object]] = None,
) -> tuple[Optional[tuple[int, ...]], str, dict[str, object]]:
    coordinates = coordinates or [vertex.co.copy() for vertex in mesh.vertices]
    if buckets is None:
        buckets = {}
        for index, coordinate in enumerate(coordinates):
            buckets.setdefault(_spatial_key(coordinate, tolerance), []).append(index)
    topology_cache = topology_cache if topology_cache is not None else {}

    statistics: dict[str, object] = {
        "raw_ambiguous_vertices": 0,
        "topology_ambiguous_vertices": 0,
        "max_raw_candidates": 0,
        "max_topology_candidates": 0,
        "bipartite_pairs": 0,
        "coordinate_preflight_vertices": 0,
    }

    def raw_candidates_for(index: int) -> list[tuple[float, int]]:
        reflected = coordinates[index].copy()
        reflected[axis] = 2.0 * plane - reflected[axis]
        bucket_key = _spatial_key(reflected, tolerance)
        result = []
        for offset in product((-1, 0, 1), repeat=3):
            neighbour_key = tuple(
                bucket_key[component] + offset[component]
                for component in range(3)
            )
            for candidate in buckets.get(neighbour_key, ()):
                distance = float((coordinates[candidate] - reflected).length)
                if distance <= tolerance:
                    result.append((distance, candidate))
        result.sort()
        return result

    # A missing reflected coordinate is a conclusive symmetry rejection.  Do
    # this bounded, topology-free probe before allocating vertex adjacency and
    # scanning every polygon.  Exact proof still runs for every axis that
    # passes, so this cannot create a false symmetry positive or negative.
    vertex_count = len(coordinates)
    preflight_indices = list(range(min(256, vertex_count)))
    if vertex_count > 256:
        preflight_indices.extend(
            min(vertex_count - 1, round(offset * (vertex_count - 1) / 255))
            for offset in range(256)
        )
    for index in dict.fromkeys(preflight_indices):
        statistics["coordinate_preflight_vertices"] = (
            int(statistics["coordinate_preflight_vertices"]) + 1
        )
        if not raw_candidates_for(index):
            return (
                None,
                f"vertex {index} has no reflected correspondence",
                statistics,
            )

    neighbours = topology_cache.get("neighbours")
    incident_face_sizes = topology_cache.get("incident_face_sizes")
    edge_face_counts = topology_cache.get("edge_face_counts")
    local_signatures = topology_cache.get("local_signatures")
    if (
        neighbours is None
        or incident_face_sizes is None
        or edge_face_counts is None
        or local_signatures is None
    ):
        neighbours = [set() for _vertex in mesh.vertices]
        edge_face_counts = Counter()
        incident_face_sizes = [[] for _vertex in mesh.vertices]
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
        local_signatures = []
        for index in range(vertex_count):
            edge_incidence = sorted(
                edge_face_counts[tuple(sorted((index, neighbour)))]
                for neighbour in neighbours[index]
            )
            local_signatures.append((
                len(neighbours[index]),
                tuple(sorted(incident_face_sizes[index])),
                tuple(edge_incidence),
            ))
        topology_cache["neighbours"] = neighbours
        topology_cache["incident_face_sizes"] = incident_face_sizes
        topology_cache["edge_face_counts"] = edge_face_counts
        topology_cache["local_signatures"] = local_signatures

    def local_signature(index: int) -> tuple[object, ...]:
        return local_signatures[index]

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
    for index, _coordinate in enumerate(coordinates):
        raw_candidates = raw_candidates_for(index)
        if not raw_candidates:
            return (
                None,
                f"vertex {index} has no reflected correspondence",
                statistics,
            )
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
    distribution_rejections = _axis_distribution_rejections(
        mesh,
        bounds_min,
        bounds_max,
        tolerance,
    )
    coordinates: Optional[list[Vector]] = None
    coordinate_buckets: Optional[dict[tuple[int, int, int], list[int]]] = None
    # Topology is axis-independent. Build it lazily only if a coordinate
    # preflight passes, then reuse it for the remaining exact axis proofs.
    topology_cache: dict[str, object] = {}
    diagnostics: dict[str, object] = {
        "schema": SYMMETRY_SCHEMA_VERSION,
        "coordinate_space": "OBJECT_LOCAL",
        "scale_diagonal": diagonal,
        "tolerance": tolerance,
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "polygon_count": len(mesh.polygons),
        "axis_distribution_rejections": distribution_rejections,
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
        if axis_name in distribution_rejections:
            mapping = None
            reason = (
                "reflected axis-coordinate distribution differs "
                f"(max error {distribution_rejections[axis_name]:.9g})"
            )
            match_statistics = {
                "axis_distribution_rejected": True,
                "maximum_axis_error": distribution_rejections[axis_name],
            }
        else:
            if coordinates is None or coordinate_buckets is None:
                coordinates = [vertex.co.copy() for vertex in mesh.vertices]
                coordinate_buckets = {}
                for index, coordinate in enumerate(coordinates):
                    coordinate_buckets.setdefault(
                        _spatial_key(coordinate, tolerance),
                        [],
                    ).append(index)
            mapping, reason, match_statistics = _reflection_vertex_map(
                mesh,
                axis,
                plane,
                tolerance,
                coordinates=coordinates,
                buckets=coordinate_buckets,
                topology_cache=topology_cache,
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


def mesh_readiness_diagnostics(mesh: bpy.types.Mesh) -> dict[str, int | bool]:
    """Return as soon as one condition proves that repair is required.

    The explicit UI surface check continues to use ``mesh_diagnostics`` for
    complete counts. Sampling only needs the Boolean readiness decision, so a
    million-face non-manifold source should not pay to count every defect and
    connected component before building its private repair proxy.
    """

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        result: dict[str, int | bool] = {
            "vertices": len(bm.verts),
            "edges": len(bm.edges),
            "faces": len(bm.faces),
            "boundary_edges": 0,
            "overfull_edges": 0,
            "wire_edges": 0,
            "nonmanifold_edges": 0,
            "degenerate_faces": 0,
            "components": 0,
            "empty": len(bm.verts) < 4 or len(bm.faces) < 4,
            "complete": True,
        }
        if result["empty"]:
            return result
        for edge in bm.edges:
            linked_faces = len(edge.link_faces)
            if linked_faces == 2 and edge.is_manifold:
                continue
            result["boundary_edges"] = int(linked_faces == 1)
            result["overfull_edges"] = int(linked_faces > 2)
            result["wire_edges"] = int(linked_faces == 0)
            result["nonmanifold_edges"] = 1
            result["complete"] = False
            return result
        for face in bm.faces:
            if face.calc_area() <= 1.0e-12:
                result["degenerate_faces"] = 1
                result["complete"] = False
                return result

        unseen = set(bm.verts)
        components = 0
        while unseen:
            components += 1
            if components > 1:
                result["components"] = components
                result["complete"] = False
                return result
            stack = [unseen.pop()]
            while stack:
                vertex = stack.pop()
                for edge in vertex.link_edges:
                    neighbour = edge.other_vert(vertex)
                    if neighbour in unseen:
                        unseen.remove(neighbour)
                        stack.append(neighbour)
        result["components"] = components
        return result
    finally:
        bm.free()


def mesh_component_count(mesh: bpy.types.Mesh, *, stop_after: int = 2) -> int:
    """Count connected vertex islands, with an optional early-stop threshold."""

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        unseen = set(bm.verts)
        components = 0
        while unseen:
            components += 1
            if stop_after > 0 and components >= stop_after:
                return components
            stack = [unseen.pop()]
            while stack:
                vertex = stack.pop()
                for edge in vertex.link_edges:
                    neighbour = edge.other_vert(vertex)
                    if neighbour in unseen:
                        unseen.remove(neighbour)
                        stack.append(neighbour)
        return components
    finally:
        bm.free()


def _closed_component_diagnostics_ready(
    diagnostics: dict[str, int | bool],
) -> bool:
    """Accept one or more individually closed components as a sampling proxy."""

    return (
        not diagnostics["empty"]
        and diagnostics["boundary_edges"] == 0
        and diagnostics["overfull_edges"] == 0
        and diagnostics["wire_edges"] == 0
        and diagnostics["nonmanifold_edges"] == 0
        and diagnostics["degenerate_faces"] == 0
        and int(diagnostics["components"]) >= 1
    )


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


def diagnostics_ready(diagnostics: dict[str, int | bool]) -> bool:
    """Public, allocation-free readiness check for an existing diagnostic report."""

    return _diagnostics_ready(diagnostics)


def is_closed_manifold(mesh: bpy.types.Mesh) -> bool:
    return _diagnostics_ready(mesh_diagnostics(mesh))


def source_signature(mesh: bpy.types.Mesh, repair_voxel_size: float) -> str:
    """Hash mesh geometry/topology with Blender's bulk RNA transfer path."""

    digest = hashlib.sha256()
    digest.update(b"CHROMOXEL_SOURCE_SIGNATURE_V2")
    digest.update(struct.pack(
        "<dIIII",
        float(repair_voxel_size),
        len(mesh.vertices),
        len(mesh.edges),
        len(mesh.polygons),
        len(mesh.loops),
    ))

    coordinates = array("f", [0.0]) * (len(mesh.vertices) * 3)
    if coordinates:
        mesh.vertices.foreach_get("co", coordinates)
        digest.update(coordinates.tobytes())

    edge_vertices = array("i", [0]) * (len(mesh.edges) * 2)
    if edge_vertices:
        mesh.edges.foreach_get("vertices", edge_vertices)
        digest.update(edge_vertices.tobytes())

    loop_vertices = array("i", [0]) * len(mesh.loops)
    if loop_vertices:
        mesh.loops.foreach_get("vertex_index", loop_vertices)
        digest.update(loop_vertices.tobytes())

    polygon_starts = array("i", [0]) * len(mesh.polygons)
    polygon_totals = array("i", [0]) * len(mesh.polygons)
    if polygon_starts:
        mesh.polygons.foreach_get("loop_start", polygon_starts)
        mesh.polygons.foreach_get("loop_total", polygon_totals)
        digest.update(polygon_starts.tobytes())
        digest.update(polygon_totals.tobytes())
    return digest.hexdigest()


def _watertight_source_signature(
    mesh: bpy.types.Mesh,
    repair_voxel_size: float,
    symmetry: dict[str, object],
    *,
    componentwise: bool = False,
) -> str:
    digest = hashlib.sha256()
    digest.update(b"CHROMOXEL_REPAIR_STRATEGY_V3")
    digest.update(source_signature(mesh, repair_voxel_size).encode("ascii"))
    digest.update(_symmetry_cache_fingerprint(symmetry))
    digest.update(b"\x01" if componentwise else b"\x00")
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
        pixel_count = len(image.pixels)
        digest.update(struct.pack("<Q", pixel_count))
        # Indexed RNA pixel reads are exceptionally expensive for 4K/8K images
        # (hundreds of scalar probes can take tens of seconds).  Blender's ID
        # update flags plus the explicit Clear Cache action provide bounded
        # invalidation without touching individual pixels here.
        digest.update(b"\x01" if bool(getattr(image, "is_updated", False)) else b"\x00")
        digest.update(b"\x01" if bool(getattr(image, "is_updated_data", False)) else b"\x00")
        packed = getattr(image, "packed_file", None)
        digest.update(struct.pack("<Q", int(getattr(packed, "size", 0) or 0)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        digest.update(b"UNREADABLE")
    return digest.digest()


def _colour_inputs_fingerprint(mesh: bpy.types.Mesh, settings) -> bytes:
    digest = hashlib.sha256()
    uv_name = str(getattr(settings, "uv_map", ""))
    digest.update(uv_name.encode("utf-8"))
    uv_layers = (
        [mesh.uv_layers.get(uv_name)]
        if uv_name and mesh.uv_layers.get(uv_name) is not None
        else list(mesh.uv_layers)
    )
    for uv_layer in uv_layers:
        if uv_layer is None:
            continue
        digest.update(str(uv_layer.name).encode("utf-8"))
        digest.update(struct.pack("<I", len(uv_layer.data)))
        for datum in uv_layer.data:
            digest.update(struct.pack("<2f", float(datum.uv.x), float(datum.uv.y)))
    fallback = tuple(float(value) for value in getattr(
        settings,
        "fallback_color",
        (0.18, 0.48, 0.8, 1.0),
    ))
    digest.update(struct.pack("<4f", *fallback))
    manual_image = getattr(settings, "base_color_image", None)
    digest.update(_image_fingerprint(manual_image))
    auto_material_images = bool(getattr(settings, "auto_material_images", True))
    digest.update(b"\x01" if auto_material_images else b"\x00")
    if manual_image is None and auto_material_images:
        for material in mesh.materials:
            if material is None:
                digest.update(b"NO_MATERIAL")
                continue
            digest.update(str(material.name_full).encode("utf-8"))
            digest.update(struct.pack(
                "<4f",
                *(float(value) for value in material.diffuse_color),
            ))
            image_node = _material_image_node(material)
            digest.update(_image_fingerprint(
                getattr(image_node, "image", None) if image_node is not None else None
            ))
            if image_node is not None:
                digest.update(str(getattr(image_node, "extension", "REPEAT")).encode("ascii"))
                digest.update(_image_node_uv_name(image_node).encode("utf-8"))
    return digest.digest()


def _runtime_colour_inputs_fingerprint(
    source: bpy.types.Object,
    settings,
) -> bytes:
    """Fingerprint colour IDs without walking every UV loop or image pixel."""

    mesh = source.data
    digest = hashlib.sha256()
    uv_name = str(getattr(settings, "uv_map", ""))
    digest.update(uv_name.encode("utf-8"))
    for uv_layer in mesh.uv_layers:
        digest.update(str(uv_layer.name).encode("utf-8"))
        digest.update(struct.pack("<Q", len(uv_layer.data)))
    fallback = tuple(float(value) for value in getattr(
        settings,
        "fallback_color",
        (0.18, 0.48, 0.8, 1.0),
    ))
    digest.update(struct.pack("<4f", *fallback))
    manual_image = getattr(settings, "base_color_image", None)
    digest.update(struct.pack(
        "<2Q",
        _runtime_id_pointer(manual_image),
        _runtime_id_revision(manual_image),
    ))
    digest.update(_image_fingerprint(manual_image))
    auto_material_images = bool(getattr(settings, "auto_material_images", True))
    digest.update(b"\x01" if auto_material_images else b"\x00")
    for material in mesh.materials:
        if material is None:
            digest.update(b"NO_MATERIAL")
            continue
        digest.update(struct.pack(
            "<2Q",
            _runtime_id_pointer(material),
            _runtime_id_revision(material),
        ))
        digest.update(str(material.name_full).encode("utf-8"))
        digest.update(struct.pack(
            "<4f",
            *(float(value) for value in material.diffuse_color),
        ))
        node_tree = getattr(material, "node_tree", None)
        digest.update(struct.pack(
            "<2Q",
            _runtime_id_pointer(node_tree),
            _runtime_id_revision(node_tree),
        ))
        if manual_image is None and auto_material_images:
            image_node = _material_image_node(material)
            image = getattr(image_node, "image", None) if image_node is not None else None
            digest.update(struct.pack(
                "<2Q",
                _runtime_id_pointer(image),
                _runtime_id_revision(image),
            ))
            digest.update(_image_fingerprint(image))
            if image_node is not None:
                digest.update(str(getattr(image_node, "extension", "REPEAT")).encode("ascii"))
                digest.update(_image_node_uv_name(image_node).encode("utf-8"))
    return digest.digest()


def preview_sampling_key(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
) -> str:
    """Build an invalidation-aware key without traversing a dense source mesh."""

    digest = hashlib.sha256()
    del context  # Kept in the public signature for existing callers.
    mesh = source.data
    digest.update(_RUNTIME_KEY_EPOCH)
    digest.update(struct.pack(
        "<4Q3I",
        _runtime_id_pointer(source),
        _runtime_id_revision(source),
        _runtime_id_pointer(mesh),
        _runtime_id_revision(mesh),
        len(mesh.vertices),
        len(mesh.edges),
        len(mesh.polygons),
    ))
    digest.update(_runtime_colour_inputs_fingerprint(source, settings))
    digest.update(struct.pack("<d", float(settings.voxel_size)))
    digest.update(b"\x01" if settings.auto_watertight_copy else b"\x00")
    digest.update(
        b"\x01" if bool(getattr(settings, "preserve_disconnected_parts", True)) else b"\x00"
    )
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
    sampling_mode = str(getattr(settings, "sampling_mode", "UNIFORM"))
    digest.update(sampling_mode.encode("ascii", "ignore"))
    digest.update(struct.pack("<I", ADAPTIVE_SCHEMA_VERSION))
    digest.update(struct.pack(
        "<I",
        _setting_int(settings, "adaptive_max_level", 0, 0),
    ))
    digest.update(struct.pack(
        "<I",
        _setting_int(settings, "adaptive_geometry_max_level", 1, 0),
    ))
    digest.update(struct.pack(
        "<2d",
        float(getattr(settings, "adaptive_texture_threshold", 0.16)),
        float(getattr(settings, "adaptive_geometry_angle", 35.0)),
    ))
    digest.update(str(getattr(settings, "texture_filter", "BILINEAR")).encode("ascii"))
    digest.update(str(getattr(settings, "compute_backend", "AUTO")).encode("ascii"))
    digest.update(struct.pack(
        "<I",
        _setting_int(settings, "gpu_batch_size", 65_536, 1_024),
    ))
    digest.update(struct.pack(
        "<I",
        _setting_int(settings, "gpu_memory_limit_mb", 512, 64),
    ))
    digest.update(struct.pack(
        "<3Q",
        sample_budget(settings),
        voxel_budget(settings),
        _setting_int(
            settings,
            "candidate_expansion_budget",
            sample_budget(settings) * 32,
            sample_budget(settings),
        ),
    ))
    return digest.hexdigest()


def _diagnostic_message(prefix: str, diagnostics: dict[str, int | bool]) -> str:
    message = (
        f"{prefix}: {diagnostics['boundary_edges']} boundary edge(s), "
        f"{diagnostics['overfull_edges']} edge(s) with more than two faces, "
        f"{diagnostics['wire_edges']} wire edge(s), "
        f"{diagnostics['nonmanifold_edges']} total non-manifold edge(s), "
        f"{diagnostics['degenerate_faces']} degenerate face(s), "
        f"{diagnostics['components']} component(s), "
        f"{diagnostics['vertices']} vertices, {diagnostics['faces']} faces."
    )
    if not bool(diagnostics.get("complete", True)):
        message += " Fast readiness scan stopped at the first blocking condition; use Check Surface for full counts."
    return message


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
    # Timer-driven and some automation contexts omit ``selected_objects`` even
    # though the view layer and Object operators are valid.  Derive the same
    # state from the view layer so large asynchronous jobs do not fail before
    # the user has requested any geometry work.
    previous_selected = tuple(
        obj for obj in context.view_layer.objects
        if obj.select_get(view_layer=context.view_layer)
    )
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


def _component_meshes(mesh: bpy.types.Mesh) -> list[bpy.types.Mesh]:
    """Split one mesh into connected-component mesh datablocks without transforms."""

    source = bmesh.new()
    try:
        source.from_mesh(mesh)
        unseen = set(source.verts)
        components = []
        while unseen:
            seed = unseen.pop()
            vertices = {seed}
            stack = [seed]
            while stack:
                vertex = stack.pop()
                for edge in vertex.link_edges:
                    neighbour = edge.other_vert(vertex)
                    if neighbour in unseen:
                        unseen.remove(neighbour)
                        vertices.add(neighbour)
                        stack.append(neighbour)
            components.append(vertices)

        result = []
        for index, vertices in enumerate(components):
            part_bmesh = bmesh.new()
            try:
                mapping = {
                    vertex: part_bmesh.verts.new(tuple(vertex.co))
                    for vertex in vertices
                }
                part_bmesh.verts.ensure_lookup_table()
                for face in source.faces:
                    if all(vertex in mapping for vertex in face.verts):
                        try:
                            part_bmesh.faces.new(tuple(mapping[vertex] for vertex in face.verts))
                        except ValueError:
                            pass
                for edge in source.edges:
                    if edge.link_faces or any(vertex not in mapping for vertex in edge.verts):
                        continue
                    try:
                        part_bmesh.edges.new(tuple(mapping[vertex] for vertex in edge.verts))
                    except ValueError:
                        pass
                part_mesh = bpy.data.meshes.new(f".{mesh.name}_Component_{index:03d}")
                part_bmesh.to_mesh(part_mesh)
                part_mesh.update()
                result.append(part_mesh)
            finally:
                part_bmesh.free()
        return result
    finally:
        source.free()


def _remesh_components_separately(
    context: bpy.types.Context,
    working: bpy.types.Object,
    voxel_size: float,
) -> None:
    """Voxel-remesh each topology island independently, then join the results."""

    source_mesh = working.data
    part_meshes = _component_meshes(source_mesh)
    repaired_meshes = []
    try:
        for index, part_mesh in enumerate(part_meshes):
            part = bpy.data.objects.new(f"{working.name}_PART_{index:03d}", part_mesh)
            (working.users_collection[0] if working.users_collection else context.collection).objects.link(part)
            part.matrix_world = working.matrix_world.copy()
            part.hide_render = True
            try:
                _remesh_working_object(context, part, voxel_size)
                repaired_meshes.append(part.data.copy())
            finally:
                data = part.data
                bpy.data.objects.remove(part, do_unlink=True)
                if data not in repaired_meshes and data.users == 0:
                    bpy.data.meshes.remove(data)

        combined_bmesh = bmesh.new()
        try:
            for repaired in repaired_meshes:
                temporary = bmesh.new()
                try:
                    temporary.from_mesh(repaired)
                    vertex_mapping = {
                        vertex: combined_bmesh.verts.new(tuple(vertex.co))
                        for vertex in temporary.verts
                    }
                    combined_bmesh.verts.ensure_lookup_table()
                    for face in temporary.faces:
                        try:
                            combined_bmesh.faces.new(
                                tuple(vertex_mapping[vertex] for vertex in face.verts)
                            )
                        except ValueError:
                            pass
                finally:
                    temporary.free()
            combined_mesh = bpy.data.meshes.new(f"{working.name}_PartsMesh")
            combined_bmesh.to_mesh(combined_mesh)
            combined_mesh.update()
        finally:
            combined_bmesh.free()
        old_mesh = working.data
        working.data = combined_mesh
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    finally:
        for part_mesh in part_meshes:
            try:
                if part_mesh.users == 0 and bpy.data.meshes.get(part_mesh.name) is part_mesh:
                    bpy.data.meshes.remove(part_mesh)
            except ReferenceError:
                pass
        for repaired in repaired_meshes:
            try:
                if repaired.users == 0 and bpy.data.meshes.get(repaired.name) is repaired:
                    bpy.data.meshes.remove(repaired)
            except ReferenceError:
                pass


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
    component_count: Optional[int] = None,
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

    preserve_parts = bool(getattr(settings, "preserve_disconnected_parts", True))
    components = (
        int(component_count)
        if component_count is not None
        else int(source_diagnostics.get("components", 0))
    )
    if preserve_parts and components <= 1:
        components = mesh_component_count(
            source_mesh,
            stop_after=SEPARATE_PART_REPAIR_LIMIT + 1,
        )
    direct_shell_parts = bool(
        preserve_parts and components > SEPARATE_PART_REPAIR_LIMIT
    )
    componentwise_repair = bool(
        preserve_parts and 1 < components <= SEPARATE_PART_REPAIR_LIMIT
    )
    if direct_shell_parts:
        # A source with many art islands (for example a character plus props)
        # would be expensive to remesh component-by-component. Sampling the
        # original shell preserves every authored gap and avoids whole-object
        # scalar-field bridges.
        return source, False

    repair_size = float(settings.repair_voxel_size)
    if repair_size <= 0.0:
        raise VoxelizerError("Repair Voxel Size must be greater than zero.")
    signature = _watertight_source_signature(
        source_mesh,
        repair_size,
        source_symmetry,
        componentwise=componentwise_repair,
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
            and (
                _closed_component_diagnostics_ready(existing_diagnostics)
                if componentwise_repair
                else _diagnostics_ready(existing_diagnostics)
            )
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
        if componentwise_repair:
            _remesh_components_separately(context, working, repair_size)
        else:
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
        repair_ready = (
            _closed_component_diagnostics_ready(repaired_diagnostics)
            if componentwise_repair
            else _diagnostics_ready(repaired_diagnostics)
        )
        if not repair_ready:
            raise SamplingInputError(
                _diagnostic_message(
                    (
                        "Component-wise repair did not produce closed component shells"
                        if componentwise_repair
                        else "Automatic watertight repair did not produce one closed manifold"
                    ),
                    repaired_diagnostics,
                )
            )
        working.data.materials.clear()
        working[SOURCE_SIGNATURE_TAG] = signature
        working[REPAIR_SIZE_TAG] = repair_size
        working[REPAIR_STRATEGY_TAG] = (
            "COMPONENTWISE" if componentwise_repair else "WHOLE_OBJECT"
        )
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
            helper[REPAIR_STRATEGY_TAG] = (
                "COMPONENTWISE" if componentwise_repair else "WHOLE_OBJECT"
            )
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
    total_output_voxels = 0
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
            adaptive_levels = (
                _setting_int(settings, "adaptive_max_level", 2, 0)
                if str(getattr(settings, "sampling_mode", "UNIFORM")) == "ADAPTIVE"
                else 0
            )
            estimated_output = min(
                voxel_budget(settings),
                sparse_estimate * (4 ** adaptive_levels),
            )
            estimated_bytes = estimated_output * 128
            item = {
                "name": source.name,
                "axis_counts": counts,
                "full_grid_samples": full_grid,
                "estimated_candidates": sparse_estimate,
                "estimated_output_voxels": estimated_output,
                "estimated_memory_bytes": estimated_bytes,
                "lattice_index_ranges": [
                    (axis.start, axis.stop - 1) for axis in indices
                ],
            }
            items.append(item)
            total_grid += full_grid
            total_candidates += sparse_estimate
            total_output_voxels += estimated_output
            total_bytes += estimated_bytes
    return {
        "sources": items,
        "source_count": len(items),
        "full_grid_samples": total_grid,
        "estimated_candidates": total_candidates,
        "estimated_output_voxels": total_output_voxels,
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
    roughness = nodes.new("ShaderNodeAttribute")
    roughness.attribute_name = "voxel_roughness"
    metallic = nodes.new("ShaderNodeAttribute")
    metallic.attribute_name = "voxel_metallic"
    emission = nodes.new("ShaderNodeAttribute")
    emission.attribute_name = "voxel_emission"
    links.new(colour.outputs["Color"], shader.inputs["Base Color"])
    links.new(colour.outputs["Alpha"], shader.inputs["Alpha"])
    if shader.inputs.get("Roughness") is not None:
        links.new(roughness.outputs["Fac"], shader.inputs["Roughness"])
    if shader.inputs.get("Metallic") is not None:
        links.new(metallic.outputs["Fac"], shader.inputs["Metallic"])
    emission_color = shader.inputs.get("Emission Color")
    if emission_color is None:
        emission_color = shader.inputs.get("Emission")
    if emission_color is not None:
        links.new(colour.outputs["Color"], emission_color)
    if shader.inputs.get("Emission Strength") is not None:
        links.new(emission.outputs["Fac"], shader.inputs["Emission Strength"])
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


def _linked_upstream_node(socket, node_type: str):
    """Find the first upstream node of ``node_type`` from one input socket."""

    stack = [link.from_node for link in getattr(socket, "links", ())]
    visited = set()
    while stack:
        node = stack.pop(0)
        pointer = node.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)
        if node.type == node_type:
            return node
        for input_socket in node.inputs:
            stack.extend(link.from_node for link in input_socket.links)
    return None


def _material_principled(material: Optional[bpy.types.Material]):
    if material is None or not material.use_nodes or material.node_tree is None:
        return None
    outputs = [
        node for node in material.node_tree.nodes
        if node.type == "OUTPUT_MATERIAL"
    ]
    output = next(
        (node for node in outputs if bool(getattr(node, "is_active_output", False))),
        outputs[0] if outputs else None,
    )
    if output is not None:
        surface = output.inputs.get("Surface")
        if surface is not None:
            principled = _linked_upstream_node(surface, "BSDF_PRINCIPLED")
            if principled is not None:
                return principled
    return next(
        (node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"),
        None,
    )


def _material_image_node(material: Optional[bpy.types.Material]):
    principled = _material_principled(material)
    if principled is None:
        return None
    base_colour = principled.inputs.get("Base Color")
    if base_colour is None:
        return None
    node = _linked_upstream_node(base_colour, "TEX_IMAGE")
    if node is None or getattr(node, "image", None) is None:
        return None
    return node


def _material_flat_colour(
    material: Optional[bpy.types.Material],
    fallback: tuple[float, ...],
) -> tuple[float, ...]:
    principled = _material_principled(material)
    if principled is not None:
        base_colour = principled.inputs.get("Base Color")
        if base_colour is not None and not base_colour.is_linked:
            value = tuple(float(component) for component in base_colour.default_value)
            if len(value) >= 4:
                return value[:4]
    if material is not None:
        value = tuple(float(component) for component in material.diffuse_color)
        if len(value) >= 4:
            return value[:4]
    return fallback


def _active_uv_layer(mesh: bpy.types.Mesh):
    if not mesh.uv_layers:
        return None
    active = getattr(mesh.uv_layers, "active", None)
    if active is not None:
        return active
    return mesh.uv_layers[0]


def _image_node_uv_name(image_node) -> str:
    if image_node is None:
        return ""
    vector = image_node.inputs.get("Vector")
    uv_node = _linked_upstream_node(vector, "UVMAP") if vector is not None else None
    return str(getattr(uv_node, "uv_map", "")) if uv_node is not None else ""


class _ImageBuffer:
    """Immutable image snapshot with repeat/clamp-aware nearest and bilinear reads."""

    def __init__(self, image: bpy.types.Image, extension: str = "REPEAT"):
        self.image = image
        self.extension = extension if extension in {"REPEAT", "EXTEND", "CLIP"} else "REPEAT"
        self.width = 0
        self.height = 0
        self.pixels = array("f")
        try:
            self.width, self.height = (int(value) for value in image.size)
            if self.width > 0 and self.height > 0:
                pixel_count = self.width * self.height * 4
                values = array("f", [0.0]) * pixel_count
                pixels = image.pixels
                try:
                    pixels.foreach_get(values)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    values = array("f", pixels[:])
                if len(values) >= pixel_count:
                    self.pixels = values
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self.width = self.height = 0
            self.pixels = array("f")

    @property
    def estimated_bytes(self) -> int:
        return len(self.pixels) * self.pixels.itemsize

    @property
    def valid(self) -> bool:
        return bool(self.pixels and self.width > 0 and self.height > 0)

    def _index(self, value: int, extent: int) -> Optional[int]:
        if self.extension == "REPEAT":
            return value % extent
        if self.extension == "CLIP" and (value < 0 or value >= extent):
            return None
        return min(extent - 1, max(0, value))

    def _pixel(self, x: int, y: int) -> Optional[tuple[float, ...]]:
        x_index = self._index(x, self.width)
        y_index = self._index(y, self.height)
        if x_index is None or y_index is None:
            return None
        offset = (y_index * self.width + x_index) * 4
        if offset + 3 >= len(self.pixels):
            return None
        raw = self.pixels[offset:offset + 4]
        return (
            _srgb_channel_to_scene_linear(raw[0]),
            _srgb_channel_to_scene_linear(raw[1]),
            _srgb_channel_to_scene_linear(raw[2]),
            raw[3],
        )

    def nearest(self, uv: Vector) -> Optional[tuple[float, ...]]:
        return self._pixel(
            int(math.floor(float(uv.x) * self.width)),
            int(math.floor(float(uv.y) * self.height)),
        )

    def bilinear(self, uv: Vector) -> Optional[tuple[float, ...]]:
        x = float(uv.x) * self.width - 0.5
        y = float(uv.y) * self.height - 0.5
        x0 = math.floor(x)
        y0 = math.floor(y)
        tx = x - x0
        ty = y - y0
        samples = (
            self._pixel(x0, y0),
            self._pixel(x0 + 1, y0),
            self._pixel(x0, y0 + 1),
            self._pixel(x0 + 1, y0 + 1),
        )
        if any(sample is None for sample in samples):
            return None
        first, second, third, fourth = samples
        assert first is not None and second is not None
        assert third is not None and fourth is not None
        return tuple(
            (
                first[channel] * (1.0 - tx) * (1.0 - ty)
                + second[channel] * tx * (1.0 - ty)
                + third[channel] * (1.0 - tx) * ty
                + fourth[channel] * tx * ty
            )
            for channel in range(4)
        )


def _cached_image_buffer(
    image: bpy.types.Image,
    extension: str,
    budget_bytes: int,
) -> _ImageBuffer:
    """Reuse immutable float32 snapshots across sizes and sampling sessions."""

    global _IMAGE_BUFFER_CACHE_BYTES
    key = (
        int(image.as_pointer()),
        str(extension),
        _image_fingerprint(image),
    )
    cached = _IMAGE_BUFFER_CACHE.get(key)
    if cached is not None:
        _IMAGE_BUFFER_CACHE.move_to_end(key)
        return cached

    buffer = _ImageBuffer(image, extension)
    size = buffer.estimated_bytes
    budget_bytes = max(16 * 1024 * 1024, int(budget_bytes))
    if buffer.valid and size <= budget_bytes:
        while _IMAGE_BUFFER_CACHE and _IMAGE_BUFFER_CACHE_BYTES + size > budget_bytes:
            _old_key, old = _IMAGE_BUFFER_CACHE.popitem(last=False)
            _IMAGE_BUFFER_CACHE_BYTES -= old.estimated_bytes
        _IMAGE_BUFFER_CACHE[key] = buffer
        _IMAGE_BUFFER_CACHE_BYTES += size
    return buffer


class ColourSampler:
    """Material-aware UV sampler with filtered footprint error estimation."""

    def __init__(
        self,
        mesh: bpy.types.Mesh,
        uv_name: str,
        image: Optional[bpy.types.Image],
        fallback: Iterable[float],
        *,
        auto_material_images: bool = True,
        filter_mode: str = "BILINEAR",
        image_cache_budget_bytes: int = DEFAULT_CACHE_MEMORY_MB * 1024 * 1024,
        adaptive_features: bool = True,
    ):
        self.mesh = mesh
        self.fallback = tuple(float(component) for component in fallback)
        self.filter_mode = filter_mode if filter_mode in {"NEAREST", "BILINEAR"} else "BILINEAR"
        self.adaptive_features = bool(adaptive_features)
        self.source_bvh = None
        self.triangles_by_polygon: dict[int, list[object]] = {}
        self._loop_triangles_ready = False
        self.material_entries: dict[
            int,
            tuple[Optional[_ImageBuffer], Optional[object], tuple[float, ...]],
        ] = {}
        self._buffers: dict[tuple[int, str], _ImageBuffer] = {}

        requested_uv = mesh.uv_layers.get(uv_name) if uv_name else None
        default_uv = requested_uv or _active_uv_layer(mesh)
        materials = list(mesh.materials)
        slot_count = max(1, len(materials))
        for material_index in range(slot_count):
            material = materials[material_index] if material_index < len(materials) else None
            flat_colour = _material_flat_colour(material, self.fallback)
            image_node = None
            selected_image = image
            if selected_image is None and auto_material_images:
                image_node = _material_image_node(material)
                selected_image = getattr(image_node, "image", None)
            uv_layer = requested_uv
            if uv_layer is None and image_node is not None:
                node_uv_name = _image_node_uv_name(image_node)
                uv_layer = mesh.uv_layers.get(node_uv_name) if node_uv_name else None
            uv_layer = uv_layer or default_uv
            buffer = None
            if selected_image is not None and uv_layer is not None:
                extension = str(getattr(image_node, "extension", "REPEAT"))
                buffer_key = (selected_image.as_pointer(), extension)
                buffer = self._buffers.get(buffer_key)
                if buffer is None:
                    buffer = _cached_image_buffer(
                        selected_image,
                        extension,
                        image_cache_budget_bytes,
                    )
                    self._buffers[buffer_key] = buffer
                if not buffer.valid:
                    buffer = None
            self.material_entries[material_index] = (buffer, uv_layer, flat_colour)

        if any(entry[0] is not None for entry in self.material_entries.values()):
            source_vertices = [vertex.co.copy() for vertex in mesh.vertices]
            source_polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
            self.source_bvh = BVHTree.FromPolygons(
                source_vertices,
                source_polygons,
                all_triangles=False,
            )
        else:
            # Geometry-detail analysis still needs the original surface BVH.
            source_vertices = [vertex.co.copy() for vertex in mesh.vertices]
            source_polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
            self.source_bvh = BVHTree.FromPolygons(
                source_vertices,
                source_polygons,
                all_triangles=False,
            )

        # Uniform sampling never reads geometry-edge error.  Deferring this
        # O(faces) structure avoids a large, unused allocation on dense input.
        self.edge_features = self._build_edge_features() if self.adaptive_features else {}

    @property
    def uses_image(self) -> bool:
        return any(entry[0] is not None for entry in self.material_entries.values())

    def _entry(self, polygon_index: int):
        if 0 <= polygon_index < len(self.mesh.polygons):
            material_index = int(self.mesh.polygons[polygon_index].material_index)
        else:
            material_index = 0
        return self.material_entries.get(
            material_index,
            self.material_entries.get(0, (None, None, self.fallback)),
        )

    def _ensure_loop_triangles(self) -> None:
        if self._loop_triangles_ready:
            return
        self.mesh.calc_loop_triangles()
        for triangle in self.mesh.loop_triangles:
            self.triangles_by_polygon.setdefault(
                triangle.polygon_index,
                [],
            ).append(triangle)
        self._loop_triangles_ready = True

    def _triangle_sample_data(self, point: Vector, polygon_index: int):
        best = None
        best_penalty = math.inf
        triangles: Iterable[object]
        if 0 <= polygon_index < len(self.mesh.polygons):
            polygon = self.mesh.polygons[polygon_index]
            if len(polygon.vertices) == 3 and polygon.loop_total == 3:
                triangles = (
                    _TriangleView(
                        tuple(int(index) for index in polygon.vertices),
                        tuple(range(polygon.loop_start, polygon.loop_start + 3)),
                    ),
                )
            else:
                self._ensure_loop_triangles()
                triangles = self.triangles_by_polygon.get(polygon_index, ())
        else:
            triangles = ()
        for triangle in triangles:
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
            return None
        triangle, weights = best
        buffer, uv_layer, flat_colour = self._entry(polygon_index)
        if buffer is None or uv_layer is None:
            return triangle, weights, None, None, flat_colour
        uv_data = uv_layer.data
        uvs = [uv_data[loop_index].uv.copy() for loop_index in triangle.loops]
        uv = uvs[0] * weights[0] + uvs[1] * weights[1] + uvs[2] * weights[2]
        return triangle, weights, buffer, (uv, uvs), flat_colour

    def _read(self, buffer: _ImageBuffer, uv: Vector):
        if self.filter_mode == "NEAREST":
            return buffer.nearest(uv)
        return buffer.bilinear(uv)

    def sample(self, point: Vector, polygon_index: int):
        data = self._triangle_sample_data(point, polygon_index)
        if data is None:
            return self.fallback
        _triangle, _weights, buffer, uv_data, flat_colour = data
        if buffer is None or uv_data is None:
            return flat_colour
        uv, _uvs = uv_data
        return self._read(buffer, uv) or flat_colour

    def _footprint_samples(
        self,
        point: Vector,
        polygon_index: int,
        cell_size: float,
    ) -> tuple[list[tuple[float, ...]], tuple[float, ...], tuple[float, float]]:
        data = self._triangle_sample_data(point, polygon_index)
        if data is None:
            return [self.fallback], self.fallback, (0.0, 0.0)
        triangle, _weights, buffer, uv_data, flat_colour = data
        if buffer is None or uv_data is None:
            return [flat_colour], flat_colour, (0.0, 0.0)
        uv, uvs = uv_data
        if cell_size <= 0.0:
            centre_colour = self._read(buffer, uv) or flat_colour
            return [centre_colour], centre_colour, (float(uv.x), float(uv.y))
        vertices = [self.mesh.vertices[index].co for index in triangle.vertices]
        u_scale = 0.0
        v_scale = 0.0
        for first, second in ((0, 1), (1, 2), (2, 0)):
            length = float((vertices[second] - vertices[first]).length)
            if length <= 1.0e-12:
                continue
            u_scale = max(u_scale, abs(float(uvs[second].x - uvs[first].x)) / length)
            v_scale = max(v_scale, abs(float(uvs[second].y - uvs[first].y)) / length)
        radius_u = min(0.25, cell_size * 0.45 * u_scale)
        radius_v = min(0.25, cell_size * 0.45 * v_scale)
        samples = []
        for v_offset in (-1.0, 0.0, 1.0):
            for u_offset in (-1.0, 0.0, 1.0):
                sampled = self._read(
                    buffer,
                    Vector((
                        float(uv.x) + u_offset * radius_u,
                        float(uv.y) + v_offset * radius_v,
                    )),
                )
                if sampled is not None:
                    samples.append(sampled)
        centre_colour = self._read(buffer, uv) or flat_colour
        return samples or [centre_colour], centre_colour, (float(uv.x), float(uv.y))

    def _build_edge_features(self):
        edge_polygons: dict[tuple[int, int], list[int]] = {}
        for polygon in self.mesh.polygons:
            indices = tuple(int(index) for index in polygon.vertices)
            for offset, first in enumerate(indices):
                second = indices[(offset + 1) % len(indices)]
                edge_polygons.setdefault(tuple(sorted((first, second))), []).append(polygon.index)
        features: dict[int, list[tuple[Vector, Vector, float]]] = {}
        for (first, second), polygons in edge_polygons.items():
            if len(polygons) != 2:
                angle = 180.0
            else:
                first_normal = self.mesh.polygons[polygons[0]].normal
                second_normal = self.mesh.polygons[polygons[1]].normal
                cosine = max(-1.0, min(1.0, float(first_normal.dot(second_normal))))
                angle = math.degrees(math.acos(cosine))
            if angle <= 1.0e-5:
                continue
            start = self.mesh.vertices[first].co.copy()
            end = self.mesh.vertices[second].co.copy()
            for polygon_index in polygons:
                features.setdefault(polygon_index, []).append((start, end, angle))
        return features

    @staticmethod
    def _point_segment_distance(point: Vector, start: Vector, end: Vector) -> float:
        segment = end - start
        denominator = float(segment.length_squared)
        if denominator <= 1.0e-16:
            return float((point - start).length)
        factor = max(0.0, min(1.0, float((point - start).dot(segment)) / denominator))
        return float((point - (start + segment * factor)).length)

    def _geometry_angle(self, point: Vector, polygon_index: int, cell_size: float) -> float:
        radius = max(1.0e-9, cell_size * math.sqrt(3.0) * 0.65)
        maximum = 0.0
        for start, end, angle in self.edge_features.get(polygon_index, ()):
            if self._point_segment_distance(point, start, end) <= radius:
                maximum = max(maximum, angle)
        return maximum

    def analyse(self, point: Vector, polygon_index: int, cell_size: float) -> _ColourAnalysis:
        samples, centre_colour, source_uv = self._footprint_samples(
            point,
            polygon_index,
            cell_size,
        )
        if len(samples) <= 1:
            texture_error = 0.0
        else:
            texture_error = max(
                max(sample[channel] for sample in samples)
                - min(sample[channel] for sample in samples)
                for channel in range(4)
            )
        return _ColourAnalysis(
            # Footprint samples detect unresolved detail; the displayed colour
            # remains the filtered value at the voxel centre. Averaging the
            # footprint here visibly washed out rings and other thin markings.
            colour=centre_colour,
            texture_error=float(texture_error),
            geometry_angle=self._geometry_angle(point, polygon_index, cell_size),
            source_uv=source_uv,
        )

    def analyse_nearest(self, query_point: Vector, cell_size: float) -> _ColourAnalysis:
        if self.source_bvh is None:
            return _ColourAnalysis(self.fallback, 0.0, 0.0)
        nearest = self.source_bvh.find_nearest(query_point)
        if nearest is None or nearest[0] is None or nearest[2] is None:
            return _ColourAnalysis(self.fallback, 0.0, 0.0)
        location, _normal, polygon_index, _distance = nearest
        return self.analyse(location, polygon_index, cell_size)

    def _map_uniform_nearest(self, query_point: Vector):
        """Map one point to an image/UV without reading a texture pixel."""

        if self.source_bvh is None:
            return None, (0.0, 0.0), self.fallback
        nearest = self.source_bvh.find_nearest(query_point)
        if nearest is None or nearest[0] is None or nearest[2] is None:
            return None, (0.0, 0.0), self.fallback
        location, _normal, polygon_index, _distance = nearest
        data = self._triangle_sample_data(location, polygon_index)
        if data is None:
            return None, (0.0, 0.0), self.fallback
        _triangle, _weights, buffer, uv_data, flat_colour = data
        if buffer is None or uv_data is None:
            return None, (0.0, 0.0), flat_colour
        uv, _uvs = uv_data
        return buffer, (float(uv.x), float(uv.y)), flat_colour

    def analyse_nearest_batch(
        self,
        query_points: Iterable[Vector],
        *,
        requested_backend: str = "AUTO",
        gpu_batch_size: int = 65_536,
        gpu_memory_limit_mb: int = 512,
    ) -> tuple[list[_ColourAnalysis], dict[str, object]]:
        """Resolve UVs on CPU, then batch texture reads on the selected backend."""

        points = list(query_points)
        mapped = [self._map_uniform_nearest(point) for point in points]
        colours: list[tuple[float, ...] | None] = [None] * len(mapped)
        uvs = [value[1] for value in mapped]
        groups: dict[_ImageBuffer, list[tuple[int, tuple[float, float]]]] = {}
        for index, (buffer, uv, flat_colour) in enumerate(mapped):
            if buffer is None:
                colours[index] = flat_colour
            else:
                groups.setdefault(buffer, []).append((index, uv))

        decision = gpu_backend.resolve_backend(requested_backend)
        used_gpu = False
        reasons = [decision.reason]
        for buffer, entries in groups.items():
            sampled = None
            group_decision = decision
            if decision.used == "GPU":
                sampled, group_decision = gpu_backend.sample_image(
                    buffer.image,
                    (uv for _index, uv in entries),
                    extension=buffer.extension,
                    filter_mode=self.filter_mode,
                    requested=requested_backend,
                    batch_size=gpu_batch_size,
                    source_pixels=buffer.pixels,
                    memory_limit_mb=gpu_memory_limit_mb,
                )
                reasons.append(group_decision.reason)
            if sampled is not None:
                used_gpu = True
                for (index, _uv), colour in zip(entries, sampled):
                    colours[index] = colour
            else:
                for index, uv in entries:
                    colours[index] = self._read(buffer, Vector(uv)) or mapped[index][2]

        analyses = [
            _ColourAnalysis(
                colour=tuple(colour or self.fallback),
                texture_error=0.0,
                geometry_angle=0.0,
                source_uv=uv,
            )
            for colour, uv in zip(colours, uvs)
        ]
        return analyses, {
            "requested": str(requested_backend).upper(),
            "used": "GPU" if used_gpu else "CPU",
            "available": bool(decision.available),
            "backend": decision.backend,
            "device": decision.device,
            "groups": len(groups),
            "samples": len(points),
            "reason": "; ".join(dict.fromkeys(reasons)),
        }

    def sample_nearest_original(self, query_point: Vector):
        return self.analyse_nearest(query_point, 0.0).colour


@dataclass
class SourceSamplingSession:
    """Prepared source data reused while one model is sampled at many sizes."""

    source_pointer: int
    source_name: str
    source_mesh: bpy.types.Mesh
    source_symmetry: dict[str, object]
    sampling_object: bpy.types.Object
    sampling_mesh: bpy.types.Mesh
    sampling_symmetry: dict[str, object]
    bvh: BVHTree
    sampler: ColourSampler
    bounds_min: Vector
    bounds_max: Vector
    helper_rebuilt: bool
    separate_parts_guard_used: bool
    base_key: str
    timings: dict[str, float]
    gpu_occupancy_resource: object | None = None
    occupancy_index_cache: OrderedDict[tuple[object, ...], object] = field(
        default_factory=OrderedDict
    )
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.gpu_occupancy_resource = None
        self.occupancy_index_cache.clear()
        meshes = [self.source_mesh]
        if self.sampling_mesh is not self.source_mesh:
            meshes.append(self.sampling_mesh)
        for mesh in meshes:
            try:
                if bpy.data.meshes.get(mesh.name) is mesh and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            except (ReferenceError, RuntimeError):
                pass


def _session_base_key(mesh: bpy.types.Mesh, settings) -> str:
    digest = hashlib.sha256()
    digest.update(source_signature(mesh, 0.0).encode("ascii"))
    digest.update(_colour_inputs_fingerprint(mesh, settings))
    digest.update(struct.pack("<d", float(settings.repair_voxel_size)))
    digest.update(b"\x01" if bool(settings.auto_watertight_copy) else b"\x00")
    digest.update(
        b"\x01" if bool(getattr(settings, "preserve_disconnected_parts", True)) else b"\x00"
    )
    return digest.hexdigest()


def _session_sampling_key(session: SourceSamplingSession, settings) -> str:
    """Build a size/settings key without rehashing source geometry or pixels."""

    digest = hashlib.sha256(session.base_key.encode("ascii"))
    digest.update(struct.pack("<d", float(settings.voxel_size)))
    digest.update(str(getattr(settings, "grid_origin_mode", "BOUNDS")).encode("ascii"))
    digest.update(struct.pack(
        "<3d",
        *(float(value) for value in getattr(settings, "grid_origin", (0.0, 0.0, 0.0))),
    ))
    digest.update(b"\x01" if bool(getattr(settings, "use_sparse_candidates", True)) else b"\x00")
    digest.update(struct.pack(
        "<I",
        _setting_int(settings, "sparse_grid_threshold", 50_000, 0),
    ))
    digest.update(str(getattr(settings, "sampling_mode", "UNIFORM")).encode("ascii"))
    digest.update(struct.pack(
        "<3I2d",
        ADAPTIVE_SCHEMA_VERSION,
        _setting_int(settings, "adaptive_max_level", 0, 0),
        _setting_int(settings, "adaptive_geometry_max_level", 1, 0),
        float(getattr(settings, "adaptive_texture_threshold", 0.16)),
        float(getattr(settings, "adaptive_geometry_angle", 35.0)),
    ))
    digest.update(str(getattr(settings, "texture_filter", "BILINEAR")).encode("ascii"))
    digest.update(str(getattr(settings, "compute_backend", "AUTO")).encode("ascii"))
    digest.update(struct.pack(
        "<5Q",
        sample_budget(settings),
        voxel_budget(settings),
        _setting_int(
            settings,
            "candidate_expansion_budget",
            sample_budget(settings) * 32,
            sample_budget(settings),
        ),
        _setting_int(settings, "gpu_batch_size", 65_536, 1_024),
        _setting_int(settings, "gpu_memory_limit_mb", 512, 64),
    ))
    return digest.hexdigest()


def prepare_sampling_session(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
) -> SourceSamplingSession:
    """Prepare immutable mesh snapshots, diagnostics, BVHs, and texture state."""

    validate_settings(settings)
    timings: dict[str, float] = {}
    source_snapshot = None
    sampling_snapshot = None
    started_total = time.perf_counter()
    try:
        started = time.perf_counter()
        with evaluated_local_mesh(context, source) as source_mesh:
            timings["evaluated_source"] = time.perf_counter() - started
            started = time.perf_counter()
            source_diagnostics = mesh_readiness_diagnostics(source_mesh)
            timings["source_diagnostics"] = time.perf_counter() - started
            started = time.perf_counter()
            source_symmetry = reflection_symmetry_diagnostics(source_mesh)
            timings["source_symmetry"] = time.perf_counter() - started
            started = time.perf_counter()
            source_component_count = int(source_diagnostics.get("components", 0))
            if (
                bool(getattr(settings, "preserve_disconnected_parts", True))
                and not _diagnostics_ready(source_diagnostics)
                and source_component_count <= 1
            ):
                source_component_count = mesh_component_count(
                    source_mesh,
                    stop_after=SEPARATE_PART_REPAIR_LIMIT + 1,
                )
            sampling_object, helper_rebuilt = ensure_sampling_object(
                context,
                source,
                settings,
                source_mesh=source_mesh,
                source_diagnostics=source_diagnostics,
                source_symmetry=source_symmetry,
                component_count=source_component_count,
            )
            separate_parts_guard_used = bool(
                sampling_object is source
                and bool(getattr(settings, "preserve_disconnected_parts", True))
                and not _diagnostics_ready(source_diagnostics)
                and source_component_count > 1
            )
            timings["sampling_helper"] = time.perf_counter() - started
            started = time.perf_counter()
            source_snapshot = source_mesh.copy()
            timings["source_snapshot"] = time.perf_counter() - started

        if sampling_object is source:
            sampling_snapshot = source_snapshot
        else:
            started = time.perf_counter()
            with evaluated_local_mesh(context, sampling_object) as sampling_mesh:
                sampling_snapshot = sampling_mesh.copy()
            timings["sampling_snapshot"] = time.perf_counter() - started

        assert source_snapshot is not None and sampling_snapshot is not None
        started = time.perf_counter()
        sampling_symmetry = reflection_symmetry_diagnostics(sampling_snapshot)
        symmetry_preserved, missing_axes = _required_axes_preserved(
            source_symmetry,
            sampling_symmetry,
        )
        timings["sampling_symmetry"] = time.perf_counter() - started
        if not symmetry_preserved:
            raise VoxelizerError(
                "Sampling geometry does not preserve proved source reflection "
                f"symmetry on axis/axes: {', '.join(missing_axes)}."
            )

        started = time.perf_counter()
        sampling_vertices = [vertex.co.copy() for vertex in sampling_snapshot.vertices]
        sampling_polygons = [tuple(polygon.vertices) for polygon in sampling_snapshot.polygons]
        bvh = BVHTree.FromPolygons(
            sampling_vertices,
            sampling_polygons,
            all_triangles=False,
        )
        timings["sampling_bvh"] = time.perf_counter() - started
        if bvh is None:
            raise VoxelizerError("Could not build a surface acceleration structure.")

        started = time.perf_counter()
        sampler = ColourSampler(
            source_snapshot,
            settings.uv_map,
            settings.base_color_image,
            settings.fallback_color,
            auto_material_images=bool(getattr(settings, "auto_material_images", True)),
            filter_mode=str(getattr(settings, "texture_filter", "BILINEAR")),
            image_cache_budget_bytes=cache_budget_bytes(settings),
            adaptive_features=(
                str(getattr(settings, "sampling_mode", "UNIFORM")) == "ADAPTIVE"
            ),
        )
        timings["colour_sampler"] = time.perf_counter() - started

        started = time.perf_counter()
        bounds_min = Vector(tuple(
            min(vertex.co[axis] for vertex in sampling_snapshot.vertices)
            for axis in range(3)
        ))
        bounds_max = Vector(tuple(
            max(vertex.co[axis] for vertex in sampling_snapshot.vertices)
            for axis in range(3)
        ))
        # The session owns immutable snapshots, so an ephemeral identity is
        # sufficient and avoids hashing the full geometry/UV payload again.
        base_key = hashlib.sha256(
            f"{source.as_pointer()}:{source.name}:{started_total:.17g}".encode("utf-8")
        ).hexdigest()
        timings["bounds_and_key"] = time.perf_counter() - started
        timings["total"] = time.perf_counter() - started_total
        return SourceSamplingSession(
            source_pointer=source.as_pointer(),
            source_name=source.name,
            source_mesh=source_snapshot,
            source_symmetry=source_symmetry,
            sampling_object=sampling_object,
            sampling_mesh=sampling_snapshot,
            sampling_symmetry=sampling_symmetry,
            bvh=bvh,
            sampler=sampler,
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            helper_rebuilt=helper_rebuilt,
            separate_parts_guard_used=separate_parts_guard_used,
            base_key=base_key,
            timings=timings,
        )
    except Exception:
        meshes = [mesh for mesh in (source_snapshot, sampling_snapshot) if mesh is not None]
        for mesh in dict.fromkeys(meshes):
            try:
                if bpy.data.meshes.get(mesh.name) is mesh and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            except (ReferenceError, RuntimeError):
                pass
        raise


def _source_session_cache_key(
    source: bpy.types.Object,
    settings,
) -> str:
    """Cheap invalidation key for reusable interactive source preparation."""

    mesh = source.data
    digest = hashlib.sha256()
    digest.update(b"CHROMOXEL_SOURCE_SESSION_V1")
    digest.update(struct.pack(
        "<4Q3I",
        _runtime_id_pointer(source),
        _runtime_id_revision(source),
        _runtime_id_pointer(mesh),
        _runtime_id_revision(mesh),
        len(mesh.vertices),
        len(mesh.edges),
        len(mesh.polygons),
    ))
    digest.update(struct.pack("<d", float(settings.repair_voxel_size)))
    digest.update(b"\x01" if bool(settings.auto_watertight_copy) else b"\x00")
    digest.update(
        b"\x01" if bool(getattr(settings, "preserve_disconnected_parts", True)) else b"\x00"
    )
    digest.update(_runtime_colour_inputs_fingerprint(source, settings))
    digest.update(str(getattr(settings, "sampling_mode", "UNIFORM")).encode("ascii"))
    digest.update(str(getattr(settings, "texture_filter", "BILINEAR")).encode("ascii"))
    return digest.hexdigest()


def acquire_sampling_session(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
) -> tuple[SourceSamplingSession, bool]:
    """Return a cached source session, preparing it only after user action.

    The cache is deliberately small because a session owns immutable mesh
    snapshots, two BVHs, texture state, and optional GPU triangle/index data.
    Opening or redrawing the N-panel never calls this function.
    """

    key = _source_session_cache_key(source, settings)
    session = _SOURCE_SESSION_CACHE.get(key)
    if session is not None and not session.closed:
        _SOURCE_SESSION_CACHE.move_to_end(key)
        return session, True
    if session is not None:
        _SOURCE_SESSION_CACHE.pop(key, None)
    session = prepare_sampling_session(context, source, settings)
    session.timings["cache_hit"] = False
    _SOURCE_SESSION_CACHE[key] = session
    _SOURCE_SESSION_CACHE.move_to_end(key)
    while len(_SOURCE_SESSION_CACHE) > _SOURCE_SESSION_CACHE_LIMIT:
        _old_key, old_session = _SOURCE_SESSION_CACHE.popitem(last=False)
        old_session.close()
    return session, False


@contextmanager
def sampling_session(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
) -> Iterator[SourceSamplingSession]:
    session = prepare_sampling_session(context, source, settings)
    try:
        yield session
    finally:
        session.close()


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


def _cell_key(centre: Vector, size: float) -> tuple[float, float, float, float]:
    return (
        round(float(centre.x), 10),
        round(float(centre.y), 10),
        round(float(centre.z), 10),
        round(float(size), 10),
    )


def _symmetry_orbit_centres(
    centre: Vector,
    source_symmetry: dict[str, object],
) -> list[Vector]:
    axes = source_symmetry["axes"]
    assert isinstance(axes, dict)
    proven_axes = set(str(axis) for axis in source_symmetry["proven_axes"])
    variants = []
    for axis, axis_name in enumerate(_AXIS_NAMES):
        value = float(centre[axis])
        if axis_name in proven_axes:
            diagnostics = axes[axis_name]
            assert isinstance(diagnostics, dict)
            mirrored = 2.0 * float(diagnostics["plane"]) - value
            variants.append((value,) if abs(mirrored - value) <= 1.0e-10 else (value, mirrored))
        else:
            variants.append((value,))
    unique: dict[tuple[float, float, float], Vector] = {}
    for coordinate in product(*variants):
        vector = Vector(coordinate)
        key = tuple(round(float(value), 10) for value in vector)
        unique[key] = vector
    return [unique[key] for key in sorted(unique)]


def _canonical_orbit_key(
    centre: Vector,
    size: float,
    source_symmetry: dict[str, object],
) -> tuple[float, float, float, float]:
    return min(
        _cell_key(candidate, size)
        for candidate in _symmetry_orbit_centres(centre, source_symmetry)
    )


def _nearest_surface_overlaps_adaptive_cell(
    centre: Vector,
    extent: Vector,
    nearest_location: Vector,
) -> bool:
    """Reject circumsphere-only hits that cannot survive subdivision.

    The uniform compatibility path deliberately keeps the historic spherical
    surface shell. Adaptive cells additionally require the nearest surface point
    to sit inside a slightly expanded cell AABB. The ten-percent axis margin
    retains edge/corner coverage while preventing a thin textured surface from
    being hidden behind a coarse, non-intersecting outer layer.
    """

    return all(
        abs(float(nearest_location[axis]) - float(centre[axis]))
        <= float(extent[axis]) * (0.5 + ADAPTIVE_CELL_AXIS_MARGIN) + 1.0e-9
        for axis in range(3)
    )


def _planar_refinement_axis(
    cell: _VoxelCell,
    bvh: BVHTree,
) -> Optional[int]:
    """Return the normal axis for surface-preserving grid-aligned refinement."""
    nearest = bvh.find_nearest(cell.centre)
    if nearest is None or nearest[1] is None:
        return None
    normal = nearest[1].normalized()
    axis = max(range(3), key=lambda index: abs(float(normal[index])))
    if abs(float(normal[axis])) < ADAPTIVE_PLANAR_NORMAL_ALIGNMENT:
        return None
    return axis


def _adaptive_refine_cells_iter(
    source: bpy.types.Object,
    settings,
    *,
    bvh: BVHTree,
    sampler: ColourSampler,
    source_symmetry: dict[str, object],
    cells: list[_VoxelCell],
) -> Iterator[SamplingProgress]:
    """Refine high-error surface cells on a deterministic power-of-two lattice."""

    maximum_level = _setting_int(settings, "adaptive_max_level", 2, 0)
    geometry_maximum_level = min(
        maximum_level,
        _setting_int(settings, "adaptive_geometry_max_level", 1, 0),
    )
    texture_threshold = max(
        1.0e-6,
        float(getattr(settings, "adaptive_texture_threshold", 0.16)),
    )
    geometry_angle = max(
        1.0e-3,
        float(getattr(settings, "adaptive_geometry_angle", 35.0)),
    )
    maximum_voxels = voxel_budget(settings)
    refinement_test_limit = sample_budget(settings)
    chunk_size = sampling_chunk_size(settings)
    tests = 0
    refined_parent_count = 0
    planar_refined_parent_count = 0
    budget_limited = False
    level_reports = []
    working = list(cells)

    for level in range(maximum_level):
        groups: dict[tuple[float, float, float, float], list[_VoxelCell]] = {}
        for cell in working:
            if cell.level != level:
                continue
            groups.setdefault(
                _canonical_orbit_key(cell.centre, cell.size, source_symmetry),
                [],
            ).append(cell)
        candidates = []
        for key, group in groups.items():
            score = max(
                max(
                    cell.texture_error / max(texture_threshold, 1.0e-9),
                    (
                        cell.geometry_angle / max(geometry_angle, 1.0e-9)
                        if level < geometry_maximum_level
                        else 0.0
                    ),
                )
                for cell in group
            )
            if score >= 1.0:
                candidates.append((score, key, group))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        output = {_cell_key(cell.centre, cell.size): cell for cell in working}
        refined_this_level = 0
        children_this_level = 0
        for candidate_number, (_score, _key, group) in enumerate(candidates, start=1):
            canonical_parent = min(
                group,
                key=lambda cell: _cell_key(cell.centre, cell.size),
            )
            child_size = canonical_parent.size * 0.5
            child_offset = child_size * 0.5
            planar_axis = _planar_refinement_axis(
                canonical_parent,
                bvh,
            )
            child_signs = (
                tuple(
                    0 if axis == planar_axis else sign[axis]
                    for axis in range(3)
                )
                for sign in _CUBE_CORNERS
            ) if planar_axis is not None else iter(_CUBE_CORNERS)
            child_signs = tuple(dict.fromkeys(child_signs))
            if tests + len(child_signs) > refinement_test_limit:
                budget_limited = True
                break
            generated: dict[tuple[float, float, float, float], _VoxelCell] = {}
            for signs in child_signs:
                tests += 1
                child_centre = canonical_parent.centre + Vector(tuple(
                    sign * child_offset for sign in signs
                ))
                child_extent = Vector((child_size, child_size, child_size))
                if planar_axis is not None:
                    child_extent[planar_axis] = canonical_parent.extent[planar_axis]
                shell_distance = float(child_extent.length) * 0.52
                nearest = bvh.find_nearest(child_centre, shell_distance)
                if (
                    nearest is None
                    or nearest[0] is None
                    or nearest[3] is None
                    or float(nearest[3]) > shell_distance
                    or not _nearest_surface_overlaps_adaptive_cell(
                        child_centre,
                        child_extent,
                        nearest[0],
                    )
                ):
                    continue
                for orbit_centre in _symmetry_orbit_centres(
                    child_centre,
                    source_symmetry,
                ):
                    analysis = sampler.analyse_nearest(orbit_centre, child_size)
                    child = _VoxelCell(
                        centre=orbit_centre,
                        size=child_size,
                        extent=child_extent.copy(),
                        level=level + 1,
                        colour=analysis.colour,
                        texture_error=analysis.texture_error,
                        geometry_angle=analysis.geometry_angle,
                        source_uv=analysis.source_uv,
                    )
                    generated[_cell_key(child.centre, child.size)] = child
            if not generated:
                continue
            parent_keys = {_cell_key(cell.centre, cell.size) for cell in group}
            projected_count = len(output) - len(parent_keys) + sum(
                key not in output for key in generated
            )
            if projected_count > maximum_voxels:
                budget_limited = True
                continue
            for parent_key in parent_keys:
                output.pop(parent_key, None)
            output.update(generated)
            refined_this_level += len(group)
            refined_parent_count += len(group)
            if planar_axis is not None:
                planar_refined_parent_count += len(group)
            children_this_level += len(generated)
            if candidate_number % chunk_size == 0:
                yield SamplingProgress(
                    "ADAPTIVE",
                    candidate_number,
                    max(1, len(candidates)),
                    f"Refining level {level + 1} detail for {source.name}",
                )
        working = sorted(
            output.values(),
            key=lambda cell: (
                cell.level,
                float(cell.centre.z),
                float(cell.centre.y),
                float(cell.centre.x),
            ),
        )
        level_reports.append({
            "level": level + 1,
            "candidate_groups": len(candidates),
            "refined_parents": refined_this_level,
            "generated_children": children_this_level,
            "voxel_count": len(working),
        })
        yield SamplingProgress(
            "ADAPTIVE",
            len(candidates),
            max(1, len(candidates)),
            f"Completed adaptive level {level + 1} for {source.name}",
        )
        if refined_this_level == 0 or budget_limited:
            break

    histogram = Counter(cell.level for cell in working)
    return working, {
        "schema": ADAPTIVE_SCHEMA_VERSION,
        "enabled": maximum_level > 0,
        "max_level": maximum_level,
        "texture_threshold": texture_threshold,
        "geometry_angle_degrees": geometry_angle,
        "geometry_max_level": geometry_maximum_level,
        "refinement_tests": tests,
        "refinement_test_limit": refinement_test_limit,
        "refined_parent_count": refined_parent_count,
        "planar_refined_parent_count": planar_refined_parent_count,
        "budget_limited": budget_limited,
        "level_histogram": {str(level): count for level, count in sorted(histogram.items())},
        "levels": level_reports,
    }


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
    separate_parts_guard_used: bool = False,
    session: Optional[SourceSamplingSession] = None,
    occupancy_only: bool = False,
) -> Iterator[SamplingProgress]:
    """Incrementally sample while evaluated mesh leases remain live."""

    phase_started_total = time.perf_counter()
    phase_timings: dict[str, float] = {}
    phase_started = time.perf_counter()
    if session is not None:
        if session.closed or session.source_pointer != source.as_pointer():
            raise VoxelizerError("Sampling session is closed or belongs to another source.")
        sampling_symmetry = session.sampling_symmetry
        bvh = session.bvh
        bounds_min = session.bounds_min
        bounds_max = session.bounds_max
    else:
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

        bounds_min = Vector(tuple(
            min(vertex.co[axis] for vertex in sampling_mesh.vertices)
            for axis in range(3)
        ))
        bounds_max = Vector(tuple(
            max(vertex.co[axis] for vertex in sampling_mesh.vertices)
            for axis in range(3)
        ))
    phase_timings["geometry_setup"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
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
    phase_timings["lattice"] = time.perf_counter() - phase_started

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
    phase_started = time.perf_counter()
    candidate_expansion_tests = 0
    if use_sparse_candidates:
        sampling_mesh.calc_loop_triangles()
        triangles = tuple(sampling_mesh.loop_triangles)
        candidate_set: set[tuple[int, int, int]] | None = set()
        candidate_mask = None
        use_dense_candidate_mask = canonical_grid_count <= 8_000_000
        if use_dense_candidate_mask:
            try:
                import numpy as np

                candidate_mask = np.zeros(canonical_grid_count, dtype=np.bool_)
                candidate_set = None
            except ImportError:
                candidate_mask = None
                candidate_set = set()
        next_yield = chunk_size
        if candidate_mask is not None:
            # Dense-mask mode is exact but avoids one Python triangle/AABB
            # traversal.  Convert loop triangles to float32 arrays in bulk,
            # derive bounded lattice boxes with vectorized searchsorted, then
            # rasterize only the small unique span shapes in NumPy chunks.
            vertex_values = array("f", [0.0]) * (len(sampling_mesh.vertices) * 3)
            triangle_values = array("i", [0]) * (len(triangles) * 3)
            sampling_mesh.vertices.foreach_get("co", vertex_values)
            sampling_mesh.loop_triangles.foreach_get("vertices", triangle_values)
            vertex_view = np.frombuffer(vertex_values, dtype=np.float32).reshape((-1, 3))
            triangle_view = np.frombuffer(triangle_values, dtype=np.int32).reshape((-1, 3))
            triangle_coordinates = vertex_view[triangle_view]
            minimums = triangle_coordinates.min(axis=1)
            maximums = triangle_coordinates.max(axis=1)
            lower_view = np.empty((len(triangles), 3), dtype=np.int32)
            upper_view = np.empty((len(triangles), 3), dtype=np.int32)
            for axis in range(3):
                coordinates = np.asarray(lattice_coordinates[axis], dtype=np.float32)
                lower_view[:, axis] = np.searchsorted(
                    coordinates,
                    minimums[:, axis] - shell_distance,
                    side="left",
                )
                upper_view[:, axis] = np.searchsorted(
                    coordinates,
                    maximums[:, axis] + shell_distance,
                    side="right",
                )
                lower_view[:, axis] = np.maximum(
                    lower_view[:, axis],
                    canonical_offset_floors[axis],
                ) - canonical_offset_floors[axis]
                upper_view[:, axis] = np.maximum(
                    upper_view[:, axis],
                    canonical_offset_floors[axis],
                ) - canonical_offset_floors[axis]
            spans = upper_view - lower_view
            expansion_counts = np.prod(spans, axis=1, dtype=np.int64)
            candidate_expansion_tests = int(expansion_counts.sum(dtype=np.int64))
            if candidate_expansion_tests > candidate_expansion_budget:
                raise VoxelizerError(
                    "Triangle candidate expansion exceeded the configured "
                    f"budget ({candidate_expansion_budget:,}); increase "
                    "Voxel Size or Candidate Expansion Budget."
                )
            unique_spans, span_groups = np.unique(spans, axis=0, return_inverse=True)
            stride_y = canonical_counts[0]
            stride_z = canonical_counts[0] * canonical_counts[1]
            for span_index, span in enumerate(unique_spans):
                dx, dy, dz = (int(value) for value in span)
                if dx <= 0 or dy <= 0 or dz <= 0:
                    continue
                local_offsets = np.asarray([
                    z * stride_z + y * stride_y + x
                    for z, y, x in product(range(dz), range(dy), range(dx))
                ], dtype=np.int64)
                starts = lower_view[span_groups == span_index]
                base_indices = (
                    starts[:, 2].astype(np.int64) * stride_z
                    + starts[:, 1].astype(np.int64) * stride_y
                    + starts[:, 0].astype(np.int64)
                )
                base_chunk = max(1, min(chunk_size, 2_000_000 // max(1, len(local_offsets))))
                for first in range(0, len(base_indices), base_chunk):
                    indices = (
                        base_indices[first:first + base_chunk, None]
                        + local_offsets[None, :]
                    )
                    candidate_mask[indices.ravel()] = True
                yield SamplingProgress(
                    "CANDIDATES",
                    span_index + 1,
                    max(1, len(unique_spans)),
                    f"Rasterizing sparse candidates for {source.name}",
                )
        else:
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
                assert candidate_set is not None
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
        if candidate_mask is not None:
            nonzero = np.flatnonzero(candidate_mask)
            if len(nonzero) > work_limit:
                raise VoxelizerError(
                    f"Sparse surface candidates exceeded {work_limit:,}; "
                    "increase Voxel Size or the Sample Budget."
                )
            z_offsets, remainder = np.divmod(
                nonzero,
                canonical_counts[0] * canonical_counts[1],
            )
            y_offsets, x_offsets = np.divmod(remainder, canonical_counts[0])
            candidate_offsets = list(zip(
                (x_offsets + canonical_offset_floors[0]).tolist(),
                (y_offsets + canonical_offset_floors[1]).tolist(),
                (z_offsets + canonical_offset_floors[2]).tolist(),
            ))
        else:
            assert candidate_set is not None
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
        candidate_offsets = _CanonicalGridOffsets(
            canonical_offset_floors,
            counts,
        )
        candidate_expansion_tests = len(candidate_offsets)
    candidate_count = len(candidate_offsets)
    if not candidate_offsets:
        raise VoxelizerError("No sampling candidates were produced.")
    phase_timings["candidates"] = time.perf_counter() - phase_started
    yield SamplingProgress(
        "CANDIDATES",
        candidate_count,
        candidate_count,
        f"Prepared {candidate_count:,} candidates for {source.name}",
    )

    adaptive_enabled = (
        str(getattr(settings, "sampling_mode", "UNIFORM")) == "ADAPTIVE"
        and _setting_int(settings, "adaptive_max_level", 2, 0) > 0
    )
    if occupancy_only and adaptive_enabled:
        raise VoxelizerError("Occupancy-only fitting is available for Uniform sampling only.")
    sampler = None if occupancy_only else (
        session.sampler if session is not None else ColourSampler(
            source_mesh,
            settings.uv_map,
            settings.base_color_image,
            settings.fallback_color,
            auto_material_images=bool(getattr(settings, "auto_material_images", True)),
            filter_mode=str(getattr(settings, "texture_filter", "BILINEAR")),
            image_cache_budget_bytes=cache_budget_bytes(settings),
            adaptive_features=adaptive_enabled,
        )
    )
    analysis_cell_size = voxel_size if adaptive_enabled else 0.0
    requested_backend = str(getattr(settings, "compute_backend", "AUTO"))
    gpu_batch_size = _setting_int(settings, "gpu_batch_size", 65_536, 1_024)
    gpu_memory_limit_mb = _setting_int(settings, "gpu_memory_limit_mb", 512, 64)
    backend_diagnostics: dict[str, object] = {
        "requested": requested_backend.upper(),
        "used": "CPU",
        "available": False,
        "reason": "Adaptive analysis uses the CPU path" if adaptive_enabled else "No occupied points",
    }
    centres: list[Vector] = []
    colours: list[tuple[float, ...]] = []
    analyses: list[_ColourAnalysis] = []
    surface_locations: list[Vector] = []
    occupied_seed_count = 0
    orbit_added_count = 0
    adaptive_rejected_seed_count = 0
    maximum_voxels = voxel_budget(settings)
    phase_started = time.perf_counter()
    occupancy_prefilter = None
    occupancy_diagnostics: dict[str, object] = {
        "used": False,
        "mode": "CPU_BVH",
        "reason": (
            "Adaptive sampling uses the CPU occupancy path"
            if adaptive_enabled
            else "CPU backend selected"
            if requested_backend.upper() == "CPU"
            else "Auto kept small occupancy work on CPU"
        ),
    }
    occupancy_gpu_requested = (
        requested_backend.upper() == "GPU"
        or (
            requested_backend.upper() == "AUTO"
            and candidate_count >= 50_000
        )
    )
    if not adaptive_enabled and occupancy_gpu_requested:
        occupancy_index_key = (
            round(voxel_size, 12),
            tuple(counts),
            tuple(round(float(axis[0]), 12) for axis in lattice_coordinates),
            round(shell_distance, 12),
        )
        cached_occupancy_index = (
            session.occupancy_index_cache.get(occupancy_index_key)
            if session is not None
            else None
        )
        occupancy_prefilter, occupancy_decision, occupancy_diagnostics, resource, index_resource = (
            gpu_backend.sample_uniform_occupancy(
                sampling_mesh,
                candidate_offsets,
                lattice_coordinates,
                shell_distance,
                requested=requested_backend,
                batch_size=gpu_batch_size,
                memory_limit_mb=gpu_memory_limit_mb,
                resource=(session.gpu_occupancy_resource if session is not None else None),
                index_resource=cached_occupancy_index,
            )
        )
        if session is not None:
            session.gpu_occupancy_resource = resource
            if index_resource is not None:
                session.occupancy_index_cache[occupancy_index_key] = index_resource
                session.occupancy_index_cache.move_to_end(occupancy_index_key)
                while len(session.occupancy_index_cache) > 2:
                    session.occupancy_index_cache.popitem(last=False)
        if occupancy_decision.used != "GPU":
            occupancy_prefilter = None
    bvh_query_count = 0
    if not proven_axes:
        for candidate_number, (x_offset, y_offset, z_offset) in enumerate(
            candidate_offsets,
            start=1,
        ):
            if occupancy_prefilter is not None and not occupancy_prefilter[candidate_number - 1]:
                if candidate_number % chunk_size == 0:
                    yield SamplingProgress(
                        "OCCUPANCY",
                        candidate_number,
                        candidate_count,
                        f"GPU-prefiltering {source.name}",
                    )
                continue
            centre = Vector((
                lattice_coordinates[0][x_offset],
                lattice_coordinates[1][y_offset],
                lattice_coordinates[2][z_offset],
            ))
            bvh_query_count += 1
            nearest = bvh.find_nearest(centre, shell_distance)
            if nearest is not None and nearest[0] is not None and nearest[3] is not None:
                location, _normal, _polygon_index, distance = nearest
                if distance <= shell_distance:
                    if adaptive_enabled and not _nearest_surface_overlaps_adaptive_cell(
                        centre,
                        Vector((voxel_size, voxel_size, voxel_size)),
                        location,
                    ):
                        adaptive_rejected_seed_count += 1
                    else:
                        centres.append(centre)
                        if adaptive_enabled:
                            assert sampler is not None
                            analysis = sampler.analyse_nearest(location, analysis_cell_size)
                            colours.append(analysis.colour)
                            analyses.append(analysis)
                        elif not occupancy_only:
                            surface_locations.append(location.copy())
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
        if not adaptive_enabled and not occupancy_only and surface_locations:
            assert sampler is not None
            analyses, backend_diagnostics = sampler.analyse_nearest_batch(
                surface_locations,
                requested_backend=requested_backend,
                gpu_batch_size=gpu_batch_size,
                gpu_memory_limit_mb=gpu_memory_limit_mb,
            )
            colours = [analysis.colour for analysis in analyses]
    else:
        selected_indices: set[tuple[int, int, int]] = set()
        for candidate_number, (x_offset, y_offset, z_offset) in enumerate(
            candidate_offsets,
            start=1,
        ):
            if occupancy_prefilter is not None and not occupancy_prefilter[candidate_number - 1]:
                if candidate_number % chunk_size == 0:
                    yield SamplingProgress(
                        "OCCUPANCY",
                        candidate_number,
                        candidate_count,
                        f"GPU-prefiltering symmetric occupancy for {source.name}",
                    )
                continue
            centre = Vector((
                lattice_coordinates[0][x_offset],
                lattice_coordinates[1][y_offset],
                lattice_coordinates[2][z_offset],
            ))
            bvh_query_count += 1
            nearest = bvh.find_nearest(centre, shell_distance)
            if nearest is not None and nearest[0] is not None and nearest[3] is not None:
                if nearest[3] <= shell_distance:
                    if adaptive_enabled and not _nearest_surface_overlaps_adaptive_cell(
                        centre,
                        Vector((voxel_size, voxel_size, voxel_size)),
                        nearest[0],
                    ):
                        adaptive_rejected_seed_count += 1
                    else:
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
            centres.append(centre)
            if not occupancy_only:
                nearest = bvh.find_nearest(centre)
                if nearest is None or nearest[0] is None:
                    raise VoxelizerError(
                        "Could not independently colour-sample a symmetry orbit centre."
                    )
                if adaptive_enabled:
                    assert sampler is not None
                    analysis = sampler.analyse_nearest(nearest[0], analysis_cell_size)
                    colours.append(analysis.colour)
                    analyses.append(analysis)
                else:
                    surface_locations.append(nearest[0].copy())
            if colour_number % chunk_size == 0:
                yield SamplingProgress(
                    "COLOUR",
                    colour_number,
                    len(ordered_indices),
                    f"Sampling colours for {source.name}",
                )
        if not adaptive_enabled and not occupancy_only and surface_locations:
            assert sampler is not None
            analyses, backend_diagnostics = sampler.analyse_nearest_batch(
                surface_locations,
                requested_backend=requested_backend,
                gpu_batch_size=gpu_batch_size,
                gpu_memory_limit_mb=gpu_memory_limit_mb,
            )
            colours = [analysis.colour for analysis in analyses]
        orbit_added_count = max(0, len(centres) - occupied_seed_count)
    phase_timings["occupancy"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    if not centres:
        raise VoxelizerError("No surface voxels were produced; decrease Voxel Size.")
    if occupancy_only:
        fallback = tuple(float(value) for value in settings.fallback_color)
        colours = [fallback] * len(centres)
        analyses = [_ColourAnalysis(fallback, 0.0, 0.0)] * len(centres)
        backend_diagnostics = {
            "requested": requested_backend.upper(),
            "used": "NONE",
            "available": False,
            "reason": "Occupancy-only target fit skipped all texture reads",
        }
    base_count = len(centres)
    cells = [
        _VoxelCell(
            centre=centre,
            size=voxel_size,
            extent=Vector((voxel_size, voxel_size, voxel_size)),
            level=0,
            colour=colour,
            texture_error=analysis.texture_error,
            geometry_angle=analysis.geometry_angle,
            source_uv=analysis.source_uv,
        )
        for centre, colour, analysis in zip(centres, colours, analyses)
    ]
    adaptive_diagnostics = {
        "schema": ADAPTIVE_SCHEMA_VERSION,
        "enabled": False,
        "max_level": 0,
        "level_histogram": {"0": len(cells)},
        "levels": [],
        "budget_limited": False,
    }
    if adaptive_enabled:
        assert sampler is not None
        cells, adaptive_diagnostics = yield from _adaptive_refine_cells_iter(
            source,
            settings,
            bvh=bvh,
            sampler=sampler,
            source_symmetry=source_symmetry,
            cells=cells,
        )
    phase_timings["colour_and_adaptive"] = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    centres = [cell.centre for cell in cells]
    colours = [cell.colour for cell in cells]
    sizes = [cell.size for cell in cells]
    extents = [cell.extent for cell in cells]
    levels = [cell.level for cell in cells]
    source_uvs = [cell.source_uv for cell in cells]
    diagnostics = {
        "schema": SYMMETRY_SCHEMA_VERSION,
        "source_symmetry": source_symmetry,
        "sampling_symmetry": sampling_symmetry,
        "proven_axes": sorted(proven_axes),
        "helper_used": sampling_object is not source,
        "helper_rebuilt": bool(helper_rebuilt),
        "separate_parts_guard_used": bool(separate_parts_guard_used),
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
        "compute_backend": backend_diagnostics,
        "occupancy_backend": occupancy_diagnostics,
        "occupancy_auto_threshold": 50_000,
        "bvh_query_count": bvh_query_count,
        "cache_hit": False,
        "source_session_reused": session is not None,
        "source_session_timings": dict(session.timings) if session is not None else {},
        "occupancy_only": bool(occupancy_only),
        "occupied_seed_count": occupied_seed_count,
        "adaptive_rejected_seed_count": adaptive_rejected_seed_count,
        "orbit_added_count": orbit_added_count,
        "base_selected_count": base_count,
        "selected_count": len(centres),
        "adaptive": adaptive_diagnostics,
        "selection": (
            "ADAPTIVE_POWER_OF_TWO_SYMMETRY_CLOSURE"
            if adaptive_enabled and proven_axes
            else "ADAPTIVE_POWER_OF_TWO"
            if adaptive_enabled
            else "PROVEN_AXIS_INTEGER_ORBIT_CLOSURE"
            if proven_axes
            else "LEGACY_NO_CLOSURE"
        ),
    }
    phase_timings["finalize"] = time.perf_counter() - phase_started
    phase_timings["total"] = time.perf_counter() - phase_started_total
    diagnostics["phase_timings"] = phase_timings
    _LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()] = diagnostics
    yield SamplingProgress(
        "FINALIZE",
        len(centres),
        len(centres),
        f"Finalized {len(centres):,} voxels for {source.name}",
    )
    return VoxelSampleResult(
        centres=centres,
        colours=colours,
        sizes=sizes,
        extents=extents,
        levels=levels,
        used_image=bool(sampler is not None and sampler.uses_image),
        source_uvs=source_uvs,
    )


def _sampling_cache_key(source: bpy.types.Object, sampling_key: str) -> str:
    return f"{source.as_pointer()}:{sampling_key}"


def sample_surface_voxels_iter(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    cache_key: Optional[str] = None,
    use_cache: bool = True,
    session: Optional[SourceSamplingSession] = None,
    occupancy_only: bool = False,
    use_session_cache: bool = False,
) -> Iterator[SamplingProgress]:
    """Incrementally sample one source and return the result on completion.

    Consumers advance this generator between UI events.  The final voxel tuple is
    carried by ``StopIteration.value`` so the same implementation serves modal
    operators and the synchronous/background API.
    """

    validate_settings(settings)
    sampling_key = cache_key or (
        _session_sampling_key(session, settings)
        if session is not None
        else preview_sampling_key(context, source, settings)
    )
    cache_id = _sampling_cache_key(
        source,
        sampling_key + (":OCCUPANCY" if occupancy_only else ":FULL"),
    )
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
            sizes = [float(value) for value in entry.get(
                "sizes",
                [float(settings.voxel_size)] * len(centres),
            )]
            extents = [Vector(value) for value in entry.get(
                "extents",
                [(size, size, size) for size in sizes],
            )]
            levels = [int(value) for value in entry.get(
                "levels",
                [0] * len(centres),
            )]
            source_uvs = [tuple(value) for value in entry.get(
                "source_uvs",
                [(0.0, 0.0)] * len(centres),
            )]
            yield SamplingProgress(
                "CACHE",
                1,
                1,
                f"Reused {len(centres):,} cached voxels for {source.name}",
            )
            return VoxelSampleResult(
                centres=centres,
                colours=colours,
                sizes=sizes,
                extents=extents,
                levels=levels,
                used_image=bool(entry["used_image"]),
                source_uvs=source_uvs,
            )

    session_cache_hit = False
    session_prepare_seconds = 0.0
    if session is None and use_session_cache:
        session_started = time.perf_counter()
        session, session_cache_hit = acquire_sampling_session(
            context,
            source,
            settings,
        )
        session_prepare_seconds = time.perf_counter() - session_started
    if session is not None:
        result = yield from _sample_surface_voxels_from_meshes_iter(
            context,
            source,
            settings,
            source_mesh=session.source_mesh,
            source_symmetry=session.source_symmetry,
            sampling_object=session.sampling_object,
            helper_rebuilt=session.helper_rebuilt,
            sampling_mesh=session.sampling_mesh,
            separate_parts_guard_used=session.separate_parts_guard_used,
            session=session,
            occupancy_only=occupancy_only,
        )
    else:
        with evaluated_local_mesh(context, source) as source_mesh:
            source_diagnostics = mesh_readiness_diagnostics(source_mesh)
            source_symmetry = reflection_symmetry_diagnostics(source_mesh)
            source_component_count = int(source_diagnostics.get("components", 0))
            if (
                bool(getattr(settings, "preserve_disconnected_parts", True))
                and not _diagnostics_ready(source_diagnostics)
                and source_component_count <= 1
            ):
                source_component_count = mesh_component_count(
                    source_mesh,
                    stop_after=SEPARATE_PART_REPAIR_LIMIT + 1,
                )
            sampling_object, helper_rebuilt = ensure_sampling_object(
                context,
                source,
                settings,
                source_mesh=source_mesh,
                source_diagnostics=source_diagnostics,
                source_symmetry=source_symmetry,
                component_count=source_component_count,
            )
            separate_parts_guard_used = bool(
                sampling_object is source
                and bool(getattr(settings, "preserve_disconnected_parts", True))
                and not _diagnostics_ready(source_diagnostics)
                and source_component_count > 1
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
                    separate_parts_guard_used=separate_parts_guard_used,
                    occupancy_only=occupancy_only,
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
                        separate_parts_guard_used=separate_parts_guard_used,
                        occupancy_only=occupancy_only,
                    )

    if not isinstance(result, VoxelSampleResult):
        centres, colours, _count, used_image = result
        result = VoxelSampleResult(
            centres=centres,
            colours=colours,
            sizes=[float(settings.voxel_size)] * len(centres),
            extents=[Vector((float(settings.voxel_size),) * 3)] * len(centres),
            levels=[0] * len(centres),
            used_image=used_image,
            source_uvs=[(0.0, 0.0)] * len(centres),
        )
    diagnostics = dict(_LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()])
    diagnostics["cache_hit"] = False
    diagnostics["source_session_cache_hit"] = bool(session_cache_hit)
    diagnostics["source_session_acquire_seconds"] = session_prepare_seconds
    if use_cache:
        _cache_put(
            cache_id,
            result.centres,
            result.colours,
            result.sizes,
            result.extents,
            result.levels,
            result.source_uvs or [(0.0, 0.0)] * result.count,
            result.used_image,
            diagnostics,
            settings,
        )
    diagnostics["cache_entries"] = len(_SAMPLE_CACHE)
    diagnostics["cache_bytes"] = int(_SAMPLE_CACHE_BYTES)
    _LAST_SAMPLING_DIAGNOSTICS[source.as_pointer()] = diagnostics
    return result


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
    session: Optional[SourceSamplingSession] = None,
    occupancy_only: bool = False,
    use_session_cache: bool = False,
) -> VoxelSampleResult:
    """Synchronous sampling API used by scripts and background tests."""

    return _consume_progress_generator(
        sample_surface_voxels_iter(
            context,
            source,
            settings,
            cache_key=cache_key,
            use_cache=use_cache,
            session=session,
            occupancy_only=occupancy_only,
            use_session_cache=use_session_cache,
        ),
        progress_callback,
    )


def remove_enclosed_uniform_samples(
    sample_result: VoxelSampleResult,
) -> tuple[VoxelSampleResult, dict[str, object]]:
    """Remove six-neighbour interior cells from one uniform sample result.

    Adaptive Preview carriers use the exact record-aware implementation in
    ``meshing.remove_enclosed_records``. The direct legacy Bake path remains
    conservative and skips adaptive samples instead of deleting ambiguous cells.
    """

    count = sample_result.count
    stats = {
        "input_voxels": count,
        "output_voxels": count,
        "removed_voxels": 0,
        "exact": True,
        "skip_reason": "",
    }
    if count < 7:
        return sample_result, stats
    if (
        len(sample_result.sizes) != count
        or len(sample_result.extents) != count
        or len(sample_result.colours) != count
        or len(sample_result.levels) != count
        or (sample_result.source_uvs and len(sample_result.source_uvs) != count)
    ):
        stats.update(
            exact=False,
            skip_reason="sample attribute lengths do not match voxel count",
        )
        return sample_result, stats

    grid_size = float(sample_result.sizes[0])
    tolerance = max(1.0e-8, abs(grid_size) * 1.0e-5)
    uniform = grid_size > 0.0 and all(
        abs(float(size) - grid_size) <= tolerance
        and all(abs(float(extent[axis]) - grid_size) <= tolerance for axis in range(3))
        for size, extent in zip(sample_result.sizes, sample_result.extents)
    )
    if not uniform:
        stats.update(
            exact=False,
            skip_reason="direct adaptive Bake requires an Editable Preview for exact filtering",
        )
        return sample_result, stats

    reference = sample_result.centres[0]
    coordinates = [
        tuple(
            int(round((float(centre[axis]) - float(reference[axis])) / grid_size))
            for axis in range(3)
        )
        for centre in sample_result.centres
    ]
    occupancy = set(coordinates)
    directions = (
        (-1, 0, 0),
        (1, 0, 0),
        (0, -1, 0),
        (0, 1, 0),
        (0, 0, -1),
        (0, 0, 1),
    )
    keep_indices = [
        index
        for index, coordinate in enumerate(coordinates)
        if not all(
            tuple(coordinate[axis] + direction[axis] for axis in range(3)) in occupancy
            for direction in directions
        )
    ]
    removed = count - len(keep_indices)
    if removed == 0:
        return sample_result, stats

    source_uvs = sample_result.source_uvs
    filtered = VoxelSampleResult(
        centres=[sample_result.centres[index] for index in keep_indices],
        colours=[sample_result.colours[index] for index in keep_indices],
        sizes=[sample_result.sizes[index] for index in keep_indices],
        extents=[sample_result.extents[index] for index in keep_indices],
        levels=[sample_result.levels[index] for index in keep_indices],
        used_image=sample_result.used_image,
        source_uvs=(
            [source_uvs[index] for index in keep_indices]
            if source_uvs
            else []
        ),
    )
    stats.update(
        output_voxels=filtered.count,
        removed_voxels=removed,
    )
    return filtered, stats


def build_voxel_mesh_iter(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    mesh_name: str,
    *,
    cache_key: Optional[str] = None,
) -> Iterator[SamplingProgress]:
    """Incrementally build the realized cube mesh used by Bake."""

    sample_result = yield from sample_surface_voxels_iter(
        context,
        source,
        settings,
        cache_key=cache_key,
        use_session_cache=True,
    )
    if not isinstance(sample_result, VoxelSampleResult):
        centres, colours, _count, used_image = sample_result
        sample_result = VoxelSampleResult(
            centres=centres,
            colours=colours,
            sizes=[float(settings.voxel_size)] * len(centres),
            extents=[Vector((float(settings.voxel_size),) * 3)] * len(centres),
            levels=[0] * len(centres),
            used_image=used_image,
            source_uvs=[(0.0, 0.0)] * len(centres),
        )
    filter_stats = {
        "input_voxels": sample_result.count,
        "output_voxels": sample_result.count,
        "removed_voxels": 0,
        "exact": True,
        "skip_reason": "",
    }
    if bool(getattr(settings, "remove_enclosed_voxels", False)):
        sample_result, filter_stats = remove_enclosed_uniform_samples(sample_result)
    centres = sample_result.centres
    colours = sample_result.colours
    sizes = sample_result.sizes
    extents = sample_result.extents
    levels = sample_result.levels
    source_uvs = sample_result.source_uvs or [(0.0, 0.0)] * sample_result.count
    count = sample_result.count
    used_image = sample_result.used_image
    base_voxel_size = float(settings.voxel_size)
    fill_ratio = max(
        1.0e-6,
        min(1.0, 1.0 - float(settings.cube_gap) / base_voxel_size),
    )
    result_vertices = []
    result_faces = []
    chunk_size = sampling_chunk_size(settings)
    for voxel_number, (centre, cell_extent) in enumerate(
        zip(centres, extents),
        start=1,
    ):
        half_extent = Vector(cell_extent) * fill_ratio * 0.5
        first_vertex = len(result_vertices)
        result_vertices.extend(
            (
                centre.x + x_sign * half_extent.x,
                centre.y + y_sign * half_extent.y,
                centre.z + z_sign * half_extent.z,
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
        size_attribute = result.attributes.new(
            name=SIZE_ATTRIBUTE,
            type="FLOAT",
            domain="FACE",
        )
        extent_attribute = result.attributes.new(
            name=EXTENT_ATTRIBUTE,
            type="FLOAT_VECTOR",
            domain="FACE",
        )
        level_attribute = result.attributes.new(
            name=LEVEL_ATTRIBUTE,
            type="INT",
            domain="FACE",
        )
        source_uv_attribute = result.attributes.new(
            name="source_uv",
            type="FLOAT2",
            domain="FACE",
        )
        for polygon_number, polygon in enumerate(result.polygons, start=1):
            voxel_index = polygon.index // 6
            colour = colours[voxel_index]
            size_attribute.data[polygon.index].value = sizes[voxel_index]
            extent_attribute.data[polygon.index].vector = extents[voxel_index]
            level_attribute.data[polygon.index].value = levels[voxel_index]
            source_uv_attribute.data[polygon.index].vector = source_uvs[voxel_index]
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
        # Delayed import avoids the core <-> meshing module import cycle.
        from . import meshing

        meshing.tag_filter_stats(result, filter_stats)
        result.update()
        completed = True
    finally:
        if not completed and result.name in bpy.data.meshes:
            bpy.data.meshes.remove(result)
    return result, count, used_image


def build_voxel_mesh_from_sample_iter(
    source: bpy.types.Object,
    settings,
    mesh_name: str,
    sample_result: VoxelSampleResult,
) -> Iterator[SamplingProgress]:
    """Build final geometry from a sample produced by target-count fitting."""

    from . import editable, meshing, preview

    temporary_mesh = bpy.data.meshes.new(f".{mesh_name}_TargetCarrierMesh")
    temporary = bpy.data.objects.new(f".{mesh_name}_TargetCarrier", temporary_mesh)
    temporary_linked = False
    completed = False
    try:
        preview.configure_preview(
            temporary,
            sample_result.centres,
            sample_result.colours,
            sample_result.sizes,
            sample_result.extents,
            sample_result.levels,
            preview.display_cube_fill(settings),
            ensure_colour_material(),
        )
        source_collection = source.users_collection[0] if source.users_collection else bpy.context.collection
        source_collection.objects.link(temporary)
        temporary_linked = True
        editable.initialize_carrier(
            temporary,
            reset_delta=True,
            coordinate_ordered=True,
        )
        source_uvs = sample_result.source_uvs or [(0.0, 0.0)] * sample_result.count
        source_uv_attribute = temporary.data.attributes.get(editable.SOURCE_UV_ATTRIBUTE)
        if source_uv_attribute is not None:
            source_uv_attribute.data.foreach_set(
                "vector",
                array("f", (component for uv in source_uvs for component in uv)),
            )
        yield SamplingProgress(
            "BAKE_GEOMETRY",
            0,
            1,
            f"Building fitted {str(settings.bake_mode).lower()} geometry for {source.name}",
        )
        mode = str(settings.bake_mode)
        if mode == "EDITABLE":
            records = editable.records_from_object(temporary)
            filter_stats = {
                "input_voxels": len(records),
                "output_voxels": len(records),
                "removed_voxels": 0,
                "exact": True,
                "skip_reason": "",
            }
            if bool(getattr(settings, "remove_enclosed_voxels", False)):
                records, filter_stats = meshing.remove_enclosed_records(
                    records,
                    float(temporary[editable.GRID_SIZE_TAG]),
                    tuple(temporary[editable.GRID_ORIGIN_TAG]),
                )
                editable.replace_records(temporary, records)
            meshing.tag_filter_stats(temporary.data, filter_stats)
            mesh = temporary.data.copy()
            mesh.name = mesh_name
            count = len(records)
        else:
            mesh, count = meshing.build_from_editable(
                temporary,
                mode,
                mesh_name,
                fill_ratio=preview.display_cube_fill(settings),
                remove_enclosed=bool(getattr(settings, "remove_enclosed_voxels", False)),
            )
        completed = True
        return mesh, count, bool(sample_result.used_image)
    finally:
        data = temporary.data
        if data is not None:
            temporary.data = None
            if data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.objects.remove(temporary, do_unlink=temporary_linked)
        if not completed:
            failed = bpy.data.meshes.get(mesh_name)
            if failed is not None and failed.users == 0:
                bpy.data.meshes.remove(failed)


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
