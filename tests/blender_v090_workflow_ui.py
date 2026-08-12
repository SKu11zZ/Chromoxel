"""Chromoxel 0.9 numbered bilingual workflow UI regression."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voxelizer  # noqa: E402


class RecordingLayout:
    enabled = True
    scale_y = 1.0

    def __init__(self, events):
        self.events = events
        self._enabled = True

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.events.append(("enabled", self._enabled))

    def box(self):
        return self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def grid_flow(self, **_kwargs):
        return self

    def label(self, **kwargs):
        self.events.append(("label", kwargs.get("text", "")))

    def prop(self, _owner, property_name, **kwargs):
        self.events.append(("prop", property_name, kwargs.get("text", "")))

    def prop_search(self, _owner, property_name, *_args, **kwargs):
        self.events.append(("prop_search", property_name, kwargs.get("text", "")))

    def template_list(self, *_args, **_kwargs):
        self.events.append(("template_list",))

    def operator(self, operator_id, **kwargs):
        result = SimpleNamespace()
        self.events.append(
            ("operator", operator_id, kwargs.get("text", ""), kwargs.get("icon", ""), result)
        )
        return result


def draw(language: str):
    settings = bpy.context.scene.voxelizer_settings
    settings.ui_language = language
    settings.show_step_edit = False
    settings.show_step_live = False
    settings.show_advanced = False
    events = []
    panel = SimpleNamespace(layout=RecordingLayout(events))
    voxelizer.VOXELIZER_PT_panel.draw(panel, bpy.context)
    return events


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    voxelizer.register()
    try:
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        english = draw("EN")
        chinese = draw("ZH")

        english_text = [event[-1] for event in english if len(event) >= 2]
        chinese_text = [event[-1] for event in chinese if len(event) >= 2]
        assert "START HERE" in english_text
        assert "从这里开始" in chinese_text
        assert "1. Select Source" in english_text
        assert "1. 选择源模型" in chinese_text
        assert "6. Bake Output" in english_text
        assert "6. 烘焙输出" in chinese_text

        def first_index(events, predicate):
            return next(index for index, event in enumerate(events) if predicate(event))

        language_index = first_index(
            english,
            lambda event: event[0] == "prop" and event[1] == "ui_language",
        )
        bake_mode_index = first_index(
            english,
            lambda event: event[0] == "operator"
            and event[1] == voxelizer.VOXELIZER_OT_set_enum.bl_idname
            and event[2] == "Editable",
        )
        preview_index = first_index(
            english,
            lambda event: event[0] == "operator"
            and event[1] == voxelizer.VOXELIZER_OT_preview.bl_idname,
        )
        bake_index = first_index(
            english,
            lambda event: event[0] == "operator"
            and event[1] == voxelizer.VOXELIZER_OT_bake.bl_idname,
        )
        step_one_index = first_index(
            english,
            lambda event: event[0] == "prop" and event[1] == "show_step_source",
        )
        assert max(language_index, bake_mode_index, preview_index, bake_index) < step_one_index

        preview_event = english[preview_index]
        bake_event = english[bake_index]
        assert preview_event[3] == "GEOMETRY_NODES"
        assert len(voxelizer.VOXELIZER_OT_preview.bl_description.split()) >= 8
        assert len(voxelizer.VOXELIZER_OT_bake.bl_description.split()) >= 8
        assert any(
            event[0] == "label" and event[1] == "Source: Cube"
            for event in english
        )
        print("PASS chromoxel_blender_0.9.0_workflow_ui")
    finally:
        voxelizer.unregister()


if __name__ == "__main__":
    main()
