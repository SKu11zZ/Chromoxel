#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "VoxelMapDataAsset.generated.h"

USTRUCT()
struct VOXELMAPMVP_API FVoxelMapBlock
{
    GENERATED_BODY()

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map")
    FIntVector BlockCoord = FIntVector::ZeroValue;

    /** Bit index is X + 4 * Y + 16 * Z inside this 4x4x4 block. */
    UPROPERTY(VisibleAnywhere, Category = "Voxel Map")
    uint64 OccupancyMask = 0;
};

USTRUCT()
struct VOXELMAPMVP_API FVoxelMapColorCaptureViewStats
{
    GENERATED_BODY()

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString ViewName;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 ResolutionX = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 ResolutionY = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Camera")
    FVector CaptureLocation = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Camera")
    FVector CaptureForward = FVector::ForwardVector;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Camera")
    float OrthoWidth = 0.0f;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Camera")
    float OrthoHeight = 0.0f;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Camera")
    float NearClip = 0.0f;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Camera")
    float FarClip = 0.0f;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorRequestedFormat = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorActualFormat = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorRequestedSizeX = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorRequestedSizeY = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorActualSizeX = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorActualSizeY = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    bool bBaseColorRenderTargetResourceValid = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    bool bBaseColorRenderTargetRHIValid = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    bool bBaseColorCaptureInvoked = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    bool bBaseColorReadbackSucceeded = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorReadbackPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|BaseColor RT")
    int32 BaseColorNonClearPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthRequestedFormat = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthActualFormat = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthRequestedSizeX = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthRequestedSizeY = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthActualSizeX = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthActualSizeY = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    bool bDepthRenderTargetResourceValid = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    bool bDepthRenderTargetRHIValid = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    bool bDepthCaptureInvoked = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    bool bDepthReadbackSucceeded = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth RT")
    int32 DepthReadbackPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    bool bHasFiniteDepthRange = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    double RawDepthMinimum = 0.0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    double RawDepthMaximum = 0.0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    double DepthClearSentinel = 0.0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthFinitePixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthNonFinitePixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthClearSentinelPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthNonClearPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthBelowOrEqualNearPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthInRangePixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Depth Diagnostics")
    int32 RawDepthAboveOrEqualFarPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 DepthHitPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 OccupiedLookupPixelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 WinningVoxelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString FallbackReason;
};

UCLASS(BlueprintType)
class VOXELMAPMVP_API UVoxelMapDataAsset : public UDataAsset
{
    GENERATED_BODY()

public:
    UPROPERTY(VisibleAnywhere, Category = "Source")
    FString SourceMap;

    UPROPERTY(VisibleAnywhere, Category = "Source")
    bool bSourceWorldPartitioned = false;

    UPROPERTY(VisibleAnywhere, Category = "Source")
    bool bWorldPartitionFullyLoadedForBake = false;

    UPROPERTY(VisibleAnywhere, Category = "Source")
    int32 WorldPartitionActorDescriptorCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Source")
    int32 WorldPartitionLoadedReferenceCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Source")
    FString BakeScope = TEXT("World");

    UPROPERTY(VisibleAnywhere, Category = "Source")
    FVector ScopeBoundsMin = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category = "Source")
    FVector ScopeBoundsMax = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    FVector BakeOrigin = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    FVector BoundsMin = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    FVector BoundsMax = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category = "Bake", meta = (Units = "cm"))
    float VoxelSize = 25.0f;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    int32 OccupiedVoxelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    int32 SourceActorCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    int32 SourceComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    int32 SourceMeshInstanceCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    int64 SourceTriangleInstanceCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    double BakeSeconds = 0.0;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    FString DataHash;

    UPROPERTY(VisibleAnywhere, Category = "Bake")
    FString BuildSummary;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Materials")
    int32 SourceMaterialSlotCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Materials")
    int32 SourceUniqueMaterialCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Materials")
    int32 SourceNullMaterialSlotCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Materials")
    int32 MultiMaterialComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Incremental")
    bool bIncrementalCompatible = false;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Incremental")
    int32 ReusedBlockCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Incremental")
    int32 ChangedBlockCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Incremental")
    int32 RemovedBlockCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Bake|Incremental")
    FString PreviousDataHash;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map")
    TArray<FVoxelMapBlock> Blocks;

    /** One stable geometry+color content hash per canonical block. */
    UPROPERTY(VisibleAnywhere, Category = "Voxel Map")
    TArray<uint64> BlockContentHashes;

    /**
     * One 0x00RRGGBB sRGB value per occupied voxel. Ordering is canonical:
     * Blocks order followed by ascending set-bit order inside each block.
     * This array is deliberately additive; legacy assets may leave it empty.
     */
    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    TArray<uint32> PackedVoxelColors;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString ColorMode;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString ColorCaptureVersion;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString ColorCaptureStatus;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString ColorHash;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    FString CaptureConfigHash;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 RequestedShowOnlyComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 EligibleShowOnlyComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 RenderStateCreatedComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 ValidPrimitiveSceneIdComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 NonNullSceneProxyComponentCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 ViewsWithRenderWriteCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 AllClearDepthViewCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 InRangeDepthViewCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    int32 OccupiedLookupViewCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    bool bAllViewsClearDepth = false;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color|Diagnostics")
    FString ColorCaptureDiagnosticSummary;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 CapturedColorVoxelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 FallbackColorVoxelCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    int32 UniqueColorCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    float ColorCoverage = 0.0f;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    TArray<FString> ColorFallbackReasons;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Color")
    TArray<FVoxelMapColorCaptureViewStats> ColorCaptureViews;

    static constexpr uint32 DefaultPackedColor = 0x00808080u;

    /**
     * Empty or length-mismatched legacy/corrupt color payloads fail safely to
     * #808080. The geometry payload and its ordering remain authoritative.
     */
    uint32 GetPackedVoxelColorOrDefault(int32 CanonicalVoxelIndex) const
    {
        const bool bHasCompletePayload =
            OccupiedVoxelCount >= 0 &&
            PackedVoxelColors.Num() == OccupiedVoxelCount;
        return bHasCompletePayload && PackedVoxelColors.IsValidIndex(CanonicalVoxelIndex)
            ? PackedVoxelColors[CanonicalVoxelIndex]
            : DefaultPackedColor;
    }
};
