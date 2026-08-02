"""Lightweight, non-realized Geometry Nodes preview carrier."""

from __future__ import annotations

import hashlib
import struct
import time
from collections.abc import Iterable
from dataclasses import dataclass

import bpy


TOOL_ID = "org.openai.textured_voxelizer_mvp"
TOOL_TAG = "_textured_voxelizer_tool"
KIND_TAG = "_textured_voxelizer_kind"
SOURCE_TAG = "_textured_voxelizer_source"
PREVIEW_GROUP_KIND = "preview_node_group"
PREVIEW_MODIFIER_KIND = "preview_instancer"
COLOUR_ATTRIBUTE = "voxel_color"
GROUP_NAME = ".BTVM_PREVIEW_INSTANCER"
MODIFIER_NAME = ".BTVM Preview Instances"
SCALE_SOCKET_NAME = "Cube Size"
CACHE_KEY_TAG = "_textured_voxelizer_cache_key"
POINT_HASH_TAG = "_textured_voxelizer_point_hash"
BUILD_COUNT_TAG = "_textured_voxelizer_build_count"
POINT_COUNT_TAG = "_textured_voxelizer_point_count"
USED_IMAGE_TAG = "_textured_voxelizer_used_image"
CUBE_SIZE_TAG = "_textured_voxelizer_cube_size"
SAFE_MINIMUM = 1.0e-6
_RUNTIME_CACHE: dict[int, dict[str, object]] = {}


class PreviewError(RuntimeError):
    """Raised when private preview data would collide with user data."""


@dataclass(frozen=True)
class PreviewUpdate:
    output: bpy.types.Object
    point_count: int
    used_image: bool
    rebuilt: bool
    reason: str
    build_count: int
    point_hash: str
    cube_size: float
    elapsed_seconds: float


def _tag(datablock, kind: str) -> None:
    datablock[TOOL_TAG] = TOOL_ID
    datablock[KIND_TAG] = kind


def _is_owned(datablock, kind: str) -> bool:
    return (
        datablock.get(TOOL_TAG) == TOOL_ID
        and datablock.get(KIND_TAG) == kind
    )


def _new_interface_socket(group, name: str, in_out: str, socket_type: str):
    return group.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type=socket_type,
    )


def ensure_node_group(material: bpy.types.Material) -> bpy.types.NodeTree:
    """Return the private instancer group without rewriting a valid shared group."""

    group = bpy.data.node_groups.get(GROUP_NAME)
    if group is not None and not _is_owned(group, PREVIEW_GROUP_KIND):
        raise PreviewError(
            f'Node group name "{GROUP_NAME}" is occupied by user data; '
            "refusing to overwrite it."
        )
    if group is not None:
        required = {
            "BTVM_Group_Input",
            "BTVM_Reusable_Cube",
            "BTVM_Set_Material",
            "BTVM_Cube_Scale",
            "BTVM_Instance_on_Points",
            "BTVM_Group_Output",
        }
        if not required.issubset(set(group.nodes.keys())):
            raise PreviewError("Private preview node group is incomplete; refusing mutation.")
        if any(node.bl_idname == "GeometryNodeRealizeInstances" for node in group.nodes):
            raise PreviewError("Private preview node group unexpectedly contains Realize Instances.")
        group.nodes["BTVM_Set_Material"].inputs["Material"].default_value = material
        return group

    group = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    _tag(group, PREVIEW_GROUP_KIND)
    if hasattr(group, "is_modifier"):
        group.is_modifier = True

    geometry_in = _new_interface_socket(
        group, "Geometry", "INPUT", "NodeSocketGeometry"
    )
    scale_in = _new_interface_socket(
        group, SCALE_SOCKET_NAME, "INPUT", "NodeSocketFloat"
    )
    scale_in.default_value = 1.0
    scale_in.min_value = 0.0
    geometry_out = _new_interface_socket(
        group, "Geometry", "OUTPUT", "NodeSocketGeometry"
    )

    nodes = group.nodes
    links = group.links
    group_input = nodes.new("NodeGroupInput")
    group_input.name = "BTVM_Group_Input"
    group_input.location = (-520.0, 80.0)
    cube = nodes.new("GeometryNodeMeshCube")
    cube.name = "BTVM_Reusable_Cube"
    cube.label = "Single Reusable Cube"
    cube.location = (-520.0, -170.0)
    cube.inputs["Size"].default_value = (1.0, 1.0, 1.0)
    set_material = nodes.new("GeometryNodeSetMaterial")
    set_material.name = "BTVM_Set_Material"
    set_material.location = (-280.0, -170.0)
    set_material.inputs["Material"].default_value = material
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.name = "BTVM_Cube_Scale"
    combine.location = (-280.0, 10.0)
    instances = nodes.new("GeometryNodeInstanceOnPoints")
    instances.name = "BTVM_Instance_on_Points"
    instances.location = (0.0, 80.0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.name = "BTVM_Group_Output"
    group_output.is_active_output = True
    group_output.location = (250.0, 80.0)

    links.new(group_input.outputs[geometry_in.identifier], instances.inputs["Points"])
    links.new(cube.outputs["Mesh"], set_material.inputs["Geometry"])
    links.new(set_material.outputs["Geometry"], instances.inputs["Instance"])
    for axis in ("X", "Y", "Z"):
        links.new(group_input.outputs[scale_in.identifier], combine.inputs[axis])
    links.new(combine.outputs["Vector"], instances.inputs["Scale"])
    links.new(instances.outputs["Instances"], group_output.inputs[geometry_out.identifier])
    return group


def _input_identifier(group: bpy.types.NodeTree, socket_name: str) -> str:
    for item in group.interface.items_tree:
        if (
            getattr(item, "item_type", None) == "SOCKET"
            and getattr(item, "in_out", None) == "INPUT"
            and item.name == socket_name
        ):
            return item.identifier
    raise PreviewError(f'Geometry Nodes input "{socket_name}" is missing.')


def ensure_modifier(
    output: bpy.types.Object,
    material: bpy.types.Material,
    cube_size: float,
) -> bpy.types.Modifier:
    modifier = output.modifiers.get(MODIFIER_NAME)
    if modifier is not None and not _is_owned(modifier, PREVIEW_MODIFIER_KIND):
        reloaded_owned_modifier = (
            output.get(TOOL_TAG) == TOOL_ID
            and output.get(KIND_TAG) == "preview"
            and isinstance(output.get(SOURCE_TAG), str)
            and bpy.data.objects.get(output.get(SOURCE_TAG)) is not None
            and modifier.type == "NODES"
            and modifier.node_group is not None
            and _is_owned(modifier.node_group, PREVIEW_GROUP_KIND)
        )
        if not reloaded_owned_modifier:
            raise PreviewError(
                f'Modifier name "{MODIFIER_NAME}" is occupied by user data; '
                "refusing to overwrite it."
            )
        _tag(modifier, PREVIEW_MODIFIER_KIND)
    if modifier is None:
        modifier = output.modifiers.new(MODIFIER_NAME, "NODES")
    if modifier.type != "NODES":
        raise PreviewError("Private preview modifier has an unexpected type.")
    group = ensure_node_group(material)
    if modifier.node_group != group:
        modifier.node_group = group
    # Assigning a node group clears a Geometry Nodes modifier's ID properties,
    # so ownership is written after assignment.
    _tag(modifier, PREVIEW_MODIFIER_KIND)
    modifier[_input_identifier(group, SCALE_SOCKET_NAME)] = float(cube_size)
    return modifier


def set_cube_size(output: bpy.types.Object, cube_size: float) -> bpy.types.Modifier:
    """Change only the per-object GN scale input for a display-only update."""

    modifier = output.modifiers.get(MODIFIER_NAME)
    if modifier is None or not _is_owned(modifier, PREVIEW_MODIFIER_KIND):
        raise PreviewError("Owned preview Geometry Nodes modifier is missing.")
    group = modifier.node_group
    if group is None or not _is_owned(group, PREVIEW_GROUP_KIND):
        raise PreviewError("Owned preview Geometry Nodes group is missing.")
    modifier[_input_identifier(group, SCALE_SOCKET_NAME)] = float(cube_size)
    return modifier


def build_carrier_mesh(
    mesh_name: str,
    centres: Iterable[Iterable[float]],
    colours: Iterable[Iterable[float]],
) -> bpy.types.Mesh:
    """Create V points/zero faces with POINT-domain ``voxel_color``."""

    centre_values = [tuple(float(value) for value in centre) for centre in centres]
    colour_values = [tuple(float(value) for value in colour) for colour in colours]
    if len(centre_values) != len(colour_values):
        raise PreviewError("Every preview point must have exactly one colour.")
    if not centre_values:
        raise PreviewError("Preview carrier cannot be empty.")

    mesh = bpy.data.meshes.new(mesh_name)
    try:
        mesh.from_pydata(centre_values, (), ())
        attribute = mesh.color_attributes.new(
            name=COLOUR_ATTRIBUTE,
            type="FLOAT_COLOR",
            domain="POINT",
        )
        for datum, colour in zip(attribute.data, colour_values):
            datum.color = colour
        mesh.update()
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    return mesh


def configure_preview(
    output: bpy.types.Object,
    centres: Iterable[Iterable[float]],
    colours: Iterable[Iterable[float]],
    cube_size: float,
    material: bpy.types.Material,
) -> int:
    """Replace an owned preview's carrier and attach its non-realized instancer."""

    mesh = build_carrier_mesh(f"{output.name}_Carrier", centres, colours)
    old_mesh = output.data if output.type == "MESH" else None
    try:
        output.data = mesh
        ensure_modifier(output, material, cube_size)
    except Exception:
        if output.data is mesh:
            output.data = old_mesh
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return len(mesh.vertices)


def display_cube_size(settings) -> float:
    voxel_size = float(settings.voxel_size)
    return max(
        voxel_size - float(settings.cube_gap),
        max(SAFE_MINIMUM, abs(voxel_size) * SAFE_MINIMUM),
    )


def _point_hash(
    centres: Iterable[Iterable[float]],
    colours: Iterable[Iterable[float]],
) -> str:
    digest = hashlib.sha256()
    for centre, colour in zip(centres, colours):
        digest.update(
            struct.pack(
                "<7d",
                *(float(value) for value in tuple(centre) + tuple(colour)),
            )
        )
    return digest.hexdigest()


def _carrier_is_valid(output: bpy.types.Object) -> bool:
    if output.type != "MESH" or len(output.data.polygons) != 0:
        return False
    attribute = output.data.color_attributes.get(COLOUR_ATTRIBUTE)
    return (
        attribute is not None
        and attribute.domain == "POINT"
        and attribute.data_type == "FLOAT_COLOR"
        and len(attribute.data) == len(output.data.vertices)
    )


def clear_runtime_cache() -> None:
    _RUNTIME_CACHE.clear()
    try:
        from . import core

        core.clear_sampling_cache()
    except (AttributeError, ImportError):
        pass


def refresh_preview_iter(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    force_rebuild: bool,
):
    """Incrementally synchronize one object-local preview."""

    from . import core

    started = time.perf_counter()
    core.validate_settings(settings)
    name = core.preview_name(source)
    existing = core.assert_name_available(
        name,
        replace_owned_preview_for=source,
    )
    cache_key = core.preview_sampling_key(context, source, settings)
    cube_size = display_cube_size(settings)
    source_pointer = source.as_pointer()

    if (
        not force_rebuild
        and existing is not None
        and _carrier_is_valid(existing)
        and existing.get(CACHE_KEY_TAG) == cache_key
    ):
        matrix_changed = existing.matrix_world != source.matrix_world
        previous_cube_size = float(existing.get(CUBE_SIZE_TAG, cube_size))
        display_changed = abs(previous_cube_size - cube_size) > 1.0e-12
        if display_changed:
            set_cube_size(existing, cube_size)
            existing[CUBE_SIZE_TAG] = cube_size
        existing.matrix_world = source.matrix_world.copy()
        core.tag_output(existing, source, core.PREVIEW_KIND)
        point_count = len(existing.data.vertices)
        point_hash = str(existing.get(POINT_HASH_TAG, ""))
        build_count = int(existing.get(BUILD_COUNT_TAG, 0))
        used_image = bool(existing.get(USED_IMAGE_TAG, False))
        _RUNTIME_CACHE[source_pointer] = {
            "output_pointer": existing.as_pointer(),
            "mesh_pointer": existing.data.as_pointer(),
            "cache_key": cache_key,
            "point_hash": point_hash,
            "build_count": build_count,
        }
        reason = (
            "DISPLAY"
            if display_changed
            else "TRANSFORM"
            if matrix_changed
            else "CACHED"
        )
        return PreviewUpdate(
            output=existing,
            point_count=point_count,
            used_image=used_image,
            rebuilt=False,
            reason=reason,
            build_count=build_count,
            point_hash=point_hash,
            cube_size=cube_size,
            elapsed_seconds=time.perf_counter() - started,
        )

    centres, colours, point_count, used_image = yield from core.sample_surface_voxels_iter(
        context,
        source,
        settings,
        cache_key=cache_key,
    )
    material = core.ensure_colour_material()
    output = existing
    if output is None:
        empty_mesh = bpy.data.meshes.new(f"{name}_Carrier")
        output = core.link_output(
            context,
            source,
            empty_mesh,
            name,
            core.PREVIEW_KIND,
        )
    try:
        configure_preview(
            output,
            centres,
            colours,
            cube_size,
            material,
        )
    except Exception:
        if existing is None and output.name in bpy.data.objects:
            failed_mesh = output.data
            bpy.data.objects.remove(output, do_unlink=True)
            if failed_mesh.users == 0:
                bpy.data.meshes.remove(failed_mesh)
        raise

    output.matrix_world = source.matrix_world.copy()
    core.tag_output(output, source, core.PREVIEW_KIND)
    point_hash = _point_hash(centres, colours)
    build_count = int(output.get(BUILD_COUNT_TAG, 0)) + 1
    output[CACHE_KEY_TAG] = cache_key
    output[POINT_HASH_TAG] = point_hash
    output[BUILD_COUNT_TAG] = build_count
    output[POINT_COUNT_TAG] = point_count
    output[USED_IMAGE_TAG] = bool(used_image)
    output[CUBE_SIZE_TAG] = cube_size
    _RUNTIME_CACHE[source_pointer] = {
        "output_pointer": output.as_pointer(),
        "mesh_pointer": output.data.as_pointer(),
        "cache_key": cache_key,
        "point_hash": point_hash,
        "build_count": build_count,
    }
    return PreviewUpdate(
        output=output,
        point_count=point_count,
        used_image=used_image,
        rebuilt=True,
        reason="MANUAL" if force_rebuild else "GEOMETRY",
        build_count=build_count,
        point_hash=point_hash,
        cube_size=cube_size,
        elapsed_seconds=time.perf_counter() - started,
    )


def refresh_preview(
    context: bpy.types.Context,
    source: bpy.types.Object,
    settings,
    *,
    force_rebuild: bool,
    progress_callback=None,
) -> PreviewUpdate:
    """Synchronous preview API used by Live, scripts, and background tests."""

    generator = refresh_preview_iter(
        context,
        source,
        settings,
        force_rebuild=force_rebuild,
    )
    while True:
        try:
            progress = next(generator)
        except StopIteration as stop:
            return stop.value
        if progress_callback is not None:
            progress_callback(progress)
