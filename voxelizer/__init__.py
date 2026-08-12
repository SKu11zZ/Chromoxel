"""Blender UI and operators for Chromoxel."""

from __future__ import annotations

import time

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

from . import core, editable, editor, gpu_backend, i18n, live, meshing, preview, vox_io


bl_info = {
    "name": "Chromoxel",
    "author": "Moore \"Zz11uKS\" Ji",
    "version": (0, 9, 0),
    "blender": (5, 1, 0),
    "location": "3D Viewport > Sidebar > Voxelizer",
    "description": "Build adaptive, texture-aware, symmetry-safe voxel shells",
    "category": "Object",
}


# Public aliases keep tests and saved-file inspection simple.
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


def _voxel_size_changed(settings, context) -> None:
    settings.quality_preset = "CUSTOM"
    _geometry_setting_changed(settings, context)


class VOXELIZER_PG_settings(PropertyGroup):
    ui_language: EnumProperty(
        name="UI Language",
        items=(
            ("AUTO", "Auto", "Follow Blender interface language"),
            ("EN", "English", "Use English Chromoxel labels"),
            ("ZH", "中文", "使用中文 Chromoxel 标签"),
        ),
        default="AUTO",
    )
    source_scope: EnumProperty(
        name="Source Scope",
        description="Choose which mesh objects Preview and Bake process",
        items=(
            ("ACTIVE", "Active", "Process only the active selected mesh"),
            ("SELECTED", "Selected", "Process every eligible selected mesh"),
            ("COLLECTION", "Collection", "Process meshes in a collection"),
        ),
        default="ACTIVE",
    )
    source_collection: PointerProperty(
        name="Source Collection",
        type=bpy.types.Collection,
    )
    include_hidden: BoolProperty(
        name="Include Hidden",
        description="Include hidden meshes when Collection scope is used",
        default=False,
    )
    quality_preset: EnumProperty(
        name="Quality",
        items=(
            ("CUSTOM", "Custom", "Voxel Size was entered manually"),
            ("COARSE", "Coarse", "About 12 cells across the longest source axis"),
            ("MEDIUM", "Medium", "About 24 cells across the longest source axis"),
            ("FINE", "Fine", "About 48 cells across the longest source axis"),
        ),
        default="CUSTOM",
        options={"HIDDEN"},
    )
    grid_origin_mode: EnumProperty(
        name="Grid Origin",
        description="Anchor the voxel lattice for repeatable results",
        items=(
            ("OBJECT", "Object Origin", "Anchor the lattice at local (0, 0, 0)"),
            ("CUSTOM", "Custom", "Anchor the lattice at a custom local coordinate"),
            ("BOUNDS", "Legacy Bounds", "Start each non-symmetric axis at its bounds"),
        ),
        default="OBJECT",
        update=_geometry_setting_changed,
    )
    grid_origin: FloatVectorProperty(
        name="Custom Origin",
        description="Local-space grid anchor used in Custom mode",
        size=3,
        subtype="XYZ",
        unit="LENGTH",
        default=(0.0, 0.0, 0.0),
        update=_geometry_setting_changed,
    )
    live_update: BoolProperty(
        name="Live Update",
        description="Allow a started live session to follow active-source changes",
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
            "Voxel Remesh resolution for the private watertight copy; smaller "
            "values preserve finer detail but cost more memory and time"
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
        description="Grid cell size in each source object's local space",
        default=0.25,
        min=0.001,
        soft_max=10.0,
        precision=4,
        unit="LENGTH",
        update=_voxel_size_changed,
    )
    sampling_mode: EnumProperty(
        name="Detail Mode",
        description="Use one uniform grid or automatically refine high-error surface cells",
        items=(
            ("ADAPTIVE", "Adaptive", "Refine texture boundaries and sharp geometry automatically"),
            ("UNIFORM", "Uniform", "Use the legacy single-size voxel grid"),
        ),
        default="ADAPTIVE",
        update=_geometry_setting_changed,
    )
    adaptive_max_level: IntProperty(
        name="Max Detail Level",
        description="Maximum power-of-two refinement depth; 2 means base, half, and quarter size",
        default=2,
        min=0,
        max=4,
        update=_geometry_setting_changed,
    )
    adaptive_texture_threshold: FloatProperty(
        name="Texture Error",
        description="Minimum colour range inside a voxel before it is refined",
        default=0.16,
        min=0.01,
        max=1.0,
        precision=3,
        update=_geometry_setting_changed,
    )
    adaptive_geometry_angle: FloatProperty(
        name="Geometry Angle",
        description="Minimum nearby edge angle in degrees before a voxel is refined",
        default=35.0,
        min=1.0,
        max=180.0,
        precision=1,
        update=_geometry_setting_changed,
    )
    adaptive_geometry_max_level: IntProperty(
        name="Geometry Detail Level",
        description="Maximum refinement depth used only for sharp geometry edges",
        default=1,
        min=0,
        max=4,
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
        update=_geometry_setting_changed,
    )
    base_color_image: PointerProperty(
        name="BaseColor Image",
        description="Image sampled through the selected UV map",
        type=bpy.types.Image,
        update=_geometry_setting_changed,
    )
    auto_material_images: BoolProperty(
        name="Auto Material Images",
        description="When no override image is selected, find Base Color images from material nodes",
        default=True,
        update=_geometry_setting_changed,
    )
    texture_filter: EnumProperty(
        name="Texture Filter",
        description="How UV image samples are reconstructed",
        items=(
            ("BILINEAR", "Bilinear", "Filtered sampling for stable texture boundaries"),
            ("NEAREST", "Nearest", "Legacy point sampling for pixel-art sources"),
        ),
        default="BILINEAR",
        update=_geometry_setting_changed,
    )
    compute_backend: EnumProperty(
        name="Compute Backend",
        description="Choose CPU sampling or GPU batch texture sampling with automatic fallback",
        items=(
            ("AUTO", "Auto", "Use GPU when an interactive compute context is available"),
            ("GPU", "GPU", "Request GPU batch sampling and fall back safely when unavailable"),
            ("CPU", "CPU", "Use the deterministic CPU sampling path"),
        ),
        default="AUTO",
        update=_geometry_setting_changed,
    )
    gpu_batch_size: IntProperty(
        name="GPU Batch Size",
        description="Maximum UV samples submitted per bounded GPU dispatch",
        default=65_536,
        min=1_024,
        max=1_000_000,
        subtype="UNSIGNED",
        update=_geometry_setting_changed,
    )
    gpu_memory_limit_mb: IntProperty(
        name="GPU Memory Limit (MiB)",
        description=(
            "Upper bound for cached source textures and temporary UV/colour "
            "buffers; oversized jobs fall back to CPU"
        ),
        default=512,
        min=64,
        max=8192,
        subtype="UNSIGNED",
        update=_geometry_setting_changed,
    )
    fallback_color: FloatVectorProperty(
        name="Fallback Color",
        description="Colour used when no valid image/UV sample is available",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.48, 0.8, 1.0),
        update=_geometry_setting_changed,
    )
    color_mode: EnumProperty(
        name="Edit Color Mode",
        items=(
            ("DIRECT", "Direct Color", "Store unrestricted per-voxel colours"),
            ("PALETTE", "Palette", "Reference editable palette/material slots"),
        ),
        default="DIRECT",
    )
    edit_color: FloatVectorProperty(
        name="Edit Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.48, 0.8, 1.0),
    )
    edit_material_id: IntProperty(name="Material ID", default=0, min=0)
    edit_roughness: FloatProperty(name="Roughness", default=0.5, min=0.0, max=1.0)
    edit_metallic: FloatProperty(name="Metallic", default=0.0, min=0.0, max=1.0)
    edit_emission: FloatProperty(name="Emission", default=0.0, min=0.0, soft_max=25.0)
    palette_slots: CollectionProperty(type=editor.VOXELIZER_PG_palette_slot)
    palette_active_index: IntProperty(name="Palette Slot", default=0, min=0, max=254)
    bake_mode: EnumProperty(
        name="Bake Output",
        items=(
            ("EDITABLE", "Editable Points", "Duplicate the editable point carrier"),
            ("REALIZED", "Realized Cubes", "Build one independent cube per voxel"),
            ("SURFACE", "Surface Mesh", "Remove hidden faces between atomic voxels"),
            ("GREEDY", "Greedy Mesh", "Merge compatible coplanar voxel faces"),
        ),
        default="REALIZED",
    )
    remove_enclosed_voxels: BoolProperty(
        name="Remove Enclosed Voxels",
        description=(
            "Delete voxels whose six axis-aligned sides are completely covered; "
            "exterior silhouettes, thin parts, holes, colours, and UV data are preserved"
        ),
        default=False,
    )
    vox_import_size: FloatProperty(
        name="VOX Unit Size",
        description="Blender-unit size assigned to one imported VOX cell",
        default=0.1,
        min=0.0001,
        soft_max=10.0,
        precision=4,
        unit="LENGTH",
    )
    use_sparse_candidates: BoolProperty(
        name="Sparse Surface Candidates",
        description="Use sparse triangle candidates once the grid reaches the threshold",
        default=True,
        update=_geometry_setting_changed,
    )
    sparse_grid_threshold: IntProperty(
        name="Sparse Grid Threshold",
        description="Use sparse candidates at or above this full-grid cell count",
        default=50_000,
        min=0,
        max=100_000_000,
        update=_geometry_setting_changed,
    )
    sample_budget: IntProperty(
        name="Candidate Limit",
        description="Maximum candidate cells processed for one source",
        default=1_500_000,
        min=1_000,
        max=100_000_000,
    )
    candidate_expansion_budget: IntProperty(
        name="Expansion Limit",
        description="Maximum triangle-to-grid candidate expansion work per source",
        default=48_000_000,
        min=1_000,
        max=1_000_000_000,
    )
    voxel_budget: IntProperty(
        name="Voxel Limit",
        description="Maximum editable surface voxels produced for one source model",
        default=100_000,
        min=1_000,
        max=100_000,
    )
    sampling_chunk_size: IntProperty(
        name="Task Chunk",
        description="Work units between progress and cancellation checks",
        default=4096,
        min=128,
        max=65_536,
    )
    cache_memory_mb: IntProperty(
        name="Cache Memory",
        description="Maximum in-memory sampling cache size in MiB",
        default=128,
        min=16,
        max=4096,
        subtype="UNSIGNED",
    )
    show_step_source: BoolProperty(name="1. Source", default=True)
    show_step_grid: BoolProperty(name="2. Voxel Grid", default=True)
    show_step_surface: BoolProperty(name="3. Surface Input", default=True)
    show_step_colour: BoolProperty(name="4. Colour", default=True)
    show_step_preview: BoolProperty(name="5. Preview", default=True)
    show_step_bake: BoolProperty(name="6. Bake", default=True)
    show_step_edit: BoolProperty(name="7. Edit & Export", default=False)
    show_step_live: BoolProperty(name="8. Live Preview", default=False)
    show_advanced: BoolProperty(name="Advanced", default=False)
    estimate_summary: StringProperty(
        name="Estimate",
        default="Run Estimate before a fine bake",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    estimate_detail: StringProperty(
        name="Estimate Detail",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    estimate_ok: BoolProperty(
        name="Estimate OK",
        default=True,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_state: EnumProperty(
        name="Surface Check State",
        items=(
            ("UNCHECKED", "Unchecked", "No explicit surface inspection has run"),
            ("WATERTIGHT", "Watertight", "The inspected source is one closed manifold"),
            ("REPAIR", "Repair", "The inspected source requires a private repair copy"),
            ("BLOCKED", "Blocked", "The inspected source is non-manifold and repair is disabled"),
            ("ERROR", "Error", "The explicit surface inspection failed"),
        ),
        default="UNCHECKED",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_source: StringProperty(
        name="Checked Surface Source",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_mesh_pointer: StringProperty(
        name="Checked Surface Mesh Pointer",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_boundary_edges: IntProperty(
        name="Checked Boundary Edges",
        default=0,
        min=0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_components: IntProperty(
        name="Checked Components",
        default=0,
        min=0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_watertight: BoolProperty(
        name="Checked Surface Is Watertight",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    surface_check_seconds: FloatProperty(
        name="Surface Check Seconds",
        default=0.0,
        min=0.0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    task_running: BoolProperty(
        name="Task Running",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    task_cancel_requested: BoolProperty(
        name="Cancel Requested",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    task_progress: FloatProperty(
        name="Progress",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    task_phase: StringProperty(
        name="Task Phase",
        default="Idle",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    task_message: StringProperty(
        name="Task Message",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    performance_summary: StringProperty(
        name="Last Performance Summary",
        default="No voxelization profile yet",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    performance_detail: StringProperty(
        name="Last Performance Detail",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    performance_backend: StringProperty(
        name="Last Compute Backend",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )


class VOXELIZER_OT_quality_preset(Operator):
    bl_idname = "voxelizer.quality_preset"
    bl_label = "Apply Quality Preset"
    bl_description = "Set Voxel Size from the longest source dimension"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        items=(
            ("COARSE", "Coarse", "About 12 cells across"),
            ("MEDIUM", "Medium", "About 24 cells across"),
            ("FINE", "Fine", "About 48 cells across"),
        )
    )

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        try:
            sources = core.source_objects(context, settings)
            longest = 0.0
            for source in sources:
                with core.evaluated_local_mesh(context, source) as mesh:
                    if not mesh.vertices:
                        continue
                    for axis in range(3):
                        values = [float(vertex.co[axis]) for vertex in mesh.vertices]
                        longest = max(longest, max(values) - min(values))
            if longest <= 0.0:
                raise core.VoxelizerError("The source scope has no measurable mesh extent.")
            target_cells = {"COARSE": 12, "MEDIUM": 24, "FINE": 48}[self.preset]
            settings.voxel_size = longest / target_cells
            if settings.cube_gap >= settings.voxel_size:
                settings.cube_gap = settings.voxel_size * 0.1
            settings.quality_preset = self.preset
            self.report(
                {"INFO"},
                f"{self.preset.title()}: {settings.voxel_size:.4g} BU voxel size.",
            )
            return {"FINISHED"}
        except core.VoxelizerError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class VOXELIZER_OT_estimate(Operator):
    bl_idname = "voxelizer.estimate"
    bl_label = "Estimate Work"
    bl_description = "Estimate candidate work and transient cache memory"

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        try:
            report = core.estimate_sources(
                context,
                core.source_objects(context, settings),
                settings,
            )
            memory_mb = int(report["estimated_memory_bytes"]) / (1024 * 1024)
            settings.estimate_summary = (
                f"{report['source_count']} source(s) | "
                f"~{report['estimated_candidates']:,} candidates | "
                f"~{report['estimated_output_voxels']:,} voxels | {memory_mb:.1f} MiB"
            )
            settings.estimate_detail = (
                f"Full grid {report['full_grid_samples']:,} | "
                f"sample {'OK' if report['within_sample_budget'] else 'OVER'} | "
                f"cache {'OK' if report['within_cache_budget'] else 'OVER'}"
            )
            settings.estimate_ok = bool(
                report["within_sample_budget"] and report["within_cache_budget"]
            )
            self.report({"INFO"}, settings.estimate_summary)
            return {"FINISHED"}
        except core.VoxelizerError as exc:
            settings.estimate_summary = str(exc)
            settings.estimate_detail = ""
            settings.estimate_ok = False
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class VOXELIZER_OT_check_surface(Operator):
    """Run the expensive topology inspection only after an explicit click."""

    bl_idname = "voxelizer.check_surface"
    bl_label = "Check Surface"
    bl_description = "Explicitly inspect the active mesh for boundaries and components"

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "voxelizer_settings", None)
        source = context.active_object
        return (
            settings is not None
            and not settings.task_running
            and source is not None
            and source.type == "MESH"
            and not core.is_tool_output(source)
        )

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        source = context.active_object
        started = time.perf_counter()
        try:
            diagnostics = core.mesh_diagnostics(source.data)
            ready = core.diagnostics_ready(diagnostics)
            settings.surface_check_source = source.name_full
            settings.surface_check_mesh_pointer = str(source.data.as_pointer())
            settings.surface_check_boundary_edges = int(diagnostics["boundary_edges"])
            settings.surface_check_components = int(diagnostics["components"])
            settings.surface_check_watertight = bool(ready)
            settings.surface_check_seconds = time.perf_counter() - started
            settings.surface_check_state = (
                "WATERTIGHT"
                if ready
                else "REPAIR"
                if settings.auto_watertight_copy
                else "BLOCKED"
            )
            self.report(
                {"INFO"},
                (
                    f"Checked {source.name}: {diagnostics['boundary_edges']} boundary edge(s), "
                    f"{diagnostics['components']} component(s) in "
                    f"{settings.surface_check_seconds:.3f}s."
                ),
            )
            return {"FINISHED"}
        except Exception as exc:
            settings.surface_check_source = source.name_full if source is not None else ""
            settings.surface_check_mesh_pointer = (
                str(source.data.as_pointer())
                if source is not None and source.type == "MESH"
                else ""
            )
            settings.surface_check_seconds = time.perf_counter() - started
            settings.surface_check_watertight = False
            settings.surface_check_state = "ERROR"
            self.report({"ERROR"}, f"Surface check failed: {exc}")
            return {"CANCELLED"}


class _VOXELIZER_OT_modal_job:
    """Shared modal runner; subclasses provide a resumable ``_job_iter``."""

    _timer = None
    _generator = None
    _batch_index = 0
    _batch_total = 1
    _completed_items = 0

    @staticmethod
    def _capture_performance(settings, source) -> None:
        diagnostics = core.sampling_diagnostics(source)
        timings = diagnostics.get("phase_timings", {})
        source_timings = diagnostics.get("source_session_timings", {})
        acquire = float(diagnostics.get("source_session_acquire_seconds", 0.0) or 0.0)
        sample_total = float(timings.get("total", 0.0) or 0.0)
        source_total = 0.0 if diagnostics.get("source_session_cache_hit") else float(
            source_timings.get("total", acquire) or acquire
        )
        occupancy = diagnostics.get("occupancy_backend", {})
        mode = str(occupancy.get("mode", "CPU_BVH"))
        if occupancy.get("used"):
            mode = "GPU + exact CPU"
        elif str(diagnostics.get("compute_backend", {}).get("used", "CPU")) == "GPU":
            mode = "GPU colour + CPU occupancy"
        settings.performance_backend = mode
        settings.performance_summary = (
            f"Source {source_total:.2f}s | Sample {sample_total:.2f}s | "
            f"{int(diagnostics.get('selected_count', 0)):,} voxels"
        )
        settings.performance_detail = (
            f"Candidates {float(timings.get('candidates', 0.0)):.2f}s | "
            f"Occupancy {float(timings.get('occupancy', 0.0)):.2f}s | "
            f"Colour {float(timings.get('colour_and_adaptive', 0.0)):.2f}s | "
            f"BVH {int(diagnostics.get('bvh_query_count', 0)):,}"
        )

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "voxelizer_settings", None)
        return settings is not None and not settings.task_running

    def _prepare(self, context):
        settings = context.scene.voxelizer_settings
        settings.task_cancel_requested = False
        settings.task_running = True
        settings.task_progress = 0.0
        settings.task_phase = "Starting"
        settings.task_message = "Preparing sources"
        self._batch_index = 0
        self._batch_total = 1
        self._completed_items = 0
        self._generator = self._job_iter(context)

    def _record_progress(self, context, progress) -> None:
        settings = context.scene.voxelizer_settings
        overall = (self._batch_index + progress.fraction) / max(1, self._batch_total)
        settings.task_progress = max(0.0, min(1.0, overall))
        settings.task_phase = progress.phase.replace("_", " ").title()
        settings.task_message = progress.message
        context.window_manager.progress_update(settings.task_progress * 100.0)
        if context.screen is not None:
            for area in context.screen.areas:
                area.tag_redraw()

    def _cleanup(self, context, *, close_generator: bool = False) -> None:
        if close_generator and self._generator is not None:
            self._generator.close()
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.progress_end()
        settings = context.scene.voxelizer_settings
        settings.task_running = False
        settings.task_cancel_requested = False
        self._generator = None

    def _failed(self, context, exc):
        self._cleanup(context, close_generator=True)
        message = str(exc) if isinstance(exc, core.VoxelizerError) else f"Chromoxel failed: {exc}"
        context.scene.voxelizer_settings.task_phase = "Error"
        context.scene.voxelizer_settings.task_message = message
        self.report({"ERROR"}, message)
        return {"CANCELLED"}

    def _cancelled(self, context):
        completed = self._completed_items
        self._cleanup(context, close_generator=True)
        settings = context.scene.voxelizer_settings
        settings.task_phase = "Cancelled"
        settings.task_message = (
            f"Cancelled after {completed} completed source(s); completed outputs were kept."
        )
        self.report({"WARNING"}, settings.task_message)
        return {"CANCELLED"}

    def execute(self, context):
        self._prepare(context)
        context.window_manager.progress_begin(0.0, 100.0)
        try:
            while True:
                progress = next(self._generator)
                self._record_progress(context, progress)
        except StopIteration as stop:
            message = str(stop.value or "Chromoxel task completed.")
            self._cleanup(context)
            settings = context.scene.voxelizer_settings
            settings.task_progress = 1.0
            settings.task_phase = "Complete"
            settings.task_message = message
            self.report({"INFO"}, message)
            return {"FINISHED"}
        except Exception as exc:
            return self._failed(context, exc)

    def invoke(self, context, _event):
        if context.window is None:
            return self.execute(context)
        self._prepare(context)
        context.window_manager.progress_begin(0.0, 100.0)
        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        settings = context.scene.voxelizer_settings
        if event.type == "ESC" or settings.task_cancel_requested:
            return self._cancelled(context)
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        try:
            # Several bounded chunks per UI tick keep small jobs snappy.
            for _step in range(8):
                progress = next(self._generator)
                self._record_progress(context, progress)
        except StopIteration as stop:
            message = str(stop.value or "Chromoxel task completed.")
            self._cleanup(context)
            settings.task_progress = 1.0
            settings.task_phase = "Complete"
            settings.task_message = message
            self.report({"INFO"}, message)
            return {"FINISHED"}
        except Exception as exc:
            return self._failed(context, exc)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self._cancelled(context)


class VOXELIZER_OT_preview(_VOXELIZER_OT_modal_job, Operator):
    bl_idname = "voxelizer.preview"
    bl_label = "Add / Update Chromoxel"
    bl_description = "Create or update non-destructive Geometry Nodes previews"
    bl_options = {"REGISTER", "UNDO"}

    def _job_iter(self, context):
        started = time.perf_counter()
        settings = context.scene.voxelizer_settings
        sources = core.source_objects(context, settings)
        self._batch_total = len(sources)
        total_points = 0
        last_update = None
        for index, source in enumerate(sources):
            self._batch_index = index
            update = yield from preview.refresh_preview_iter(
                context,
                source,
                settings,
                force_rebuild=False,
            )
            update.output.hide_render = False
            self._capture_performance(settings, source)
            total_points += update.point_count
            last_update = update
            self._completed_items += 1
        settings.live_point_count = total_points
        settings.live_build_count = last_update.build_count if last_update else 0
        settings.live_last_seconds = time.perf_counter() - started
        return (
            f"Updated {len(sources)} preview(s), {total_points:,} voxels in "
            f"{settings.live_last_seconds:.3f}s."
        )


class VOXELIZER_OT_bake(_VOXELIZER_OT_modal_job, Operator):
    bl_idname = "voxelizer.bake"
    bl_label = "Bake to Mesh"
    bl_description = "Create realized <Source>_VOX meshes with retained colours"
    bl_options = {"REGISTER", "UNDO"}

    def _job_iter(self, context):
        settings = context.scene.voxelizer_settings
        editable_sources = [
            output for output in context.selected_objects
            if editable.is_editable(output)
        ]
        if editable_sources:
            self._batch_total = len(editable_sources)
            outputs = []
            total_voxels = 0
            total_removed = 0
            skipped_reasons = []
            for index, source in enumerate(editable_sources):
                self._batch_index = index
                mode = settings.bake_mode
                name = f"{source.name}_{mode}"
                core.assert_name_available(name)
                if mode == "EDITABLE":
                    output = source.copy()
                    output.data = source.data.copy()
                    output.name = name
                    collection = source.users_collection[0] if source.users_collection else context.collection
                    collection.objects.link(output)
                    records = editable.records_from_object(output)
                    filter_stats = {
                        "input_voxels": len(records),
                        "output_voxels": len(records),
                        "removed_voxels": 0,
                        "exact": True,
                        "skip_reason": "",
                    }
                    if settings.remove_enclosed_voxels:
                        records, filter_stats = meshing.remove_enclosed_records(
                            records,
                            float(output[editable.GRID_SIZE_TAG]),
                            tuple(output[editable.GRID_ORIGIN_TAG]),
                        )
                        editable.replace_records(output, records)
                    meshing.tag_filter_stats(output.data, filter_stats)
                    count = len(records)
                else:
                    mesh, count = meshing.build_from_editable(
                        source,
                        mode,
                        f"{name}_Mesh",
                        fill_ratio=preview.display_cube_fill(settings),
                        remove_enclosed=settings.remove_enclosed_voxels,
                    )
                    output = core.link_output(
                        context,
                        source,
                        mesh,
                        name,
                        core.BAKE_KIND,
                    )
                output.matrix_world = source.matrix_world.copy()
                output.hide_render = False
                output["chromoxel_bake_mode"] = mode
                output["chromoxel_atomic_voxel_count"] = int(count)
                removed = int(output.data.get(meshing.ENCLOSED_REMOVED_TAG, 0))
                skip_reason = str(output.data.get(meshing.ENCLOSED_SKIP_TAG, ""))
                output["chromoxel_remove_enclosed_voxels"] = bool(
                    settings.remove_enclosed_voxels
                )
                output["chromoxel_enclosed_removed_voxels"] = removed
                outputs.append(output)
                total_voxels += count
                total_removed += removed
                if skip_reason:
                    skipped_reasons.append(f"{source.name}: {skip_reason}")
                self._completed_items += 1
                yield core.SamplingProgress(
                    "BAKE_GEOMETRY",
                    index + 1,
                    len(editable_sources),
                    f"Built {mode.title()} output for {source.name}",
                )
            for selected in tuple(context.selected_objects):
                selected.select_set(False)
            for output in outputs:
                output.select_set(True)
            if outputs:
                context.view_layer.objects.active = outputs[-1]
            summary = (
                f"Built {len(outputs)} {settings.bake_mode.lower()} output(s), "
                f"{total_voxels:,} atomic voxels; removed {total_removed:,} enclosed."
            )
            if skipped_reasons:
                summary += " Filter skipped: " + "; ".join(skipped_reasons)
            return summary

        sources = core.source_objects(context, settings)
        self._batch_total = len(sources)
        for source in sources:
            core.assert_name_available(core.bake_name(source))
        outputs = []
        total_voxels = 0
        total_removed = 0
        skipped_reasons = []
        image_sources = 0
        for index, source in enumerate(sources):
            self._batch_index = index
            name = core.bake_name(source)
            cache_key = core.preview_sampling_key(context, source, settings)
            mesh, count, used_image = yield from core.build_voxel_mesh_iter(
                context,
                source,
                settings,
                f"{name}_Mesh",
                cache_key=cache_key,
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
            self._capture_performance(settings, source)
            removed = int(mesh.get(meshing.ENCLOSED_REMOVED_TAG, 0))
            skip_reason = str(mesh.get(meshing.ENCLOSED_SKIP_TAG, ""))
            output["chromoxel_remove_enclosed_voxels"] = bool(
                settings.remove_enclosed_voxels
            )
            output["chromoxel_enclosed_removed_voxels"] = removed
            outputs.append(output)
            total_voxels += count
            total_removed += removed
            if skip_reason:
                skipped_reasons.append(f"{source.name}: {skip_reason}")
            image_sources += int(used_image)
            self._completed_items += 1
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        for output in outputs:
            output.select_set(True)
        if outputs:
            context.view_layer.objects.active = outputs[-1]
        summary = (
            f"Baked {len(outputs)} mesh(es), {total_voxels:,} voxels; "
            f"removed {total_removed:,} enclosed; "
            f"{image_sources} source(s) used image/UV colour."
        )
        if skipped_reasons:
            summary += " Filter skipped: " + "; ".join(skipped_reasons)
        return summary


class VOXELIZER_OT_cancel_job(Operator):
    bl_idname = "voxelizer.cancel_job"
    bl_label = "Cancel Chromoxel Task"
    bl_description = "Request cancellation at the next bounded work chunk"

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "voxelizer_settings", None)
        return settings is not None and settings.task_running

    def execute(self, context):
        context.scene.voxelizer_settings.task_cancel_requested = True
        return {"FINISHED"}


class VOXELIZER_OT_clear_cache(Operator):
    bl_idname = "voxelizer.clear_cache"
    bl_label = "Clear Sampling Cache"
    bl_description = "Free cached voxel centres and colours without deleting outputs"

    def execute(self, _context):
        stats = core.sampling_cache_stats()
        core.clear_sampling_cache()
        self.report(
            {"INFO"},
            f"Cleared {stats['entries']} cache entr{'y' if stats['entries'] == 1 else 'ies'}.",
        )
        return {"FINISHED"}


class VOXELIZER_OT_clear(Operator):
    bl_idname = "voxelizer.clear"
    bl_label = "Clear Outputs"
    bl_description = "Delete only objects tagged as Chromoxel outputs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "voxelizer_settings", None)
        return settings is not None and not settings.task_running

    def execute(self, context):
        live.cancel_pending(context.scene.voxelizer_settings, stop_running=True)
        preview.clear_runtime_cache()
        count = core.clear_tagged_outputs()
        self.report({"INFO"}, f"Cleared {count} tagged Chromoxel output(s).")
        return {"FINISHED"}


class VOXELIZER_OT_live_toggle(Operator):
    bl_idname = "voxelizer.live_toggle"
    bl_label = "Start / Stop Live"
    bl_description = "Start watching the active source, or stop the live session"

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        if settings.live_running:
            live.stop(settings)
            return {"FINISHED"}
        if settings.task_running:
            self.report({"WARNING"}, "Wait for the current Chromoxel task to finish.")
            return {"CANCELLED"}
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
        if settings.source_scope != "ACTIVE":
            self.report({"INFO"}, "Live watches the active source; batch scope remains manual.")
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
        source = context.active_object
        tr = lambda english, chinese: editor.translated(context, english, chinese)

        def enum_buttons(owner, property_name, choices):
            row = owner.row(align=True)
            for value, english, chinese in choices:
                operator = row.operator(
                    "wm.context_set_enum",
                    text=tr(english, chinese),
                    depress=getattr(settings, property_name) == value,
                )
                operator.data_path = f"scene.voxelizer_settings.{property_name}"
                operator.value = value

        def step_box(property_name, english, chinese, icon):
            box = layout.box()
            box.prop(
                settings,
                property_name,
                text=tr(english, chinese),
                icon="TRIA_DOWN" if getattr(settings, property_name) else "TRIA_RIGHT",
                emboss=False,
            )
            return box if getattr(settings, property_name) else None

        # Always keep language, output mode, and the two primary actions above
        # the numbered workflow. No source inspection is performed here.
        quick_box = layout.box()
        quick_box.label(text=tr("Quick Start", "快速开始"), icon="PLAY")
        quick_box.prop(settings, "ui_language", text=tr("Language", "语言"))
        quick_box.label(text=tr("Bake Output", "烘焙输出"), icon="MESH_CUBE")
        enum_buttons(quick_box, "bake_mode", (
            ("EDITABLE", "Editable", "可编辑点"),
            ("REALIZED", "Cubes", "实体方块"),
            ("SURFACE", "Surface", "表面网格"),
            ("GREEDY", "Greedy", "贪心网格"),
        ))
        quick_actions = quick_box.row(align=True)
        quick_actions.enabled = not settings.task_running
        quick_actions.scale_y = 1.35
        quick_actions.operator(
            VOXELIZER_OT_preview.bl_idname,
            text=tr("Create Preview", "创建预览"),
            icon="MOD_NODES",
        )
        quick_actions.operator(
            VOXELIZER_OT_bake.bl_idname,
            text=tr("Start Bake", "开始烘焙"),
            icon="MESH_CUBE",
        )

        if settings.task_running:
            quick_box.label(text=settings.task_phase, icon="TIME")
            if hasattr(quick_box, "progress"):
                quick_box.progress(
                    factor=settings.task_progress,
                    type="BAR",
                    text=f"{settings.task_progress * 100.0:.0f}%",
                )
            else:
                row = quick_box.row()
                row.enabled = False
                row.prop(settings, "task_progress", slider=True, text="")
            quick_box.label(text=settings.task_message)
            quick_box.operator(
                VOXELIZER_OT_cancel_job.bl_idname,
                text=tr("Cancel Task", "取消任务"),
                icon="CANCEL",
            )
        elif settings.task_message:
            quick_box.label(text=settings.task_message, icon="CHECKMARK")

        source_box = step_box(
            "show_step_source", "1. Select Source", "1. 选择源模型", "OUTLINER_COLLECTION"
        )
        if source_box is not None:
            enum_buttons(source_box, "source_scope", (
                ("ACTIVE", "Active", "活动对象"),
                ("SELECTED", "Selected", "已选对象"),
                ("COLLECTION", "Collection", "集合"),
            ))
            if settings.source_scope == "COLLECTION":
                source_box.prop(
                    settings,
                    "source_collection",
                    text=tr("Source Collection", "源集合"),
                )
                source_box.prop(
                    settings,
                    "include_hidden",
                    text=tr("Include Hidden", "包含隐藏对象"),
                )
            source_box.label(
                text=tr(
                    "Select the original Mesh object(s) to process.",
                    "选择要处理的原始 Mesh 对象。",
                ),
                icon="INFO",
            )

        quality_box = step_box(
            "show_step_grid", "2. Set Voxel Grid", "2. 设置体素网格", "MOD_REMESH"
        )
        if quality_box is not None:
            row = quality_box.row(align=True)
            for identifier, english, chinese in (
                ("COARSE", "Coarse", "粗略"),
                ("MEDIUM", "Medium", "中等"),
                ("FINE", "Fine", "精细"),
            ):
                operator = row.operator(
                    VOXELIZER_OT_quality_preset.bl_idname,
                    text=tr(english, chinese),
                    depress=settings.quality_preset == identifier,
                )
                operator.preset = identifier
            quality_box.prop(settings, "voxel_size", text=tr("Voxel Size", "体素尺寸"))
            enum_buttons(quality_box, "sampling_mode", (
                ("UNIFORM", "Uniform", "统一"),
                ("ADAPTIVE", "Adaptive", "自适应"),
            ))
            if settings.sampling_mode == "ADAPTIVE":
                quality_box.prop(
                    settings,
                    "adaptive_max_level",
                    text=tr("Max Detail Level", "最大细节等级"),
                )
                smallest = settings.voxel_size / (2 ** settings.adaptive_max_level)
                quality_box.label(
                    text=tr(
                        f"Automatic minimum size: {smallest:.4g} BU",
                        f"自动最小尺寸：{smallest:.4g} BU",
                    )
                )
            quality_box.prop(settings, "cube_gap", text=tr("Cube Gap", "体素间隙"))
            quality_box.label(text=tr("Grid Origin", "网格原点"))
            enum_buttons(quality_box, "grid_origin_mode", (
                ("OBJECT", "Object", "对象原点"),
                ("CUSTOM", "Custom", "自定义"),
                ("BOUNDS", "Bounds", "边界"),
            ))
            if settings.grid_origin_mode == "CUSTOM":
                quality_box.prop(
                    settings,
                    "grid_origin",
                    text=tr("Custom Origin", "自定义原点"),
                )
            quality_box.operator(
                VOXELIZER_OT_estimate.bl_idname,
                text=tr("Estimate Work", "估算工作量"),
                icon="INFO",
            )
            quality_box.label(
                text=settings.estimate_summary,
                icon="CHECKMARK" if settings.estimate_ok else "ERROR",
            )
            if settings.estimate_detail:
                quality_box.label(text=settings.estimate_detail)

        repair_box = step_box(
            "show_step_surface", "3. Validate Surface", "3. 检查表面", "MESH_DATA"
        )
        if repair_box is not None:
            repair_box.prop(
                settings,
                "auto_watertight_copy",
                text=tr("Auto Watertight Copy", "自动闭合副本"),
            )
            if settings.auto_watertight_copy:
                repair_box.prop(
                    settings,
                    "repair_voxel_size",
                    text=tr("Repair Voxel Size", "修复体素尺寸"),
                )
            if source is not None and source.type == "MESH" and not core.is_tool_output(source):
                checked = (
                    settings.surface_check_state != "UNCHECKED"
                    and settings.surface_check_source == source.name_full
                    and settings.surface_check_mesh_pointer == str(source.data.as_pointer())
                )
                repair_box.operator(
                    VOXELIZER_OT_check_surface.bl_idname,
                    text=tr("Check Surface", "检查表面"),
                    icon="VIEWZOOM",
                )
                if not checked:
                    repair_box.label(text=tr("Surface not checked", "尚未检查表面"), icon="INFO")
                elif settings.surface_check_state == "ERROR":
                    repair_box.label(text=tr("Surface check failed", "表面检查失败"), icon="ERROR")
                elif settings.surface_check_watertight:
                    repair_box.label(
                        text=tr("Active source is watertight", "活动源模型已闭合"),
                        icon="CHECKMARK",
                    )
                elif settings.auto_watertight_copy:
                    repair_box.label(
                        text=tr("Private repair copy will be used", "将使用私有修复副本"),
                        icon="MOD_REMESH",
                    )
                else:
                    repair_box.label(
                        text=tr("Non-manifold source is blocked", "非流形源模型已被阻止"),
                        icon="ERROR",
                    )
                if checked:
                    repair_box.label(
                        text=tr(
                            f"Boundary {settings.surface_check_boundary_edges} | "
                            f"Components {settings.surface_check_components} | "
                            f"{settings.surface_check_seconds:.3f}s",
                            f"边界 {settings.surface_check_boundary_edges} | "
                            f"连通块 {settings.surface_check_components} | "
                            f"{settings.surface_check_seconds:.3f}s",
                        )
                    )
            else:
                repair_box.label(
                    text=tr("Select an original Mesh source", "请选择原始 Mesh 源对象"),
                    icon="INFO",
                )

        colour_box = step_box(
            "show_step_colour", "4. Set Colour", "4. 设置颜色", "IMAGE_DATA"
        )
        if colour_box is not None:
            colour_box.prop(
                settings,
                "auto_material_images",
                text=tr("Auto Material Images", "自动查找材质贴图"),
            )
            if source is not None and source.type == "MESH":
                colour_box.prop_search(
                    settings,
                    "uv_map",
                    source.data,
                    "uv_layers",
                    text=tr("UV Map", "UV 映射"),
                )
            else:
                colour_box.prop(settings, "uv_map", text=tr("UV Map", "UV 映射"))
            colour_box.prop(
                settings,
                "base_color_image",
                text=tr("Image Override", "覆盖贴图"),
            )
            colour_box.label(text=tr("Texture Filter", "纹理过滤"))
            enum_buttons(colour_box, "texture_filter", (
                ("BILINEAR", "Bilinear", "双线性"),
                ("NEAREST", "Nearest", "最近点"),
            ))
            colour_box.prop(
                settings,
                "fallback_color",
                text=tr("Fallback Color", "备用颜色"),
            )

        preview_box = step_box(
            "show_step_preview", "5. Create Preview", "5. 创建预览", "MOD_NODES"
        )
        if preview_box is not None:
            preview_actions = preview_box.column(align=True)
            preview_actions.enabled = not settings.task_running
            preview_actions.operator(
                VOXELIZER_OT_preview.bl_idname,
                text=tr("Create / Update Preview", "创建 / 更新预览"),
                icon="MOD_NODES",
            )
            preview_box.label(
                text=tr(
                    "Preview remains editable through Geometry Nodes.",
                    "预览通过 Geometry Nodes 保持可编辑。",
                ),
                icon="INFO",
            )

        bake_box = step_box(
            "show_step_bake", "6. Bake Output", "6. 烘焙输出", "MESH_CUBE"
        )
        if bake_box is not None:
            enum_buttons(bake_box, "bake_mode", (
                ("EDITABLE", "Editable", "可编辑点"),
                ("REALIZED", "Cubes", "实体方块"),
                ("SURFACE", "Surface", "表面网格"),
                ("GREEDY", "Greedy", "贪心网格"),
            ))
            bake_box.prop(
                settings,
                "remove_enclosed_voxels",
                text=tr("Remove Enclosed Voxels", "移除封闭内部体素"),
            )
            bake_actions = bake_box.column(align=True)
            bake_actions.enabled = not settings.task_running
            bake_actions.operator(
                VOXELIZER_OT_bake.bl_idname,
                text=tr("Start Bake", "开始烘焙"),
                icon="MESH_CUBE",
            )
            bake_actions.operator(
                VOXELIZER_OT_clear.bl_idname,
                text=tr("Clear Outputs", "清除输出"),
                icon="TRASH",
            )

        edit_box = step_box(
            "show_step_edit", "7. Edit & Export", "7. 编辑与导出", "EDITMODE_HLT"
        )
        if edit_box is not None:
            editable_source = editable.is_editable(source)
            voxel_edit_box = edit_box.box()
            voxel_edit_box.label(text=tr("Voxel Edit", "体素编辑"), icon="EDITMODE_HLT")
            if editable_source:
                diagnostics = editable.validate_editable(source)
                voxel_edit_box.label(
                    text=tr(
                        f"{diagnostics['voxels']:,} voxels | "
                        f"{diagnostics['chunks']:,} chunks | "
                        f"grid {diagnostics['grid_size']:.4g} BU",
                        f"{diagnostics['voxels']:,} 体素 | "
                        f"{diagnostics['chunks']:,} 分块 | "
                        f"网格 {diagnostics['grid_size']:.4g} BU",
                    ),
                    icon=(
                        "CHECKMARK"
                        if diagnostics["duplicate_coordinates"] == 0
                        and diagnostics["within_model_limit"]
                        else "ERROR"
                    ),
                )
                if not diagnostics["within_model_limit"]:
                    voxel_edit_box.label(
                        text=tr(
                            "Over 100,000 points: split into multiple models",
                            "超过 100,000 点：请拆分为多个模型",
                        ),
                        icon="ERROR",
                    )
                row = voxel_edit_box.row(align=True)
                row.operator(
                    editor.VOXELIZER_OT_enter_edit.bl_idname,
                    text=tr("Enter Edit", "进入编辑"),
                    icon="EDITMODE_HLT",
                )
                row.operator(
                    editor.VOXELIZER_OT_exit_edit.bl_idname,
                    text=tr("Exit Edit", "退出编辑"),
                    icon="OBJECT_DATAMODE",
                )
                voxel_edit_box.operator(
                    editor.VOXELIZER_OT_revoxelize_edits.bl_idname,
                    text=tr("Re-voxelize + Replay Edits", "重新体素化并重放编辑"),
                    icon="FILE_REFRESH",
                )
                row = voxel_edit_box.row(align=True)
                for action, english, chinese in (
                    ("ALL", "All", "全选"),
                    ("NONE", "None", "取消"),
                    ("INVERT", "Invert", "反选"),
                ):
                    operator = row.operator(
                        editor.VOXELIZER_OT_select.bl_idname,
                        text=tr(english, chinese),
                    )
                    operator.action = action
                voxel_edit_box.operator(
                    editor.VOXELIZER_OT_box_select.bl_idname,
                    text=tr("Box Select", "框选"),
                    icon="BORDER_RECT",
                )
                row = voxel_edit_box.row(align=True)
                row.operator(
                    editor.VOXELIZER_OT_add_cursor.bl_idname,
                    text=tr("Add", "添加"),
                    icon="ADD",
                )
                row.operator(
                    editor.VOXELIZER_OT_delete_selected.bl_idname,
                    text=tr("Delete", "删除"),
                    icon="REMOVE",
                )
                move_grid = voxel_edit_box.grid_flow(columns=3, align=True)
                for delta, label in (
                    ((-1, 0, 0), "-X"), ((1, 0, 0), "+X"),
                    ((0, -1, 0), "-Y"), ((0, 1, 0), "+Y"),
                    ((0, 0, -1), "-Z"), ((0, 0, 1), "+Z"),
                ):
                    operator = move_grid.operator(
                        editor.VOXELIZER_OT_move_selected.bl_idname,
                        text=label,
                    )
                    operator.delta = delta
                row = voxel_edit_box.row(align=True)
                row.operator(
                    editor.VOXELIZER_OT_pick_selected.bl_idname,
                    text=tr("Pick", "吸色"),
                    icon="EYEDROPPER",
                )
                row.operator(
                    editor.VOXELIZER_OT_paint_selected.bl_idname,
                    text=tr("Paint", "上色"),
                    icon="BRUSH_DATA",
                )
                row.operator(
                    editor.VOXELIZER_OT_flood_fill.bl_idname,
                    text=tr("Fill", "填充"),
                    icon="UV_SYNC_SELECT",
                )
                select_grid = voxel_edit_box.grid_flow(columns=2, align=True)
                for mode, english, chinese in (
                    ("COLOR", "Same Color", "同颜色"),
                    ("MATERIAL", "Same Material", "同材质"),
                    ("LEVEL", "Same Level", "同等级"),
                    ("CONNECTED", "Connected", "连通区域"),
                    ("COLOR_CONNECTED", "Color Region", "颜色区域"),
                ):
                    operator = select_grid.operator(
                        editor.VOXELIZER_OT_select_similar.bl_idname,
                        text=tr(english, chinese),
                    )
                    operator.mode = mode
                row = voxel_edit_box.row(align=True)
                for axis in "XYZ":
                    operator = row.operator(
                        editor.VOXELIZER_OT_mirror_selected.bl_idname,
                        text=tr(f"Mirror {axis}", f"镜像 {axis}"),
                    )
                    operator.axis = axis
                row = voxel_edit_box.row(align=True)
                row.operator(
                    editor.VOXELIZER_OT_copy_voxels.bl_idname,
                    text=tr("Copy", "复制"),
                    icon="COPYDOWN",
                )
                row.operator(
                    editor.VOXELIZER_OT_paste_voxels.bl_idname,
                    text=tr("Paste", "粘贴"),
                    icon="PASTEDOWN",
                )
            else:
                voxel_edit_box.label(
                    text=tr(
                        "Create or select a Chromoxel Preview",
                        "请创建或选择 Chromoxel 预览",
                    ),
                    icon="INFO",
                )

            material_box = edit_box.box()
            material_box.label(
                text=tr("Voxel Color & Material", "体素颜色与材质"),
                icon="MATERIAL",
            )
            enum_buttons(material_box, "color_mode", (
                ("DIRECT", "Direct", "直接颜色"),
                ("PALETTE", "Palette", "调色板"),
            ))
            if editable_source:
                material_box.operator(
                    editor.VOXELIZER_OT_palette_generate.bl_idname,
                    text=tr("Generate Palette", "生成调色板"),
                    icon="COLOR",
                )
            if settings.color_mode == "DIRECT":
                material_box.prop(settings, "edit_color", text=tr("Edit Color", "编辑颜色"))
                material_box.prop(settings, "edit_material_id", text=tr("Material ID", "材质 ID"))
                material_box.prop(settings, "edit_roughness", text=tr("Roughness", "粗糙度"))
                material_box.prop(settings, "edit_metallic", text=tr("Metallic", "金属度"))
                material_box.prop(settings, "edit_emission", text=tr("Emission", "自发光"))
            else:
                material_box.template_list(
                    "UI_UL_list", "chromoxel_palette", settings, "palette_slots",
                    settings, "palette_active_index", rows=3,
                )
                row = material_box.row(align=True)
                row.operator(editor.VOXELIZER_OT_palette_add.bl_idname, icon="ADD", text="")
                row.operator(editor.VOXELIZER_OT_palette_remove.bl_idname, icon="REMOVE", text="")
                if settings.palette_slots:
                    palette_index = min(
                        settings.palette_active_index,
                        len(settings.palette_slots) - 1,
                    )
                    slot = settings.palette_slots[palette_index]
                    material_box.prop(slot, "name", text=tr("Name", "名称"))
                    material_box.prop(slot, "color", text=tr("Color", "颜色"))
                    material_box.prop(slot, "roughness", text=tr("Roughness", "粗糙度"))
                    material_box.prop(slot, "metallic", text=tr("Metallic", "金属度"))
                    material_box.prop(slot, "emission", text=tr("Emission", "自发光"))
                    material_box.operator(
                        editor.VOXELIZER_OT_palette_update_linked.bl_idname,
                        text=tr("Update Linked Voxels", "更新关联体素"),
                    )

            vox_box = edit_box.box()
            vox_box.label(text="MagicaVoxel .vox", icon="FILE_3D")
            vox_box.prop(
                settings,
                "vox_import_size",
                text=tr("VOX Unit Size", ".vox 单位尺寸"),
            )
            row = vox_box.row(align=True)
            row.operator(
                vox_io.VOXELIZER_OT_import_vox.bl_idname,
                text=tr("Import .vox", "导入 .vox"),
                icon="IMPORT",
            )
            export_row = row.row(align=True)
            export_row.enabled = editable_source
            export_row.operator(
                vox_io.VOXELIZER_OT_export_vox.bl_idname,
                text=tr("Export .vox", "导出 .vox"),
                icon="EXPORT",
            )

        live_box = step_box(
            "show_step_live", "8. Live Preview", "8. 实时预览", "FILE_REFRESH"
        )
        if live_box is not None:
            live_box.prop(settings, "live_update", text=tr("Live Update", "实时更新"))
            live_box.prop(settings, "live_debounce", text=tr("Debounce", "防抖延迟"))
            live_box.operator(
                VOXELIZER_OT_live_toggle.bl_idname,
                text=(
                    tr("Stop Live", "停止实时预览")
                    if settings.live_running
                    else tr("Start Live", "启动实时预览")
                ),
                icon="PAUSE" if settings.live_running else "PLAY",
            )
            live_box.label(text=tr(f"Status: {settings.live_status}", f"状态：{settings.live_status}"))
            live_box.label(
                text=tr(
                    f"Points {settings.live_point_count:,} | "
                    f"Builds {settings.live_build_count:,} | "
                    f"{settings.live_last_seconds:.3f}s",
                    f"点 {settings.live_point_count:,} | "
                    f"更新 {settings.live_build_count:,} | "
                    f"{settings.live_last_seconds:.3f}s",
                )
            )

        advanced_box = layout.box()
        advanced_box.prop(
            settings,
            "show_advanced",
            text=tr("Advanced", "高级设置"),
            icon="TRIA_DOWN" if settings.show_advanced else "TRIA_RIGHT",
            emboss=False,
        )
        if settings.show_advanced:
            if settings.sampling_mode == "ADAPTIVE":
                advanced_box.prop(
                    settings,
                    "adaptive_texture_threshold",
                    text=tr("Texture Error", "纹理误差"),
                )
                advanced_box.prop(
                    settings,
                    "adaptive_geometry_angle",
                    text=tr("Geometry Angle", "几何角度"),
                )
                advanced_box.prop(
                    settings,
                    "adaptive_geometry_max_level",
                    text=tr("Geometry Detail Level", "几何细节等级"),
                )
            advanced_box.prop(
                settings,
                "use_sparse_candidates",
                text=tr("Sparse Surface Candidates", "稀疏表面候选"),
            )
            if settings.use_sparse_candidates:
                advanced_box.prop(
                    settings,
                    "sparse_grid_threshold",
                    text=tr("Sparse Grid Threshold", "稀疏网格阈值"),
                )
            advanced_box.prop(settings, "sample_budget", text=tr("Candidate Limit", "候选上限"))
            advanced_box.prop(
                settings,
                "candidate_expansion_budget",
                text=tr("Expansion Limit", "展开上限"),
            )
            advanced_box.prop(settings, "voxel_budget", text=tr("Voxel Limit", "体素上限"))
            advanced_box.prop(
                settings,
                "sampling_chunk_size",
                text=tr("Task Chunk", "任务分块"),
            )
            advanced_box.prop(
                settings,
                "cache_memory_mb",
                text=tr("Cache Memory", "缓存内存"),
            )
            enum_buttons(advanced_box, "compute_backend", (
                ("AUTO", "Auto", "自动"),
                ("GPU", "GPU", "GPU"),
                ("CPU", "CPU", "CPU"),
            ))
            if settings.compute_backend != "CPU":
                advanced_box.prop(
                    settings,
                    "gpu_batch_size",
                    text=tr("GPU Batch Size", "GPU 批次大小"),
                )
                advanced_box.prop(
                    settings,
                    "gpu_memory_limit_mb",
                    text=tr("GPU Memory Limit (MiB)", "GPU 显存上限 (MiB)"),
                )
                decision = gpu_backend.resolve_backend(settings.compute_backend)
                advanced_box.label(
                    text=(
                        f"{decision.used}: {decision.backend or decision.reason}"
                        + (f" / {decision.device}" if decision.device else "")
                    ),
                    icon="RENDER_RESULT" if decision.used == "GPU" else "INFO",
                )
            row = advanced_box.row(align=True)
            row.operator(
                VOXELIZER_OT_clear_cache.bl_idname,
                text=tr("Clear Sampling Cache", "清除采样缓存"),
                icon="X",
            )
            stats = core.sampling_cache_stats()
            row.label(text=f"{stats['entries']} | {stats['bytes'] / (1024 * 1024):.1f} MiB")
            advanced_box.label(
                text=tr(
                    f"Prepared sources: {stats['session_entries']}",
                    f"已准备源：{stats['session_entries']}",
                ),
                icon="MESH_DATA",
            )
            profile_box = advanced_box.box()
            profile_box.label(text=tr("Last voxelization", "上次体素化"), icon="TIME")
            profile_box.label(text=settings.performance_summary)
            if settings.performance_detail:
                profile_box.label(text=settings.performance_detail)
            if settings.performance_backend:
                profile_box.label(
                    text=tr(
                        f"Backend: {settings.performance_backend}",
                        f"后端：{settings.performance_backend}",
                    )
                )


CLASSES = (
    editor.VOXELIZER_PG_palette_slot,
    VOXELIZER_PG_settings,
    VOXELIZER_OT_quality_preset,
    VOXELIZER_OT_estimate,
    VOXELIZER_OT_check_surface,
    VOXELIZER_OT_preview,
    VOXELIZER_OT_bake,
    VOXELIZER_OT_cancel_job,
    VOXELIZER_OT_clear_cache,
    VOXELIZER_OT_clear,
    VOXELIZER_OT_live_toggle,
    *editor.CLASSES[1:],
    *vox_io.CLASSES,
    VOXELIZER_PT_panel,
)


def register():
    i18n.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.voxelizer_settings = PointerProperty(type=VOXELIZER_PG_settings)
    bpy.types.Scene.voxelizer_clipboard = StringProperty(
        name="Chromoxel Clipboard",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    live.register_handlers()


def unregister():
    live.unregister_handlers()
    preview.clear_runtime_cache()
    if hasattr(bpy.types.Scene, "voxelizer_settings"):
        del bpy.types.Scene.voxelizer_settings
    if hasattr(bpy.types.Scene, "voxelizer_clipboard"):
        del bpy.types.Scene.voxelizer_clipboard
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    i18n.unregister()


if __name__ == "__main__":
    register()
