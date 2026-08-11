"""Lightweight live-update runtime for Textured Voxelizer previews."""

from __future__ import annotations

import time

import bpy
from bpy.app.handlers import persistent


_generation = 0
_pending_source_name = ""
_pending_kind = ""
_rebuilding = False
_status = "Idle"
_last_event_at = 0.0
_load_suppressed = False
_registered_timers = set()


def _settings(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    return getattr(scene, "voxelizer_settings", None) if scene else None


def _set_status(settings, text: str) -> None:
    global _status
    _status = text
    if settings is not None and hasattr(settings, "live_status"):
        settings.live_status = text


def _is_tool_owned(obj) -> bool:
    if obj is None:
        return True
    try:
        from . import core

        return core.is_tool_output(obj)
    except (AttributeError, TypeError, ReferenceError):
        return True


def _same_blender_id(a, b) -> bool:
    if a is b:
        return True
    if a is None or b is None:
        return False
    try:
        a_original = getattr(a, "original", None) or a
        b_original = getattr(b, "original", None) or b
        return a_original.as_pointer() == b_original.as_pointer()
    except (AttributeError, ReferenceError):
        return a == b


def _configured_source(settings):
    if settings is None:
        return None
    return getattr(settings, "live_source", None)


def _clear_surface_check(settings) -> None:
    """Invalidate cached UI-only diagnostics without touching mesh data."""

    if settings is None or not hasattr(settings, "surface_check_state"):
        return
    settings.surface_check_state = "UNCHECKED"
    settings.surface_check_source = ""
    settings.surface_check_mesh_pointer = ""
    settings.surface_check_boundary_edges = 0
    settings.surface_check_components = 0
    settings.surface_check_watertight = False
    settings.surface_check_seconds = 0.0


def _invalidate_surface_check_from_updates(settings, depsgraph) -> None:
    source_name = str(getattr(settings, "surface_check_source", ""))
    if not source_name:
        return
    source = bpy.data.objects.get(source_name)
    if source is None or source.type != "MESH":
        _clear_surface_check(settings)
        return
    source_data = source.data
    for update in depsgraph.updates:
        updated = getattr(update, "id", None)
        if not _same_blender_id(updated, source) and not _same_blender_id(updated, source_data):
            continue
        if getattr(update, "is_updated_geometry", False) or _same_blender_id(updated, source_data):
            _clear_surface_check(settings)
            return


def _record_runtime_id_updates(depsgraph) -> None:
    """Feed cheap preview-key revisions from Blender's own update stream."""

    try:
        from . import core
    except ImportError:
        return
    for update in depsgraph.updates:
        updated = getattr(update, "id", None)
        try:
            original = getattr(updated, "original", None) or updated
            is_colour_id = isinstance(
                original,
                (bpy.types.Material, bpy.types.Image, bpy.types.NodeTree),
            )
            is_mesh_id = isinstance(original, bpy.types.Mesh)
            geometry_changed = bool(getattr(update, "is_updated_geometry", False))
            if geometry_changed or is_colour_id or is_mesh_id:
                core.mark_runtime_id_updated(updated)
            if geometry_changed and isinstance(original, bpy.types.Object):
                core.mark_runtime_id_updated(getattr(original, "data", None))
        except (AttributeError, ReferenceError, TypeError):
            continue


def _preview_exists(source) -> bool:
    if source is None:
        return False
    try:
        from . import preview

        from . import core

        output = bpy.data.objects.get(core.preview_name(source))
        return (
            output is not None
            and core.is_tool_output(output, core.PREVIEW_KIND)
            and output.get(core.SOURCE_TAG) == source.name
        )
    except Exception:
        return False


def _refresh(settings, source, kind: str) -> bool:
    from . import preview

    refresh = getattr(preview, "refresh_preview", None)
    if not callable(refresh):
        return False
    result = refresh(
        bpy.context,
        source,
        settings,
        force_rebuild=kind == "GEOMETRY",
    )
    settings.live_last_seconds = result.elapsed_seconds
    settings.live_point_count = result.point_count
    settings.live_build_count = result.build_count
    return True


def _timer_callback(token: int):
    def callback():
        global _pending_kind, _pending_source_name, _rebuilding
        keep_registered = False
        try:
            settings = _settings()
            if token != _generation:
                return None
            if _load_suppressed or _rebuilding or settings is None:
                return None
            if not getattr(settings, "live_update", False) or not getattr(settings, "live_running", False):
                return None
            source = bpy.data.objects.get(_pending_source_name)
            if source is None or source != _configured_source(settings) or not _preview_exists(source):
                _set_status(settings, "Idle")
                return None
            remaining = max(
                0.05,
                min(2.0, float(getattr(settings, "live_debounce", 0.25))),
            ) - (time.monotonic() - _last_event_at)
            if remaining > 0.0:
                keep_registered = True
                return remaining
            kind = _pending_kind
            _pending_kind = ""
            _pending_source_name = ""
            _rebuilding = True
            started = time.perf_counter()
            try:
                _set_status(settings, "Rebuilding")
                if _refresh(settings, source, kind):
                    if hasattr(settings, "live_last_seconds"):
                        settings.live_last_seconds = max(
                            0.0,
                            time.perf_counter() - started,
                        )
                    _set_status(settings, "Idle")
                else:
                    _set_status(settings, "Idle")
            except Exception:
                _set_status(settings, "Error")
            finally:
                _rebuilding = False
            return None
        finally:
            if not keep_registered:
                _registered_timers.discard(callback)

    return callback


def queue_update(source, kind: str) -> None:
    global _generation, _pending_kind, _pending_source_name, _last_event_at
    settings = _settings()
    if (
        _load_suppressed
        or _rebuilding
        or settings is None
        or not getattr(settings, "live_update", False)
        or not getattr(settings, "live_running", False)
        or source is None
        or source != _configured_source(settings)
        or _is_tool_owned(source)
    ):
        return
    _generation += 1
    token = _generation
    _pending_source_name = source.name
    _pending_kind = kind
    _last_event_at = time.monotonic()
    _set_status(settings, "Pending")
    callback = _timer_callback(token)
    _registered_timers.add(callback)
    try:
        bpy.app.timers.register(callback, first_interval=max(
            0.05, min(2.0, float(getattr(settings, "live_debounce", 0.25)))
        ))
    except Exception:
        _registered_timers.discard(callback)
        raise


def settings_changed(settings, context, kind: str) -> None:
    if (
        _load_suppressed
        or _rebuilding
        or settings is None
        or context is None
        or not getattr(settings, "live_update", False)
        or not getattr(settings, "live_running", False)
    ):
        return
    source = _configured_source(settings)
    if source is None or _is_tool_owned(source) or not _preview_exists(source):
        return
    if kind == "DISPLAY":
        try:
            if _refresh(settings, source, "DISPLAY"):
                _set_status(settings, "Display")
        except Exception:
            _set_status(settings, "Error")
        return
    if kind == "GEOMETRY":
        queue_update(source, "GEOMETRY")


@persistent
def depsgraph_update_post(scene, depsgraph) -> None:
    _record_runtime_id_updates(depsgraph)
    settings = _settings(scene)
    if settings is not None:
        _invalidate_surface_check_from_updates(settings, depsgraph)
    if (
        _load_suppressed
        or _rebuilding
        or settings is None
        or not getattr(settings, "live_update", False)
        or not getattr(settings, "live_running", False)
    ):
        return
    source = _configured_source(settings)
    if source is None or _is_tool_owned(source):
        return
    source_data = getattr(source, "data", None)
    for update in depsgraph.updates:
        updated = getattr(update, "id", None)
        if not _same_blender_id(updated, source) and not _same_blender_id(updated, source_data):
            continue
        if getattr(update, "is_updated_geometry", False) or _same_blender_id(updated, source_data):
            queue_update(source, "GEOMETRY")
            return
        if getattr(update, "is_updated_transform", False):
            try:
                if _preview_exists(source) and _refresh(settings, source, "TRANSFORM"):
                    _set_status(settings, "Transform")
                else:
                    queue_update(source, "TRANSFORM")
            except Exception:
                _set_status(settings, "Error")
            return


@persistent
def load_post(_dummy) -> None:
    global _load_suppressed
    _load_suppressed = True
    settings = _settings()
    cancel_pending(settings, stop_running=True)
    _clear_surface_check(settings)
    try:
        from . import preview
        from . import core

        preview.clear_runtime_cache()
        core.clear_runtime_id_revisions()
    except (AttributeError, ImportError):
        pass
    _load_suppressed = False


def start(settings=None) -> None:
    settings = settings or _settings()
    if settings is not None:
        settings.live_running = True
    _set_status(settings, "Idle")


def cancel_pending(settings=None, *, stop_running: bool = False) -> None:
    global _generation, _pending_kind, _pending_source_name, _rebuilding
    _generation += 1
    _pending_kind = ""
    _pending_source_name = ""
    _rebuilding = False
    for callback in tuple(_registered_timers):
        try:
            if bpy.app.timers.is_registered(callback):
                bpy.app.timers.unregister(callback)
        except (ReferenceError, RuntimeError, ValueError):
            pass
        _registered_timers.discard(callback)
    settings = settings or _settings()
    if settings is not None and stop_running:
        settings.live_running = False
    _set_status(settings, "Idle")


def stop(settings=None) -> None:
    cancel_pending(settings, stop_running=True)


def register_handlers() -> None:
    for handlers, handler in (
        (bpy.app.handlers.depsgraph_update_post, depsgraph_update_post),
        (bpy.app.handlers.load_post, load_post),
    ):
        while handler in handlers:
            handlers.remove(handler)
        handlers.append(handler)


def unregister_handlers() -> None:
    cancel_pending(stop_running=True)
    for handlers, handler in (
        (bpy.app.handlers.depsgraph_update_post, depsgraph_update_post),
        (bpy.app.handlers.load_post, load_post),
    ):
        while handler in handlers:
            handlers.remove(handler)
