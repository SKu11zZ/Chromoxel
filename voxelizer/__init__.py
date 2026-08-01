"""Blender UI and operators for Chromoxel."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

from . import core, live, preview


bl_info = {
    "name": "Chromoxel",
    "author": "SKu11zZ",
    "version": (0, 3, 2),
    "blender": (5, 1, 0),
    "location": "3D Viewport > Sidebar > Voxelizer",
    "description": "Build a texture-aware, symmetry-safe voxel shell from a mesh",
    "category": "Object",
}


# Public aliases keep test and saved-file inspection simple.
TOOL_ID = core.TOOL_ID
TOOL_TAG = core.TOOL_TAG
KIND_TAG = core.KIND_TAG
SOURCE_TAG = core.SOURCE_TAG
PREVIEW_KIND = core.PREVIEW_KIND
BAKE_KIND = core.BAKE_KIND
HELPER_KIND = core.HELPER_KIND
COLOUR_ATTRIBUTE = core.COLOUR_ATTRIBUTE
VoxelizerError = core.VoxelizerError
_preview_name = core.preview_name
_watertight_name = core.watertight_name
_bake_name = core.bake_name
_is_tool_output = core.is_tool_output


def _display_setting_changed(settings, context) -> None:
    live.settings_changed(settings, context, "DISPLAY")


def _geometry_setting_changed(settings, context) -> None:
    live.settings_changed(settings, context, "GEOMETRY")


class VOXELIZER_PG_settings(PropertyGroup):
    live_update: BoolProperty(
        name="Live Update",
        description="Allow a started live session to follow source changes",
        default=True,
    )
    live_debounce: FloatProperty(
        name="Debounce",
        description="Wait after the last geometry change before rebuilding",
        default=0.25,
        min=0.05,
        max=2.0,
        precision=2,
        subtype="TIME",
    )
    live_running: BoolProperty(
        name="Live Running",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    live_source: PointerProperty(
        name="Live Source",
        type=bpy.types.Object,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    live_status: StringProperty(
        name="Live Status",
        default="Idle",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    live_last_seconds: FloatProperty(
        name="Last Build Seconds",
        default=0.0,
        min=0.0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    live_point_count: IntProperty(
        name="Point Count",
        default=0,
        min=0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    live_build_count: IntProperty(
        name="Build Count",
        default=0,
        min=0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    auto_watertight_copy: BoolProperty(
        name="Auto Watertight Copy",
        description=(
            "For a non-manifold source, build a private voxel-remeshed copy "
            "for occupancy while leaving the source untouched"
        ),
        default=True,
        update=_geometry_setting_changed,
    )
    repair_voxel_size: FloatProperty(
        name="Repair Voxel Size",
        description=(
            "Voxel Remesh resolution for the private watertight copy; "
            "smaller values preserve finer detail but cost more memory and time"
        ),
        default=0.08,
        min=0.005,
        soft_max=1.0,
        precision=4,
        unit="LENGTH",
        update=_geometry_setting_changed,
    )
    voxel_size: FloatProperty(
        name="Voxel Size",
        description="Grid cell size in the source object's local space",
        default=0.25,
        min=0.001,
        soft_max=10.0,
        precision=4,
        unit="LENGTH",
        update=_geometry_setting_changed,
    )
    cube_gap: FloatProperty(
        name="Cube Gap",
        description="Empty distance between neighbouring cube faces",
        default=0.025,
        min=0.0,
        soft_max=1.0,
        precision=4,
        unit="LENGTH",
        update=_display_setting_changed,
    )
    uv_map: StringProperty(
        name="UV Map",
        description="UV layer used to sample BaseColor Image",
        default="",
    )
    base_color_image: PointerProperty(
        name="BaseColor Image",
        description="Image sampled through the selected UV map",
        type=bpy.types.Image,
    )
    fallback_color: FloatVectorProperty(
        name="Fallback Color",
        description="Colour used when no valid image/UV sample is available",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.48, 0.8, 1.0),
    )


class VOXELIZER_OT_preview(Operator):
    bl_idname = "voxelizer.preview"
    bl_label = "Add / Refresh Preview"
    bl_description = "Create or refresh a tagged, independent gapped-cube preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            source = core.selected_source(context)
            settings = context.scene.voxelizer_settings
            update = preview.refresh_preview(
                context,
                source,
                settings,
                force_rebuild=True,
            )
            output = update.output
            settings.live_point_count = update.point_count
            settings.live_build_count = update.build_count
            settings.live_last_seconds = update.elapsed_seconds
            output.hide_render = False
            context.view_layer.objects.active = source
            source.select_set(True)
            self.report(
                {"INFO"},
                f"Preview: {update.point_count:,} voxels "
                f"({'image/UV' if update.used_image else 'fallback'} colour), "
                f"{update.reason.lower()}, build {update.build_count}, "
                f"{update.elapsed_seconds:.3f}s.",
            )
            return {"FINISHED"}
        except core.VoxelizerError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Voxelizer failed: {exc}")
            return {"CANCELLED"}


class VOXELIZER_OT_bake(Operator):
    bl_idname = "voxelizer.bake"
    bl_label = "Bake to Mesh"
    bl_description = "Create a realized <Source>_VOX mesh with retained voxel colours"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            source = core.selected_source(context)
            settings = context.scene.voxelizer_settings
            name = core.bake_name(source)
            core.assert_name_available(name)
            mesh, count, used_image = core.build_voxel_mesh(
                context,
                source,
                settings,
                f"{name}_Mesh",
            )
            try:
                output = core.link_output(
                    context,
                    source,
                    mesh,
                    name,
                    core.BAKE_KIND,
                )
            except Exception:
                bpy.data.meshes.remove(mesh)
                raise
            output.hide_render = False
            context.view_layer.objects.active = output
            for selected in tuple(context.selected_objects):
                selected.select_set(False)
            output.select_set(True)
            self.report(
                {"INFO"},
                f"Baked {count:,} voxels "
                f"({'image/UV' if used_image else 'fallback'} colour).",
            )
            return {"FINISHED"}
        except core.VoxelizerError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Voxelizer failed: {exc}")
            return {"CANCELLED"}


class VOXELIZER_OT_clear(Operator):
    bl_idname = "voxelizer.clear"
    bl_label = "Clear"
    bl_description = "Delete only objects tagged as Chromoxel outputs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        live.cancel_pending(
            context.scene.voxelizer_settings,
            stop_running=True,
        )
        preview.clear_runtime_cache()
        count = core.clear_tagged_outputs()
        self.report({"INFO"}, f"Cleared {count} tagged Voxelizer output(s).")
        return {"FINISHED"}


class VOXELIZER_OT_live_toggle(Operator):
    bl_idname = "voxelizer.live_toggle"
    bl_label = "Start / Stop Live"
    bl_description = "Start watching the selected source, or stop the live session"

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        if settings.live_running:
            live.stop(settings)
            return {"FINISHED"}
        if not settings.live_update:
            self.report({"WARNING"}, "Enable Live Update before starting.")
            return {"CANCELLED"}
        try:
            source = core.selected_source(context)
        except core.VoxelizerError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.live_source = source
        live.start(settings)
        return {"FINISHED"}


class VOXELIZER_PT_panel(Panel):
    bl_label = "Chromoxel"
    bl_idname = "VOXELIZER_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Voxelizer"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.voxelizer_settings
        repair_box = layout.box()
        repair_box.prop(settings, "auto_watertight_copy")
        repair_box.prop(settings, "repair_voxel_size")
        source = context.active_object
        if source is not None and source.type == "MESH":
            diagnostics = core.mesh_diagnostics(source.data)
            if core.is_closed_manifold(source.data):
                repair_box.label(text="Status: source is already watertight", icon="CHECKMARK")
            elif settings.auto_watertight_copy:
                repair_box.label(text="Status: repair copy will be used", icon="MOD_REMESH")
            else:
                repair_box.label(text="Status: non-manifold source is blocked", icon="ERROR")
            repair_box.label(
                text=(
                    f"Boundary {diagnostics['boundary_edges']}  ·  "
                    f"Components {diagnostics['components']}"
                )
            )
        else:
            repair_box.label(text="Status: select one Mesh source", icon="INFO")
        layout.separator()
        layout.prop(settings, "voxel_size")
        layout.prop(settings, "cube_gap")
        if source is not None and source.type == "MESH":
            layout.prop_search(
                settings,
                "uv_map",
                source.data,
                "uv_layers",
                text="UV Map",
            )
        else:
            layout.prop(settings, "uv_map")
        layout.prop(settings, "base_color_image")
        layout.prop(settings, "fallback_color")
        layout.separator()
        live_box = layout.box()
        live_box.prop(settings, "live_update")
        live_box.prop(settings, "live_debounce")
        live_box.operator(
            VOXELIZER_OT_live_toggle.bl_idname,
            text="Stop Live" if settings.live_running else "Start Live",
            icon="PAUSE" if settings.live_running else "PLAY",
        )
        live_box.label(text=f"Status: {settings.live_status}")
        live_box.label(
            text=(
                f"Points {settings.live_point_count:,}  "
                f"Builds {settings.live_build_count:,}  "
                f"{settings.live_last_seconds:.3f}s"
            )
        )
        layout.separator()
        layout.operator(VOXELIZER_OT_preview.bl_idname, icon="MOD_BUILD")
        layout.operator(VOXELIZER_OT_bake.bl_idname, icon="MESH_CUBE")
        layout.operator(VOXELIZER_OT_clear.bl_idname, icon="TRASH")


CLASSES = (
    VOXELIZER_PG_settings,
    VOXELIZER_OT_preview,
    VOXELIZER_OT_bake,
    VOXELIZER_OT_clear,
    VOXELIZER_OT_live_toggle,
    VOXELIZER_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.voxelizer_settings = PointerProperty(type=VOXELIZER_PG_settings)
    live.register_handlers()


def unregister():
    live.unregister_handlers()
    if hasattr(bpy.types.Scene, "voxelizer_settings"):
        del bpy.types.Scene.voxelizer_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
