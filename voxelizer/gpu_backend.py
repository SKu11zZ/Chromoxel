"""Optional GPU batch texture sampling for Chromoxel.

The Blender ``gpu`` module needs an interactive graphics context.  Background
and unsupported sessions therefore resolve to the CPU without making Preview
or CLI workflows fail.  GPU work is intentionally limited to a bounded batch
of UV texture reads; Blender data access and BVH queries remain on the CPU.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict
from dataclasses import dataclass
import math
from typing import Iterable, Sequence

import bpy


LOCAL_SIZE_X = 16
LOCAL_SIZE_Y = 16
MAX_ROW_WIDTH = 4096
_SHADER = None
_SOURCE_TEXTURE_CACHE = OrderedDict()
_SOURCE_TEXTURE_CACHE_BYTES = 0


@dataclass(frozen=True)
class BackendDecision:
    requested: str
    used: str
    available: bool
    reason: str
    backend: str = ""
    device: str = ""


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


def _flatten(values):
    if isinstance(values, (list, tuple)):
        for value in values:
            yield from _flatten(value)
    else:
        yield float(values)


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
    global _SHADER, _SOURCE_TEXTURE_CACHE_BYTES
    _SHADER = None
    _SOURCE_TEXTURE_CACHE.clear()
    _SOURCE_TEXTURE_CACHE_BYTES = 0
