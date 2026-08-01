#pragma once

#include "CoreMinimal.h"

class UMaterialInterface;

class FVoxelMapPreviewMaterial
{
public:
    static constexpr const TCHAR* AssetPath =
        TEXT("/Game/VoxelMapMVP/Materials/M_VoxelMapPreview_BaseColor");

    static bool EnsurePersistentMaterial(
        UMaterialInterface*& OutMaterial,
        FString& OutError);
};
