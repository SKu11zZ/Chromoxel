"""Optional GPU compute backends for Chromoxel.

The Blender ``gpu`` module needs an interactive graphics context.  Background
and unsupported sessions therefore resolve to the CPU without making Preview
or CLI workflows fail.  Texture reads and uniform surface occupancy both use
bounded batches.  Uniform occupancy uploads the source triangles once, builds
a coarse lattice-brick index on the CPU, and lets each candidate inspect only
the triangles that overlap its local brick.  It never performs an all-pairs
candidate/triangle dispatch.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict
from dataclasses import dataclass
import math
import time
from typing import Iterable, Sequence

import bpy


LOCAL_SIZE_X = 16
LOCAL_SIZE_Y = 16
MAX_ROW_WIDTH = 4096
_SHADER = None
_OCCUPANCY_SHADER = None
_SOURCE_TEXTURE_CACHE = OrderedDict()
_SOURCE_TEXTURE_CACHE_BYTES = 0
OCCUPANCY_BRICK_EDGE = 4
MAX_EXACT_FLOAT_INDEX = (1 << 24) - 1


@dataclass(frozen=True)
class BackendDecision:
    requested: str
    used: str
    available: bool
    reason: str
    backend: str = ""
    device: str = ""


@dataclass
class UniformOccupancyResource:
    """One source triangle upload reused by a :class:`SourceSamplingSession`."""

    triangle_texture: object
    triangle_vertex_width: int
    triangle_count: int
    triangle_bounds: object
    gpu_bytes: int


def _normalise_backend(value: str) -> str:
    value = str(value or "AUTO").upper()
    return value if value in {"AUTO", "GPU", "CPU"} else "AUTO"


def capability() -> BackendDecision:
    """Probe Blender's current graphics context without raising."""

    try:
        import gpu

        backend = str(gpu.platform.backend_type_get())
        device = str(gpu.platform.device_type_get())
        available = bool(
            hasattr(gpu, "compute")
            and hasattr(gpu.compute, "dispatch")
            and hasattr(gpu.types, "GPUTexture")
            and backend not in {"", "NONE", "UNKNOWN"}
        )
        return BackendDecision(
            requested="GPU",
            used="GPU" if available else "CPU",
            available=available,
            reason="GPU compute context available" if available else "GPU compute API unavailable",
            backend=backend,
            device=device,
        )
    except Exception as exc:
        return BackendDecision(
            requested="GPU",
            used="CPU",
            available=False,
            reason=f"No interactive GPU context: {type(exc).__name__}",
        )


def resolve_backend(requested: str) -> BackendDecision:
    requested = _normalise_backend(requested)
    if requested == "CPU":
        return BackendDecision(
            requested=requested,
            used="CPU",
            available=True,
            reason="CPU explicitly selected",
        )
    detected = capability()
    if detected.available:
        return BackendDecision(
            requested=requested,
            used="GPU",
            available=True,
            reason=detected.reason,
            backend=detected.backend,
            device=detected.device,
        )
    return BackendDecision(
        requested=requested,
        used="CPU",
        available=False,
        reason=detected.reason,
        backend=detected.backend,
        device=detected.device,
    )


def _ensure_shader():
    global _SHADER
    if _SHADER is not None:
        return _SHADER

    import gpu

    info = gpu.types.GPUShaderCreateInfo()
    info.local_group_size(LOCAL_SIZE_X, LOCAL_SIZE_Y, 1)
    info.image(0, "RG32F", "FLOAT_2D", "uv_input", qualifiers={"READ", "NO_RESTRICT"})
    info.image(1, "RGBA32F", "FLOAT_2D", "colour_output", qualifiers={"WRITE", "NO_RESTRICT"})
    info.image(2, "RGBA32F", "FLOAT_2D", "source_image", qualifiers={"READ", "NO_RESTRICT"})
    info.push_constant("INT", "sample_count")
    info.push_constant("INT", "row_width")
    info.push_constant("INT", "source_width")
    info.push_constant("INT", "source_height")
    info.push_constant("INT", "extension_mode")
    info.push_constant("INT", "filter_mode")
    info.compute_source(
        """
        ivec2 chromoxel_wrap(ivec2 pixel, ivec2 size)
        {
          if (extension_mode == 0) {
            return ivec2(
              ((pixel.x % size.x) + size.x) % size.x,
              ((pixel.y % size.y) + size.y) % size.y
            );
          }
          return clamp(pixel, ivec2(0), size - ivec2(1));
        }

        float chromoxel_srgb_to_linear(float value)
        {
          return value <= 0.04045
            ? value / 12.92
            : pow((value + 0.055) / 1.055, 2.4);
        }

        vec4 chromoxel_load(ivec2 pixel)
        {
          ivec2 size = ivec2(int(source_width), int(source_height));
          if (extension_mode == 2 && any(notEqual(pixel, clamp(pixel, ivec2(0), size - ivec2(1))))) {
            return vec4(0.0);
          }
          vec4 colour = imageLoad(source_image, chromoxel_wrap(pixel, size));
          colour.rgb = vec3(
            chromoxel_srgb_to_linear(colour.r),
            chromoxel_srgb_to_linear(colour.g),
            chromoxel_srgb_to_linear(colour.b)
          );
          return colour;
        }

        vec4 chromoxel_sample(vec2 uv)
        {
          vec2 size = vec2(float(source_width), float(source_height));
          if (filter_mode == 0) {
            return chromoxel_load(ivec2(floor(uv * size)));
          }
          vec2 coordinate = uv * size - vec2(0.5);
          ivec2 first = ivec2(floor(coordinate));
          vec2 blend = fract(coordinate);
          vec4 a = chromoxel_load(first);
          vec4 b = chromoxel_load(first + ivec2(1, 0));
          vec4 c = chromoxel_load(first + ivec2(0, 1));
          vec4 d = chromoxel_load(first + ivec2(1, 1));
          return mix(mix(a, b, blend.x), mix(c, d, blend.x), blend.y);
        }

        void main()
        {
          ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
          ivec2 extent = imageSize(uv_input);
          if (pixel.x >= extent.x || pixel.y >= extent.y) {
            return;
          }
          int index = pixel.y * row_width + pixel.x;
          if (index >= sample_count) {
            return;
          }
          vec2 uv = imageLoad(uv_input, pixel).xy;
          vec4 colour = chromoxel_sample(uv);
          imageStore(colour_output, pixel, colour);
        }
        """
    )
    _SHADER = gpu.shader.create_from_info(info)
    return _SHADER


def _ensure_occupancy_shader():
    """Compile the uniform point-to-triangle occupancy kernel lazily."""

    global _OCCUPANCY_SHADER
    if _OCCUPANCY_SHADER is not None:
        return _OCCUPANCY_SHADER

    import gpu

    info = gpu.types.GPUShaderCreateInfo()
    info.local_group_size(LOCAL_SIZE_X, LOCAL_SIZE_Y, 1)
    info.image(0, "RGBA32F", "FLOAT_2D", "candidate_positions", qualifiers={"READ", "NO_RESTRICT"})
    # Blender 5.1's Python GPUTexture constructor accepts FLOAT buffers only,
    # even when an integer texture format is requested.  Indices are therefore
    # stored in R/RG/RGBA32F and bounded below the exact IEEE-754 integer range.
    info.image(1, "RGBA32F", "FLOAT_2D", "candidate_cells", qualifiers={"READ", "NO_RESTRICT"})
    info.image(2, "RG32F", "FLOAT_2D", "brick_ranges", qualifiers={"READ", "NO_RESTRICT"})
    info.image(3, "R32F", "FLOAT_2D", "brick_triangles", qualifiers={"READ", "NO_RESTRICT"})
    info.image(4, "RGBA32F", "FLOAT_2D", "triangle_vertices", qualifiers={"READ", "NO_RESTRICT"})
    info.image(5, "R32F", "FLOAT_2D", "occupancy_output", qualifiers={"WRITE", "NO_RESTRICT"})
    info.push_constant("INT", "sample_count")
    info.push_constant("INT", "row_width")
    info.push_constant("INT", "brick_range_width")
    info.push_constant("INT", "brick_triangle_width")
    info.push_constant("INT", "triangle_vertex_width")
    info.push_constant("INT", "brick_dim_x")
    info.push_constant("INT", "brick_dim_y")
    info.push_constant("INT", "brick_edge")
    info.push_constant("FLOAT", "shell_distance_squared")
    info.compute_source(
        """
        ivec2 chromoxel_linear_pixel(int index, int width)
        {
          return ivec2(index % width, index / width);
        }

        vec3 chromoxel_triangle_vertex(int index)
        {
          return imageLoad(
            triangle_vertices,
            chromoxel_linear_pixel(index, triangle_vertex_width)
          ).xyz;
        }

        float chromoxel_segment_distance_squared(vec3 p, vec3 a, vec3 b)
        {
          vec3 ab = b - a;
          float denominator = dot(ab, ab);
          if (denominator <= 1.0e-30) {
            vec3 delta = p - a;
            return dot(delta, delta);
          }
          float t = clamp(dot(p - a, ab) / denominator, 0.0, 1.0);
          vec3 delta = p - (a + t * ab);
          return dot(delta, delta);
        }

        float chromoxel_triangle_distance_squared(vec3 p, vec3 a, vec3 b, vec3 c)
        {
          vec3 ab = b - a;
          vec3 ac = c - a;
          vec3 ap = p - a;
          float d1 = dot(ab, ap);
          float d2 = dot(ac, ap);
          if (d1 <= 0.0 && d2 <= 0.0) return dot(ap, ap);

          vec3 bp = p - b;
          float d3 = dot(ab, bp);
          float d4 = dot(ac, bp);
          if (d3 >= 0.0 && d4 <= d3) return dot(bp, bp);

          float vc = d1 * d4 - d3 * d2;
          if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) {
            float v = d1 / max(d1 - d3, 1.0e-30);
            vec3 delta = p - (a + v * ab);
            return dot(delta, delta);
          }

          vec3 cp = p - c;
          float d5 = dot(ab, cp);
          float d6 = dot(ac, cp);
          if (d6 >= 0.0 && d5 <= d6) return dot(cp, cp);

          float vb = d5 * d2 - d1 * d6;
          if (vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0) {
            float w = d2 / max(d2 - d6, 1.0e-30);
            vec3 delta = p - (a + w * ac);
            return dot(delta, delta);
          }

          float va = d3 * d6 - d5 * d4;
          if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0) {
            vec3 bc = c - b;
            float w = (d4 - d3) / max((d4 - d3) + (d5 - d6), 1.0e-30);
            vec3 delta = p - (b + w * bc);
            return dot(delta, delta);
          }

          float denominator = va + vb + vc;
          if (abs(denominator) <= 1.0e-30) {
            return min(
              chromoxel_segment_distance_squared(p, a, b),
              min(
                chromoxel_segment_distance_squared(p, b, c),
                chromoxel_segment_distance_squared(p, c, a)
              )
            );
          }
          float inverse = 1.0 / denominator;
          float v = vb * inverse;
          float w = vc * inverse;
          vec3 delta = p - (a + ab * v + ac * w);
          return dot(delta, delta);
        }

        float chromoxel_triangle_lower_bound_squared(vec3 p, vec3 a, vec3 b, vec3 c)
        {
          // AABB distance is a stable lower bound on distance to the finite
          // triangle.  The shader intentionally avoids plane-distance math:
          // degenerate and very small source triangles can amplify float32
          // normal error at 100K resolutions. CPU BVH confirms all positives.
          vec3 bounds_minimum = min(a, min(b, c));
          vec3 bounds_maximum = max(a, max(b, c));
          vec3 outside = max(max(bounds_minimum - p, vec3(0.0)), p - bounds_maximum);
          float bounds_distance = dot(outside, outside);

          return bounds_distance;
        }

        void main()
        {
          ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
          ivec2 extent = imageSize(candidate_positions);
          if (pixel.x >= extent.x || pixel.y >= extent.y) return;
          int index = pixel.y * row_width + pixel.x;
          if (index >= sample_count) return;

          vec3 point = imageLoad(candidate_positions, pixel).xyz;
          ivec3 cell = ivec3(round(imageLoad(candidate_cells, pixel).xyz));
          ivec3 brick = cell / max(brick_edge, 1);
          int brick_index = (brick.z * brick_dim_y + brick.y) * brick_dim_x + brick.x;
          vec2 range_value = imageLoad(
            brick_ranges,
            chromoxel_linear_pixel(brick_index, brick_range_width)
          ).xy;
          uvec2 range = uvec2(round(range_value));

          uint occupied = 0u;
          float threshold = shell_distance_squared * 1.000002 + 1.0e-20;
          for (uint offset = 0u; offset < range.y; ++offset) {
            uint triangle_index = uint(round(imageLoad(
              brick_triangles,
              chromoxel_linear_pixel(int(range.x + offset), brick_triangle_width)
            ).x));
            int vertex_offset = int(triangle_index) * 3;
            vec3 a = chromoxel_triangle_vertex(vertex_offset);
            vec3 b = chromoxel_triangle_vertex(vertex_offset + 1);
            vec3 c = chromoxel_triangle_vertex(vertex_offset + 2);
            if (chromoxel_triangle_lower_bound_squared(point, a, b, c) <= threshold) {
              occupied = 1u;
              break;
            }
          }
          imageStore(occupancy_output, pixel, vec4(float(occupied), 0.0, 0.0, 0.0));
        }
        """
    )
    _OCCUPANCY_SHADER = gpu.shader.create_from_info(info)
    return _OCCUPANCY_SHADER


def _flatten(values):
    if isinstance(values, (list, tuple)):
        for value in values:
            yield from _flatten(value)
    else:
        yield float(values)


def _texture_extent(item_count: int) -> tuple[int, int, int]:
    item_count = max(1, int(item_count))
    width = min(MAX_ROW_WIDTH, item_count)
    height = int(math.ceil(item_count / width))
    return width, height, width * height


def _prepare_uniform_occupancy_resource(
    mesh: bpy.types.Mesh,
    *,
    memory_limit_bytes: int,
) -> UniformOccupancyResource:
    """Upload immutable triangle positions and retain vectorized AABBs."""

    import gpu
    import numpy as np

    mesh.calc_loop_triangles()
    triangle_count = len(mesh.loop_triangles)
    if triangle_count <= 0:
        raise ValueError("Sampling mesh has no loop triangles")
    texture_bytes = triangle_count * 3 * 16
    if texture_bytes + (8 * 1024 * 1024) > memory_limit_bytes:
        raise MemoryError(
            f"triangle upload needs at least {texture_bytes / (1024 * 1024):.1f} MiB, "
            f"limit is {memory_limit_bytes / (1024 * 1024):.1f} MiB"
        )

    coordinates = array("f", [0.0]) * (len(mesh.vertices) * 3)
    triangle_indices = array("i", [0]) * (triangle_count * 3)
    mesh.vertices.foreach_get("co", coordinates)
    mesh.loop_triangles.foreach_get("vertices", triangle_indices)
    coordinate_view = np.frombuffer(coordinates, dtype=np.float32).reshape((-1, 3))
    index_view = np.frombuffer(triangle_indices, dtype=np.int32).reshape((-1, 3))
    triangles = coordinate_view[index_view]
    minimums = triangles.min(axis=1)
    maximums = triangles.max(axis=1)
    bounds = np.concatenate((minimums, maximums), axis=1).astype(np.float32, copy=False)

    vertex_count = triangle_count * 3
    width, height, padded = _texture_extent(vertex_count)
    packed = np.zeros((padded, 4), dtype=np.float32)
    packed[:vertex_count, :3] = triangles.reshape((-1, 3))
    buffer = gpu.types.Buffer("FLOAT", (height, width, 4), array("f", packed.ravel()))
    texture = gpu.types.GPUTexture(
        size=(width, height),
        format="RGBA32F",
        data=buffer,
    )
    return UniformOccupancyResource(
        triangle_texture=texture,
        triangle_vertex_width=width,
        triangle_count=triangle_count,
        triangle_bounds=bounds,
        gpu_bytes=padded * 16,
    )


def _uniform_brick_textures(
    resource: UniformOccupancyResource,
    lattice_coordinates: Sequence[Sequence[float]],
    shell_distance: float,
    *,
    memory_limit_bytes: int,
):
    """Build a dense brick range table with compact triangle references."""

    import gpu
    import numpy as np

    edge = OCCUPANCY_BRICK_EDGE
    counts = tuple(len(axis) for axis in lattice_coordinates)
    brick_dimensions = tuple(max(1, int(math.ceil(count / edge))) for count in counts)
    brick_count = brick_dimensions[0] * brick_dimensions[1] * brick_dimensions[2]
    bounds = resource.triangle_bounds
    coordinate_scale = max(
        1.0,
        *(abs(float(axis[0])) for axis in lattice_coordinates if axis),
        *(abs(float(axis[-1])) for axis in lattice_coordinates if axis),
    )
    # This is a conservative prefilter, not the final occupancy decision.
    # Expand both the brick index and shader threshold enough to absorb float32
    # texture conversion and backend-specific point/triangle rounding.  Every
    # positive is still confirmed by Blender's CPU BVH at the exact threshold.
    prefilter_distance = float(shell_distance) * 1.06 + coordinate_scale * 1.0e-6
    lower = []
    upper = []
    for axis in range(3):
        coordinates = np.asarray(lattice_coordinates[axis], dtype=np.float32)
        lower.append(np.searchsorted(coordinates, bounds[:, axis] - prefilter_distance, side="left"))
        upper.append(np.searchsorted(coordinates, bounds[:, axis + 3] + prefilter_distance, side="right") - 1)
    lower_view = np.stack(lower, axis=1)
    upper_view = np.stack(upper, axis=1)
    lower_view = np.clip(lower_view, 0, np.asarray(counts) - 1) // edge
    upper_view = np.clip(upper_view, 0, np.asarray(counts) - 1) // edge

    spans = upper_view - lower_view + 1
    references_per_triangle = np.prod(spans, axis=1, dtype=np.int64)
    reference_count = int(references_per_triangle.sum(dtype=np.int64))
    if max(brick_count, reference_count, resource.triangle_count) > MAX_EXACT_FLOAT_INDEX:
        raise MemoryError(
            "occupancy index exceeds Blender 5.1's exact float-index limit; CPU fallback"
        )
    range_bytes = brick_count * 8
    reference_bytes = max(1, reference_count) * 4
    required = resource.gpu_bytes + range_bytes + reference_bytes
    if required + (8 * 1024 * 1024) > memory_limit_bytes:
        raise MemoryError(
            f"occupancy index needs at least {required / (1024 * 1024):.1f} MiB, "
            f"limit is {memory_limit_bytes / (1024 * 1024):.1f} MiB"
        )

    if reference_count:
        triangle_owners = np.repeat(
            np.arange(resource.triangle_count, dtype=np.int32),
            references_per_triangle,
        )
        starts = np.empty(resource.triangle_count, dtype=np.int64)
        starts[0] = 0
        if resource.triangle_count > 1:
            np.cumsum(references_per_triangle[:-1], out=starts[1:])
        local_reference = (
            np.arange(reference_count, dtype=np.int64)
            - np.repeat(starts, references_per_triangle)
        )
        owner_spans = spans[triangle_owners]
        x_offset = local_reference % owner_spans[:, 0]
        yz_offset = local_reference // owner_spans[:, 0]
        y_offset = yz_offset % owner_spans[:, 1]
        z_offset = yz_offset // owner_spans[:, 1]
        owner_lower = lower_view[triangle_owners]
        x_bricks, y_bricks, _z_bricks = brick_dimensions
        brick_indices = (
            ((owner_lower[:, 2] + z_offset) * y_bricks + owner_lower[:, 1] + y_offset)
            * x_bricks
            + owner_lower[:, 0]
            + x_offset
        ).astype(np.int32, copy=False)
        ordering = np.argsort(brick_indices, kind="stable")
        sorted_bricks = brick_indices[ordering]
        sorted_triangles = triangle_owners[ordering]
        counts_by_brick = np.bincount(sorted_bricks, minlength=brick_count).astype(
            np.int64,
            copy=False,
        )
        starts_by_brick = np.zeros(brick_count, dtype=np.int64)
        if brick_count > 1:
            np.cumsum(counts_by_brick[:-1], out=starts_by_brick[1:])
        range_values = np.empty((brick_count, 2), dtype=np.float32)
        range_values[:, 0] = starts_by_brick
        range_values[:, 1] = counts_by_brick
        reference_values = sorted_triangles.astype(np.float32, copy=False)
    else:
        range_values = np.zeros((brick_count, 2), dtype=np.float32)
        reference_values = np.zeros(1, dtype=np.float32)

    ranges = array("f", range_values.ravel())
    references = array("f", reference_values)

    range_width, range_height, range_padded = _texture_extent(brick_count)
    if range_padded > brick_count:
        ranges.extend([0.0] * ((range_padded - brick_count) * 2))
    range_buffer = gpu.types.Buffer("FLOAT", (range_height, range_width, 2), ranges)
    range_texture = gpu.types.GPUTexture(
        size=(range_width, range_height),
        format="RG32F",
        data=range_buffer,
    )

    reference_width, reference_height, reference_padded = _texture_extent(len(references))
    if reference_padded > len(references):
        references.extend([0.0] * (reference_padded - len(references)))
    reference_buffer = gpu.types.Buffer(
        "FLOAT",
        (reference_height, reference_width),
        references,
    )
    reference_texture = gpu.types.GPUTexture(
        size=(reference_width, reference_height),
        format="R32F",
        data=reference_buffer,
    )
    return (
        range_texture,
        reference_texture,
        brick_dimensions,
        range_width,
        reference_width,
        {
            "brick_edge": edge,
            "prefilter_distance": prefilter_distance,
            "brick_dimensions": list(brick_dimensions),
            "brick_count": brick_count,
            "triangle_references": reference_count,
            "index_gpu_bytes": range_padded * 8 + reference_padded * 4,
        },
    )


def sample_uniform_occupancy(
    mesh: bpy.types.Mesh,
    candidate_offsets: Sequence[Sequence[int]],
    lattice_coordinates: Sequence[Sequence[float]],
    shell_distance: float,
    *,
    requested: str = "AUTO",
    batch_size: int = 65_536,
    memory_limit_mb: int = 512,
    resource: UniformOccupancyResource | None = None,
    index_resource: object | None = None,
) -> tuple[
    list[bool] | None,
    BackendDecision,
    dict[str, object],
    UniformOccupancyResource | None,
    object | None,
]:
    """GPU-prefilter Uniform candidates for exact CPU/BVH confirmation.

    The shader uses a deliberately expanded distance threshold.  Callers must
    confirm every returned positive with the CPU BVH; this preserves exact
    CPU output while eliminating BVH calls for the much larger negative set.
    """

    decision = resolve_backend(requested)
    if decision.used != "GPU":
        return None, decision, {"used": False, "reason": decision.reason}, resource, index_resource
    started = time.perf_counter()
    memory_limit_bytes = max(64, int(memory_limit_mb)) * 1024 * 1024
    try:
        import gpu

        if resource is None:
            resource = _prepare_uniform_occupancy_resource(
                mesh,
                memory_limit_bytes=memory_limit_bytes,
            )
        index_reused = index_resource is not None
        if index_resource is None:
            index_resource = _uniform_brick_textures(
                resource,
                lattice_coordinates,
                float(shell_distance),
                memory_limit_bytes=memory_limit_bytes,
            )
        (
            brick_ranges,
            brick_triangles,
            brick_dimensions,
            brick_range_width,
            brick_triangle_width,
            brick_report,
        ) = index_resource
        fixed_bytes = resource.gpu_bytes + int(brick_report["index_gpu_bytes"])
        available_batch_bytes = memory_limit_bytes - fixed_bytes
        if available_batch_bytes < 40 * 1024:
            raise MemoryError("GPU memory limit leaves no bounded occupancy batch")
        max_safe_batch = max(1024, available_batch_bytes // 40)
        batch_size = max(1024, min(1_000_000, int(batch_size), max_safe_batch))
        shader = _ensure_occupancy_shader()
        flags: list[bool] = []
        for first in range(0, len(candidate_offsets), batch_size):
            batch = candidate_offsets[first:first + batch_size]
            width, height, padded = _texture_extent(len(batch))
            positions = array("f", [0.0]) * (padded * 4)
            cells = array("f", [0.0]) * (padded * 4)
            for index, offset in enumerate(batch):
                base = index * 4
                x, y, z = (int(value) for value in offset)
                positions[base] = float(lattice_coordinates[0][x])
                positions[base + 1] = float(lattice_coordinates[1][y])
                positions[base + 2] = float(lattice_coordinates[2][z])
                positions[base + 3] = 1.0
                cells[base] = float(x)
                cells[base + 1] = float(y)
                cells[base + 2] = float(z)
            position_texture = gpu.types.GPUTexture(
                size=(width, height),
                format="RGBA32F",
                data=gpu.types.Buffer("FLOAT", (height, width, 4), positions),
            )
            cell_texture = gpu.types.GPUTexture(
                size=(width, height),
                format="RGBA32F",
                data=gpu.types.Buffer("FLOAT", (height, width, 4), cells),
            )
            output_texture = gpu.types.GPUTexture(size=(width, height), format="R32F")
            shader.bind()
            shader.image("candidate_positions", position_texture)
            shader.image("candidate_cells", cell_texture)
            shader.image("brick_ranges", brick_ranges)
            shader.image("brick_triangles", brick_triangles)
            shader.image("triangle_vertices", resource.triangle_texture)
            shader.image("occupancy_output", output_texture)
            shader.uniform_int("sample_count", len(batch))
            shader.uniform_int("row_width", width)
            shader.uniform_int("brick_range_width", brick_range_width)
            shader.uniform_int("brick_triangle_width", brick_triangle_width)
            shader.uniform_int("triangle_vertex_width", resource.triangle_vertex_width)
            shader.uniform_int("brick_dim_x", brick_dimensions[0])
            shader.uniform_int("brick_dim_y", brick_dimensions[1])
            shader.uniform_int("brick_edge", OCCUPANCY_BRICK_EDGE)
            # The GPU pass is a conservative prefilter. Exact shell membership
            # is confirmed by Blender's CPU BVH for every positive candidate.
            prefilter_distance = float(brick_report["prefilter_distance"])
            shader.uniform_float("shell_distance_squared", prefilter_distance ** 2)
            gpu.compute.dispatch(
                shader,
                int(math.ceil(width / LOCAL_SIZE_X)),
                int(math.ceil(height / LOCAL_SIZE_Y)),
                1,
            )
            flat = list(_flatten(output_texture.read().to_list()))
            flags.extend(bool(int(value)) for value in flat[:len(batch)])
        positives = sum(flags)
        report = {
            "used": True,
            "mode": "GPU_CONSERVATIVE_AABB_CPU_EXACT",
            "candidates": len(candidate_offsets),
            "gpu_positive_candidates": positives,
            "rejected_candidates": len(candidate_offsets) - positives,
            "triangle_count": resource.triangle_count,
            "triangle_gpu_bytes": resource.gpu_bytes,
            "batch_size": batch_size,
            "memory_limit_mb": int(memory_limit_mb),
            "index_reused": index_reused,
            "seconds": time.perf_counter() - started,
            **brick_report,
        }
        return flags, decision, report, resource, index_resource
    except Exception as exc:
        fallback = BackendDecision(
            requested=decision.requested,
            used="CPU",
            available=False,
            reason=f"GPU occupancy failed; CPU fallback: {type(exc).__name__}: {exc}",
            backend=decision.backend,
            device=decision.device,
        )
        return None, fallback, {
            "used": False,
            "reason": fallback.reason,
            "seconds": time.perf_counter() - started,
        }, resource, index_resource


def _source_texture_from_image(
    image: bpy.types.Image,
    *,
    pixels: Sequence[float] | None,
    memory_limit_bytes: int,
):
    """Create a sampleable float texture without relying on viewport upload state."""

    import gpu

    global _SOURCE_TEXTURE_CACHE_BYTES

    width, height = (int(image.size[0]), int(image.size[1]))
    estimated_bytes = width * height * 16
    if estimated_bytes > memory_limit_bytes:
        raise MemoryError(
            f"source texture needs {estimated_bytes / (1024 * 1024):.1f} MiB, "
            f"limit is {memory_limit_bytes / (1024 * 1024):.1f} MiB"
        )
    key = (
        int(image.as_pointer()),
        width,
        height,
        int(getattr(image, "channels", 4) or 4),
        bool(getattr(image, "is_updated", False)),
        bool(getattr(image, "is_updated_data", False)),
    )
    cached = _SOURCE_TEXTURE_CACHE.get(key)
    if cached is not None:
        _SOURCE_TEXTURE_CACHE.move_to_end(key)
        return cached[0]

    values = array("f", pixels) if pixels is not None else array("f", [0.0]) * (width * height * 4)
    if pixels is None:
        image.pixels.foreach_get(values)
    if len(values) < width * height * 4:
        raise ValueError("Image pixel buffer is smaller than its RGBA dimensions")
    source_buffer = gpu.types.Buffer("FLOAT", (height, width, 4), values)
    texture = gpu.types.GPUTexture(
        size=(width, height),
        format="RGBA32F",
        data=source_buffer,
    )
    # Keep one generation per datablock; Blender's GPU objects are context-bound.
    pointer = int(image.as_pointer())
    for stale_key in [value for value in _SOURCE_TEXTURE_CACHE if value[0] == pointer]:
        stale = _SOURCE_TEXTURE_CACHE.pop(stale_key, None)
        if stale is not None:
            _SOURCE_TEXTURE_CACHE_BYTES -= int(stale[1])
    while _SOURCE_TEXTURE_CACHE and _SOURCE_TEXTURE_CACHE_BYTES + estimated_bytes > memory_limit_bytes:
        _old_key, (_old_texture, old_bytes) = _SOURCE_TEXTURE_CACHE.popitem(last=False)
        _SOURCE_TEXTURE_CACHE_BYTES -= int(old_bytes)
    _SOURCE_TEXTURE_CACHE[key] = (texture, estimated_bytes)
    _SOURCE_TEXTURE_CACHE_BYTES += estimated_bytes
    return texture


def _sample_chunk(
    image: bpy.types.Image,
    uvs: Sequence[tuple[float, float]],
    *,
    extension: str,
    filter_mode: str,
    source_pixels: Sequence[float] | None,
    memory_limit_bytes: int,
) -> list[tuple[float, float, float, float]]:
    import gpu

    count = len(uvs)
    if count == 0:
        return []
    width = min(MAX_ROW_WIDTH, count)
    height = int(math.ceil(count / width))
    padded = width * height
    uv_values = [0.0] * (padded * 2)
    for index, (u, v) in enumerate(uvs):
        offset = index * 2
        uv_values[offset] = float(u)
        uv_values[offset + 1] = float(v)

    uv_buffer = gpu.types.Buffer("FLOAT", (height, width, 2), array("f", uv_values))
    uv_texture = gpu.types.GPUTexture(
        size=(width, height),
        format="RG32F",
        data=uv_buffer,
    )
    colour_texture = gpu.types.GPUTexture(
        size=(width, height),
        format="RGBA32F",
    )
    source_texture = _source_texture_from_image(
        image,
        pixels=source_pixels,
        memory_limit_bytes=memory_limit_bytes - padded * 24,
    )
    shader = _ensure_shader()
    shader.bind()
    shader.image("uv_input", uv_texture)
    shader.image("colour_output", colour_texture)
    shader.image("source_image", source_texture)
    shader.uniform_int("sample_count", count)
    shader.uniform_int("row_width", width)
    shader.uniform_int("source_width", int(image.size[0]))
    shader.uniform_int("source_height", int(image.size[1]))
    shader.uniform_int(
        "extension_mode",
        {"REPEAT": 0, "EXTEND": 1, "CLIP": 2}.get(extension, 0),
    )
    shader.uniform_int("filter_mode", 0 if filter_mode == "NEAREST" else 1)
    gpu.compute.dispatch(
        shader,
        int(math.ceil(width / LOCAL_SIZE_X)),
        int(math.ceil(height / LOCAL_SIZE_Y)),
        1,
    )
    flat = list(_flatten(colour_texture.read().to_list()))
    return [
        tuple(flat[index * 4:index * 4 + 4])  # type: ignore[list-item]
        for index in range(count)
    ]


def sample_image(
    image: bpy.types.Image,
    uvs: Iterable[Sequence[float]],
    *,
    extension: str = "REPEAT",
    filter_mode: str = "BILINEAR",
    requested: str = "AUTO",
    batch_size: int = 65_536,
    source_pixels: Sequence[float] | None = None,
    memory_limit_mb: int = 512,
) -> tuple[list[tuple[float, float, float, float]] | None, BackendDecision]:
    """Sample one Blender image on the GPU or report a safe CPU fallback."""

    decision = resolve_backend(requested)
    if decision.used != "GPU":
        return None, decision
    if extension == "CLIP":
        return None, BackendDecision(
            requested=decision.requested,
            used="CPU",
            available=True,
            reason="CLIP edge sampling uses the CPU parity path",
            backend=decision.backend,
            device=decision.device,
        )
    values = [(float(value[0]), float(value[1])) for value in uvs]
    memory_limit_bytes = max(64, int(memory_limit_mb)) * 1024 * 1024
    source_bytes = int(image.size[0]) * int(image.size[1]) * 16
    available_batch_bytes = memory_limit_bytes - source_bytes
    if available_batch_bytes < 24 * 1_024:
        return None, BackendDecision(
            requested=decision.requested,
            used="CPU",
            available=False,
            reason=(
                f"GPU memory limit ({memory_limit_mb} MiB) is too small for "
                f"the source texture ({source_bytes / (1024 * 1024):.1f} MiB)"
            ),
            backend=decision.backend,
            device=decision.device,
        )
    max_safe_batch = max(1_024, available_batch_bytes // 24)
    batch_size = max(1_024, min(1_000_000, int(batch_size), max_safe_batch))
    try:
        colours = []
        for offset in range(0, len(values), batch_size):
            colours.extend(
                _sample_chunk(
                    image,
                    values[offset:offset + batch_size],
                    extension=extension,
                    filter_mode=filter_mode,
                    source_pixels=source_pixels,
                    memory_limit_bytes=memory_limit_bytes,
                )
            )
        return colours, decision
    except Exception as exc:
        return None, BackendDecision(
            requested=decision.requested,
            used="CPU",
            available=False,
            reason=f"GPU batch failed; CPU fallback: {type(exc).__name__}: {exc}",
            backend=decision.backend,
            device=decision.device,
        )


def clear_runtime_cache() -> None:
    global _SHADER, _OCCUPANCY_SHADER, _SOURCE_TEXTURE_CACHE_BYTES
    _SHADER = None
    _OCCUPANCY_SHADER = None
    _SOURCE_TEXTURE_CACHE.clear()
    _SOURCE_TEXTURE_CACHE_BYTES = 0
