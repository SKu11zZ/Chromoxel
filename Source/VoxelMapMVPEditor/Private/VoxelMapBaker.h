#pragma once

#include "CoreMinimal.h"
#include "VoxelMapDataAsset.h"

class UWorld;
class UVoxelMapDataAsset;

struct FVoxelMapBakeOptions
{
    float VoxelSize = 25.0f;
    int32 MaxAxisVoxels = 1024;
    int32 MaxOccupiedVoxels = 750000;
    int64 MaxCandidateTests = 100000000;
    int32 ColorMinViewResolution = 32;
    int32 ColorMaxViewResolution = 2048;
    int32 ColorPixelsPerVoxel = 2;
    float MinimumColorCoverage = 0.95f;
    FString SourceMapPath;
    FString OutputMapPath;
    FString DataAssetPath;
    FString ReportPath;
    bool bHideIncludedSourceMeshes = true;
};

struct FVoxelMapBakeResult
{
    bool bSuccess = false;
    FString Error;
    FString DataAssetPath;
    FString OutputMapPath;
    FString ReportPath;
    int32 OccupiedVoxelCount = 0;
    int32 BlockCount = 0;
    int32 SourceActorCount = 0;
    int32 SourceComponentCount = 0;
    int32 SourceMeshInstanceCount = 0;
    int32 UniqueMeshCount = 0;
    int64 SourceTriangleInstanceCount = 0;
    int64 CandidateTests = 0;
    int32 FilteredHidden = 0;
    int32 FilteredMovable = 0;
    int32 FilteredNoCollision = 0;
    int32 FilteredSky = 0;
    int32 FilteredNoMesh = 0;
    int32 FilteredNoMeshDescription = 0;
    bool bWorldPartitioned = false;
    bool bWorldPartitionFullyLoaded = false;
    bool bOutputRefreshedInPlace = false;
    int32 WorldPartitionActorDescriptorCount = 0;
    int32 WorldPartitionLoadedReferenceCount = 0;
    double BakeSeconds = 0.0;
    int64 DataAssetBytes = -1;
    int64 OutputMapBytes = -1;
    FString DataHash;
    bool bColorCaptureComplete = false;
    bool bColorCaptureSucceededWithFallback = false;
    FString ColorMode;
    FString ColorCaptureVersion;
    FString ColorCaptureStatus;
    FString ColorHash;
    FString CaptureConfigHash;
    FString ColorCaptureDiagnosticSummary;
    FString PreviewMaterialPath;
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
    int32 ColorCount = 0;
    int32 CapturedColorVoxelCount = 0;
    int32 FallbackColorVoxelCount = 0;
    int32 UniqueColorCount = 0;
    float ColorCoverage = 0.0f;
    TArray<FString> ColorFallbackReasons;
    TArray<FVoxelMapColorCaptureViewStats> ColorCaptureViews;
};

class FVoxelMapBaker
{
public:
    static bool BakeWorldAndSave(UWorld* World, const FVoxelMapBakeOptions& Options, FVoxelMapBakeResult& OutResult);
    static FVoxelMapBakeOptions MakeDefaultOptionsForWorld(UWorld* World);
};
