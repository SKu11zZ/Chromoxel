#pragma once

#include "CoreMinimal.h"
#include "VoxelMapDataAsset.h"

class UPrimitiveComponent;
class UWorld;

struct FVoxelMapColorCaptureSettings
{
    int32 MinViewResolution = 32;
    int32 MaxViewResolution = 2048;
    int32 PixelsPerVoxel = 2;
    float BoundsPaddingVoxels = 2.0f;
    float CameraPaddingVoxels = 2.0f;
    float NearClipCm = 1.0f;
    float MinimumAcceptedCoverage = 0.95f;
    TFunction<bool()> ShouldCancel;
    TFunction<void(int32 CompletedViews, int32 TotalViews)> ReportViewProgress;
};

struct FVoxelMapColorCaptureResult
{
    bool bComplete = false;
    bool bSucceededWithFallback = false;
    FString Error;
    FString ColorMode;
    FString CaptureVersion;
    FString CaptureStatus;
    FString ColorHash;
    FString ConfigHash;
    FString DiagnosticSummary;
    int32 RequestedShowOnlyComponentCount = 0;
    int32 EligibleShowOnlyComponentCount = 0;
    int32 RenderStateCreatedComponentCount = 0;
    int32 ValidPrimitiveSceneIdComponentCount = 0;
    int32 NonNullSceneProxyComponentCount = 0;
    int32 ViewsWithRenderWriteCount = 0;
    int32 AllClearDepthViewCount = 0;
    int32 InRangeDepthViewCount = 0;
    int32 OccupiedLookupViewCount = 0;
    bool bAllViewsClearDepth = false;
    int32 CapturedVoxelCount = 0;
    int32 FallbackVoxelCount = 0;
    int32 UniqueColorCount = 0;
    float Coverage = 0.0f;
    TArray<uint32> PackedColors;
    TArray<FString> FallbackReasons;
    TArray<FVoxelMapColorCaptureViewStats> Views;
};

class FVoxelMapColorCapture
{
public:
    static bool Capture(
        UWorld* World,
        const FBox& Bounds,
        const FVector3d& BakeOrigin,
        double VoxelSize,
        const TArray<FVoxelMapBlock>& CanonicalBlocks,
        TConstArrayView<UPrimitiveComponent*> ShowOnlyComponents,
        const FVoxelMapColorCaptureSettings& Settings,
        FVoxelMapColorCaptureResult& OutResult);
};
