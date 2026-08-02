"""Portable source/package contract checks for Chromoxel Unreal v0.3.0."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


descriptor = json.loads((ROOT / "VoxelMapMVP.uplugin").read_text(encoding="utf-8"))
require(descriptor["VersionName"] == "0.3.0", "descriptor version mismatch")
require(descriptor["FriendlyName"] == "Chromoxel", "friendly name mismatch")
require([module["Name"] for module in descriptor["Modules"]] == [
    "VoxelMapMVP",
    "VoxelMapMVPEditor",
], "module identity changed")

baker_h = (ROOT / "Source/VoxelMapMVPEditor/Private/VoxelMapBaker.h").read_text(encoding="utf-8")
baker_cpp = (ROOT / "Source/VoxelMapMVPEditor/Private/VoxelMapBaker.cpp").read_text(encoding="utf-8")
module_cpp = (ROOT / "Source/VoxelMapMVPEditor/Private/VoxelMapMVPEditorModule.cpp").read_text(encoding="utf-8")
preview_h = (ROOT / "Source/VoxelMapMVP/Public/VoxelMapPreviewActor.h").read_text(encoding="utf-8")
preview_cpp = (ROOT / "Source/VoxelMapMVP/Private/VoxelMapPreviewActor.cpp").read_text(encoding="utf-8")
data_h = (ROOT / "Source/VoxelMapMVP/Public/VoxelMapDataAsset.h").read_text(encoding="utf-8")
commandlet_cpp = (ROOT / "Source/VoxelMapMVPEditor/Private/VoxelMapBakeCommandlet.cpp").read_text(encoding="utf-8")
readme = (ROOT / "README.md").read_text(encoding="utf-8")

for token in ("World", "SelectedActors", "Bounds"):
    require(token in baker_h, f"missing scope {token}")
for voxel_size in ("10.0f", "25.0f", "50.0f"):
    require(voxel_size in module_cpp, f"missing editor preset {voxel_size}")
require("FScopedSlowTask" in baker_cpp, "progress task missing")
require("ShouldCancel" in baker_cpp, "baker cancellation missing")
require("ReportViewProgress" in baker_cpp, "color progress bridge missing")
require("BlockContentHashes" in data_h and "BuildBlockContentHashes" in baker_cpp, "block hashes missing")
require("LOAD_NoWarn" in baker_cpp, "first-bake asset probe emits a misleading warning")
require("PreviewChunkComponents" in preview_h, "preview chunks missing")
require("BlocksPerPreviewChunk = 4" in preview_cpp, "16-cell chunk grouping missing")
require("FloorDivide" in preview_cpp, "signed chunk coordinates are not floor-divided")
require("LastReusedPreviewChunkCount" in preview_cpp, "preview reuse accounting missing")
require("reused_preview_chunks" in baker_cpp, "preview reuse report field missing")
require("SourceMaterialSlotCount" in data_h, "material diagnostics missing")
require("GetNumMaterials" in baker_cpp, "all material slots are not inspected")
require("Preset=" in commandlet_cpp and "Scope=" in commandlet_cpp, "commandlet presets/scopes missing")
require('TEXT("BoundsMin="), BoundsMinText, false' in commandlet_cpp, "BoundsMin CSV parsing can truncate")
require('TEXT("BoundsMax="), BoundsMaxText, false' in commandlet_cpp, "BoundsMax CSV parsing can truncate")
require("IsNumeric" in commandlet_cpp, "bounds vector numeric validation missing")
require("## English" in readme and "## 简体中文" in readme, "README is not bilingual")

for generated in ("Binaries", "Intermediate", "Saved"):
    require(not (ROOT / generated).exists(), f"generated directory leaked: {generated}")

print("PASS chromoxel_unreal_0.3.0_source_contract")
