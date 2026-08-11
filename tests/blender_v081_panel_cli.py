"""Chromoxel 0.8.1 passive-panel and strict CLI-fit regressions."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402
from voxelizer import cli, core, live  # noqa: E402


class _DummyLayout:
    """Minimal no-op Blender layout used to execute a panel draw headlessly."""

    enabled = True

    def box(self):
        return self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def grid_flow(self, **_kwargs):
        return self

    def label(self, **_kwargs):
        return None

    def prop(self, *_args, **_kwargs):
        return None

    def prop_search(self, *_args, **_kwargs):
        return None

    def template_list(self, *_args, **_kwargs):
        return None

    def operator(self, *_args, **_kwargs):
        return SimpleNamespace()


def _draw_panel() -> None:
    panel = SimpleNamespace(layout=_DummyLayout())
    voxelizer.VOXELIZER_PT_panel.draw(panel, bpy.context)


def _panel_regression() -> None:
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    source = bpy.context.object
    source.name = "PassivePanelCube"
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.context.view_layer.update()

    original_diagnostics = core.mesh_diagnostics
    original_closed = core.is_closed_manifold

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Panel draw must not inspect source topology")

    try:
        core.mesh_diagnostics = forbidden
        core.is_closed_manifold = forbidden
        _draw_panel()
    finally:
        core.mesh_diagnostics = original_diagnostics
        core.is_closed_manifold = original_closed

    calls = 0

    def counted(mesh):
        nonlocal calls
        calls += 1
        return original_diagnostics(mesh)

    try:
        core.mesh_diagnostics = counted
        result = bpy.ops.voxelizer.check_surface()
    finally:
        core.mesh_diagnostics = original_diagnostics
    assert result == {"FINISHED"}
    assert calls == 1, f"Explicit surface check ran diagnostics {calls} times"

    settings = bpy.context.scene.voxelizer_settings
    assert settings.surface_check_state == "WATERTIGHT"
    assert settings.surface_check_boundary_edges == 0
    assert settings.surface_check_components == 1

    try:
        core.mesh_diagnostics = forbidden
        core.is_closed_manifold = forbidden
        _draw_panel()
    finally:
        core.mesh_diagnostics = original_diagnostics
        core.is_closed_manifold = original_closed

    live._clear_surface_check(settings)
    assert settings.surface_check_state == "UNCHECKED"

    key_before = core.preview_sampling_key(bpy.context, source, settings)
    source.location.x += 1.0
    bpy.context.view_layer.update()
    key_after_transform = core.preview_sampling_key(bpy.context, source, settings)
    assert key_after_transform == key_before

    source.data.vertices[0].co.x += 0.125
    source.data.update()
    bpy.context.view_layer.update()
    key_after_geometry = core.preview_sampling_key(bpy.context, source, settings)
    assert key_after_geometry != key_before

    image = bpy.data.images.new("RuntimeKeyImage", width=1, height=1)
    settings.base_color_image = image
    bpy.context.view_layer.update()
    key_before_pixels = core.preview_sampling_key(bpy.context, source, settings)
    image.pixels = (1.0, 0.0, 0.0, 1.0)
    image.update()
    bpy.context.view_layer.update()
    key_after_pixels = core.preview_sampling_key(bpy.context, source, settings)
    assert key_after_pixels != key_before_pixels
    settings.base_color_image = None

    assert core.diagnostics_ready(core.mesh_readiness_diagnostics(source.data))
    open_mesh = bpy.data.meshes.new("ReadinessOpenCube")
    open_mesh.from_pydata(
        [
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        ],
        [],
        [
            (0, 1, 2, 3),
            (0, 4, 5, 1),
            (1, 5, 6, 2),
            (2, 6, 7, 3),
            (3, 7, 4, 0),
        ],
    )
    readiness = core.mesh_readiness_diagnostics(open_mesh)
    assert not core.diagnostics_ready(readiness)
    assert readiness["complete"] is False
    assert readiness["nonmanifold_edges"] == 1
    bpy.data.meshes.remove(open_mesh)


def _cli_fit_regression() -> None:
    originals = {
        "surface_area": cli._surface_area,
        "configure_settings": cli.configure_settings,
        "select_only": cli._select_only,
        "sampling_session": core.sampling_session,
        "sample_surface_voxels": core.sample_surface_voxels,
    }
    state = {"counts": [], "samples": 0, "sessions": 0}

    def fake_configure(settings, **kwargs):
        settings.voxel_size = float(kwargs["voxel_size"])
        if not hasattr(settings, "repair_voxel_size"):
            settings.repair_voxel_size = 0.1

    @contextmanager
    def fake_session(*_args, **_kwargs):
        state["sessions"] += 1
        yield SimpleNamespace()

    def fake_sample(*_args, **_kwargs):
        state["samples"] += 1
        if not state["counts"]:
            raise AssertionError("Unexpected duplicate or fallback sample")
        return SimpleNamespace(count=state["counts"].pop(0))

    try:
        cli._surface_area = lambda *_args, **_kwargs: 1.0
        cli.configure_settings = fake_configure
        cli._select_only = lambda *_args, **_kwargs: None
        core.sampling_session = fake_session
        core.sample_surface_voxels = fake_sample

        settings = SimpleNamespace(repair_voxel_size=0.1)
        state.update(counts=[1192, 2277, 1805, 2147], samples=0, sessions=0)
        try:
            cli.fit_target_voxels(
                bpy.context,
                bpy.context.object,
                settings,
                2000,
                tolerance=0.05,
                max_iterations=4,
            )
        except cli.CLIError as exc:
            assert "No out-of-tolerance output was created" in str(exc)
        else:
            raise AssertionError("An out-of-tolerance fit was incorrectly accepted")
        assert state["samples"] == 4
        assert state["sessions"] == 1
        assert not state["counts"]

        state.update(counts=[1192, 2277, 1950, 1950], samples=0, sessions=0)
        sample, _size, attempts = cli.fit_target_voxels(
            bpy.context,
            bpy.context.object,
            settings,
            2000,
            tolerance=0.05,
            max_iterations=4,
        )
        assert sample.count == 1950
        assert len(attempts) == 3
        assert attempts[-1]["final_voxels"] == 1950
        assert state["samples"] == 4
        assert state["sessions"] == 1
        assert not state["counts"]
    finally:
        cli._surface_area = originals["surface_area"]
        cli.configure_settings = originals["configure_settings"]
        cli._select_only = originals["select_only"]
        core.sampling_session = originals["sampling_session"]
        core.sample_surface_voxels = originals["sample_surface_voxels"]


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    try:
        _panel_regression()
        _cli_fit_regression()
        print("PASS chromoxel_blender_0.8.1_panel_cli")
    finally:
        voxelizer.unregister()


if __name__ == "__main__":
    main()
