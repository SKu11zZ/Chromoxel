#include "VoxelMapBaker.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Editor.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "FileHelpers.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "JsonObjectConverter.h"
#include "Materials/MaterialInterface.h"
#include "MeshDescription.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "StaticMeshAttributes.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "UObject/StrongObjectPtr.h"
#include "VoxelMapColorCapture.h"
#include "VoxelMapDataAsset.h"
#include "VoxelMapPreviewActor.h"
#include "VoxelMapPreviewMaterial.h"
#include "WorldPartition/ActorDescContainerInstance.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/WorldPartitionHandle.h"

DEFINE_LOG_CATEGORY_STATIC(LogVoxelMapMVP, Log, All);

namespace
{
struct FMeshWorkItem
{
    TObjectPtr<UStaticMesh> Mesh;
    FTransform WorldTransform;
    TObjectPtr<UStaticMeshComponent> SourceComponent;
};

struct FCollectionStats
{
    int32 ActorCount = 0;
    int32 ComponentCount = 0;
    int32 MeshInstanceCount = 0;
    int32 FilteredHidden = 0;
    int32 FilteredMovable = 0;
    int32 FilteredNoCollision = 0;
    int32 FilteredSky = 0;
    int32 FilteredNoMesh = 0;
};

bool IsSkyMesh(const UStaticMesh* Mesh)
{
    if (!Mesh)
    {
        return false;
    }

    const FString MeshName = Mesh->GetName();
    return MeshName.Contains(TEXT("SkySphere"), ESearchCase::IgnoreCase) ||
           MeshName.Contains(TEXT("Sky_Sphere"), ESearchCase::IgnoreCase);
}

bool IsComponentEligible(UStaticMeshComponent* Component, FCollectionStats& Stats)
{
    if (!Component || !IsValid(Component))
    {
        ++Stats.FilteredNoMesh;
        return false;
    }

    AActor* Owner = Component->GetOwner();
    if (!Owner || Owner->IsHidden() || Owner->IsHiddenEd() || !Component->IsVisible() || Component->bHiddenInGame)
    {
        ++Stats.FilteredHidden;
        return false;
    }

    if (Component->Mobility != EComponentMobility::Static)
    {
        ++Stats.FilteredMovable;
        return false;
    }

    if (Component->GetCollisionEnabled() == ECollisionEnabled::NoCollision)
    {
        ++Stats.FilteredNoCollision;
        return false;
    }

    UStaticMesh* Mesh = Component->GetStaticMesh();
    if (!Mesh)
    {
        ++Stats.FilteredNoMesh;
        return false;
    }

    if (IsSkyMesh(Mesh))
    {
        ++Stats.FilteredSky;
        return false;
    }

    return true;
}

void CollectWorkItems(UWorld* World, TArray<FMeshWorkItem>& OutItems, FCollectionStats& OutStats)
{
    TSet<AActor*> SourceActors;
    TSet<UStaticMeshComponent*> SourceComponents;

    for (TActorIterator<AActor> ActorIt(World); ActorIt; ++ActorIt)
    {
        AActor* Actor = *ActorIt;
        if (!Actor || Actor->IsA<AVoxelMapPreviewActor>())
        {
            continue;
        }

        TInlineComponentArray<UStaticMeshComponent*> Components(Actor);
        for (UStaticMeshComponent* Component : Components)
        {
            if (!IsComponentEligible(Component, OutStats))
            {
                continue;
            }

            UStaticMesh* Mesh = Component->GetStaticMesh();
            SourceActors.Add(Actor);
            SourceComponents.Add(Component);

            if (UInstancedStaticMeshComponent* InstancedComponent = Cast<UInstancedStaticMeshComponent>(Component))
            {
                const int32 InstanceCount = InstancedComponent->GetInstanceCount();
                for (int32 InstanceIndex = 0; InstanceIndex < InstanceCount; ++InstanceIndex)
                {
                    FTransform InstanceWorldTransform;
                    if (InstancedComponent->GetInstanceTransform(InstanceIndex, InstanceWorldTransform, true))
                    {
                        OutItems.Add({Mesh, InstanceWorldTransform, Component});
                    }
                }
            }
            else
            {
                OutItems.Add({Mesh, Component->GetComponentTransform(), Component});
            }
        }
    }

    OutStats.ActorCount = SourceActors.Num();
    OutStats.ComponentCount = SourceComponents.Num();
    OutStats.MeshInstanceCount = OutItems.Num();
}

bool AxisHasOverlap(
    const FVector3d& Axis,
    const FVector3d& V0,
    const FVector3d& V1,
    const FVector3d& V2,
    const FVector3d& BoxHalfExtent)
{
    if (Axis.SizeSquared() < 1.0e-16)
    {
        return true;
    }

    const double P0 = FVector3d::DotProduct(V0, Axis);
    const double P1 = FVector3d::DotProduct(V1, Axis);
    const double P2 = FVector3d::DotProduct(V2, Axis);
    const double MinProjection = FMath::Min3(P0, P1, P2);
    const double MaxProjection = FMath::Max3(P0, P1, P2);
    const double Radius =
        BoxHalfExtent.X * FMath::Abs(Axis.X) +
        BoxHalfExtent.Y * FMath::Abs(Axis.Y) +
        BoxHalfExtent.Z * FMath::Abs(Axis.Z);
    return MinProjection <= Radius && MaxProjection >= -Radius;
}

bool TriangleIntersectsBox(
    const FVector3d& BoxCenter,
    const FVector3d& BoxHalfExtent,
    const FVector3d& WorldA,
    const FVector3d& WorldB,
    const FVector3d& WorldC)
{
    const FVector3d V0 = WorldA - BoxCenter;
    const FVector3d V1 = WorldB - BoxCenter;
    const FVector3d V2 = WorldC - BoxCenter;

    const double MinX = FMath::Min3(V0.X, V1.X, V2.X);
    const double MaxX = FMath::Max3(V0.X, V1.X, V2.X);
    const double MinY = FMath::Min3(V0.Y, V1.Y, V2.Y);
    const double MaxY = FMath::Max3(V0.Y, V1.Y, V2.Y);
    const double MinZ = FMath::Min3(V0.Z, V1.Z, V2.Z);
    const double MaxZ = FMath::Max3(V0.Z, V1.Z, V2.Z);
    if (MinX > BoxHalfExtent.X || MaxX < -BoxHalfExtent.X ||
        MinY > BoxHalfExtent.Y || MaxY < -BoxHalfExtent.Y ||
        MinZ > BoxHalfExtent.Z || MaxZ < -BoxHalfExtent.Z)
    {
        return false;
    }

    const FVector3d E0 = V1 - V0;
    const FVector3d E1 = V2 - V1;
    const FVector3d E2 = V0 - V2;
    const FVector3d TriangleNormal = FVector3d::CrossProduct(E0, E1);
    if (!AxisHasOverlap(TriangleNormal, V0, V1, V2, BoxHalfExtent))
    {
        return false;
    }

    static const FVector3d BoxAxes[] =
    {
        FVector3d(1.0, 0.0, 0.0),
        FVector3d(0.0, 1.0, 0.0),
        FVector3d(0.0, 0.0, 1.0)
    };
    const FVector3d TriangleEdges[] = {E0, E1, E2};
    for (const FVector3d& Edge : TriangleEdges)
    {
        for (const FVector3d& BoxAxis : BoxAxes)
        {
            if (!AxisHasOverlap(FVector3d::CrossProduct(Edge, BoxAxis), V0, V1, V2, BoxHalfExtent))
            {
                return false;
            }
        }
    }

    return true;
}

FIntVector ToCellCoord(const FVector3d& Position, const FVector3d& Origin, double VoxelSize)
{
    const FVector3d Relative = (Position - Origin) / VoxelSize;
    return FIntVector(
        FMath::FloorToInt(Relative.X),
        FMath::FloorToInt(Relative.Y),
        FMath::FloorToInt(Relative.Z));
}

FString BuildDataHash(const TArray<FVoxelMapBlock>& Blocks)
{
    FSHA1 Sha;
    for (const FVoxelMapBlock& Block : Blocks)
    {
        const int32 Coords[] = {Block.BlockCoord.X, Block.BlockCoord.Y, Block.BlockCoord.Z};
        Sha.Update(reinterpret_cast<const uint8*>(Coords), sizeof(Coords));
        Sha.Update(reinterpret_cast<const uint8*>(&Block.OccupancyMask), sizeof(Block.OccupancyMask));
    }
    Sha.Final();

    uint8 Hash[FSHA1::DigestSize];
    Sha.GetHash(Hash);
    return BytesToHex(Hash, UE_ARRAY_COUNT(Hash));
}

FString BuildColorHash(const TArray<uint32>& PackedColors)
{
    FSHA1 Sha;
    if (!PackedColors.IsEmpty())
    {
        Sha.Update(
            reinterpret_cast<const uint8*>(PackedColors.GetData()),
            static_cast<uint64>(PackedColors.Num()) * sizeof(uint32));
    }
    Sha.Final();

    uint8 Hash[FSHA1::DigestSize];
    Sha.GetHash(Hash);
    return BytesToHex(Hash, UE_ARRAY_COUNT(Hash));
}

bool ValidateColorConsistency(
    const FVoxelMapBakeOptions& Options,
    const FVoxelMapBakeResult& Result,
    int32 PackedColorCount,
    FString& OutError)
{
    const bool bCountsMatch =
        PackedColorCount == Result.OccupiedVoxelCount &&
        Result.ColorCount == Result.OccupiedVoxelCount &&
        Result.CapturedColorVoxelCount >= 0 &&
        Result.FallbackColorVoxelCount >= 0 &&
        Result.CapturedColorVoxelCount + Result.FallbackColorVoxelCount ==
            Result.OccupiedVoxelCount;
    const float ExpectedCoverage = Result.OccupiedVoxelCount > 0
        ? static_cast<float>(Result.CapturedColorVoxelCount) /
            static_cast<float>(Result.OccupiedVoxelCount)
        : 0.0f;
    const bool bCoverageMatches =
        FMath::IsNearlyEqual(Result.ColorCoverage, ExpectedCoverage, 1.0e-6f) &&
        Result.ColorCoverage >= 0.0f &&
        Result.ColorCoverage <= 1.0f;
    const bool bExpectedFallback =
        Result.FallbackColorVoxelCount > 0 ||
        Result.ColorCoverage < Options.MinimumColorCoverage;
    const TCHAR* ExpectedStatus =
        bExpectedFallback ? TEXT("SucceededWithFallback") : TEXT("Succeeded");
    const bool bFallbackMetadataMatches =
        Result.bColorCaptureSucceededWithFallback == bExpectedFallback &&
        Result.ColorCaptureStatus.Equals(ExpectedStatus, ESearchCase::CaseSensitive) &&
        (bExpectedFallback
            ? !Result.ColorFallbackReasons.IsEmpty()
            : Result.ColorFallbackReasons.IsEmpty());
    const bool bMetadataComplete =
        Result.bColorCaptureComplete &&
        Result.ColorMode.Equals(TEXT("basecolor_buffer_depth"), ESearchCase::CaseSensitive) &&
        !Result.ColorCaptureVersion.IsEmpty() &&
        !Result.ColorHash.IsEmpty() &&
        !Result.CaptureConfigHash.IsEmpty() &&
        Result.ColorCaptureViews.Num() == 6;
    const bool bDiagnosticsComplete =
        !Result.ColorCaptureDiagnosticSummary.IsEmpty() &&
        Result.RequestedShowOnlyComponentCount >= Result.EligibleShowOnlyComponentCount &&
        Result.EligibleShowOnlyComponentCount > 0 &&
        Result.RenderStateCreatedComponentCount >= 0 &&
        Result.RenderStateCreatedComponentCount <= Result.EligibleShowOnlyComponentCount &&
        Result.ValidPrimitiveSceneIdComponentCount > 0 &&
        Result.ValidPrimitiveSceneIdComponentCount <= Result.EligibleShowOnlyComponentCount &&
        Result.NonNullSceneProxyComponentCount > 0 &&
        Result.NonNullSceneProxyComponentCount <= Result.EligibleShowOnlyComponentCount &&
        Result.ViewsWithRenderWriteCount >= 0 &&
        Result.ViewsWithRenderWriteCount <= 6 &&
        Result.AllClearDepthViewCount >= 0 &&
        Result.AllClearDepthViewCount < 6 &&
        Result.InRangeDepthViewCount >= 0 &&
        Result.InRangeDepthViewCount <= 6 &&
        Result.OccupiedLookupViewCount >= 0 &&
        Result.OccupiedLookupViewCount <= 6 &&
        !Result.bAllViewsClearDepth;

    if (!bCountsMatch ||
        !bCoverageMatches ||
        !bFallbackMetadataMatches ||
        !bMetadataComplete ||
        !bDiagnosticsComplete)
    {
        OutError = FString::Printf(
            TEXT("Color consistency guard failed: complete=%s colors=%d result_colors=%d ")
            TEXT("captured=%d fallback=%d occupied=%d coverage=%.6f expected=%.6f ")
            TEXT("mode=%s version=%s status=%s views=%d color_hash=%s config_hash=%s ")
            TEXT("diagnostics_complete=%s diagnostic_summary=%s."),
            Result.bColorCaptureComplete ? TEXT("true") : TEXT("false"),
            PackedColorCount,
            Result.ColorCount,
            Result.CapturedColorVoxelCount,
            Result.FallbackColorVoxelCount,
            Result.OccupiedVoxelCount,
            Result.ColorCoverage,
            ExpectedCoverage,
            *Result.ColorMode,
            *Result.ColorCaptureVersion,
            *Result.ColorCaptureStatus,
            Result.ColorCaptureViews.Num(),
            *Result.ColorHash,
            *Result.CaptureConfigHash,
            bDiagnosticsComplete ? TEXT("true") : TEXT("false"),
            *Result.ColorCaptureDiagnosticSummary);
        return false;
    }

    return true;
}

bool SaveDataAsset(
    const FString& DataAssetPath,
    const FVoxelMapBakeOptions& Options,
    const FVoxelMapBakeResult& Result,
    const FVector3d& Origin,
    const FBox& Bounds,
    const TArray<FVoxelMapBlock>& Blocks,
    const TArray<uint32>& PackedColors,
    UVoxelMapDataAsset*& OutAsset,
    FString& OutError)
{
    if (!ValidateColorConsistency(Options, Result, PackedColors.Num(), OutError))
    {
        return false;
    }
    const FString RecomputedColorHash = BuildColorHash(PackedColors);
    if (!RecomputedColorHash.Equals(Result.ColorHash, ESearchCase::CaseSensitive))
    {
        OutError = FString::Printf(
            TEXT("Color hash guard failed before asset save: result=%s recomputed=%s."),
            *Result.ColorHash,
            *RecomputedColorHash);
        return false;
    }

    const FString AssetName = FPackageName::GetLongPackageAssetName(DataAssetPath);
    if (AssetName.IsEmpty() || !FPackageName::IsValidLongPackageName(DataAssetPath))
    {
        OutError = FString::Printf(TEXT("Invalid data asset path: %s"), *DataAssetPath);
        return false;
    }

    const FString ObjectPath = FString::Printf(TEXT("%s.%s"), *DataAssetPath, *AssetName);
    OutAsset = LoadObject<UVoxelMapDataAsset>(nullptr, *ObjectPath);
    bool bCreatedNewAsset = false;
    UPackage* Package = nullptr;
    if (!OutAsset)
    {
        Package = CreatePackage(*DataAssetPath);
        OutAsset = NewObject<UVoxelMapDataAsset>(
            Package,
            *AssetName,
            RF_Public | RF_Standalone | RF_Transactional);
        bCreatedNewAsset = true;
    }
    else
    {
        Package = OutAsset->GetOutermost();
        OutAsset->Modify();
    }

    OutAsset->SourceMap = Options.SourceMapPath;
    OutAsset->bSourceWorldPartitioned = Result.bWorldPartitioned;
    OutAsset->bWorldPartitionFullyLoadedForBake = Result.bWorldPartitionFullyLoaded;
    OutAsset->WorldPartitionActorDescriptorCount = Result.WorldPartitionActorDescriptorCount;
    OutAsset->WorldPartitionLoadedReferenceCount = Result.WorldPartitionLoadedReferenceCount;
    OutAsset->BakeOrigin = FVector(Origin);
    OutAsset->BoundsMin = Bounds.Min;
    OutAsset->BoundsMax = Bounds.Max;
    OutAsset->VoxelSize = Options.VoxelSize;
    OutAsset->OccupiedVoxelCount = Result.OccupiedVoxelCount;
    OutAsset->SourceActorCount = Result.SourceActorCount;
    OutAsset->SourceComponentCount = Result.SourceComponentCount;
    OutAsset->SourceMeshInstanceCount = Result.SourceMeshInstanceCount;
    OutAsset->SourceTriangleInstanceCount = Result.SourceTriangleInstanceCount;
    OutAsset->BakeSeconds = Result.BakeSeconds;
    OutAsset->DataHash = Result.DataHash;
    OutAsset->Blocks = Blocks;
    OutAsset->PackedVoxelColors = PackedColors;
    OutAsset->ColorMode = Result.ColorMode;
    OutAsset->ColorCaptureVersion = Result.ColorCaptureVersion;
    OutAsset->ColorCaptureStatus = Result.ColorCaptureStatus;
    OutAsset->ColorHash = Result.ColorHash;
    OutAsset->CaptureConfigHash = Result.CaptureConfigHash;
    OutAsset->RequestedShowOnlyComponentCount =
        Result.RequestedShowOnlyComponentCount;
    OutAsset->EligibleShowOnlyComponentCount =
        Result.EligibleShowOnlyComponentCount;
    OutAsset->RenderStateCreatedComponentCount =
        Result.RenderStateCreatedComponentCount;
    OutAsset->ValidPrimitiveSceneIdComponentCount =
        Result.ValidPrimitiveSceneIdComponentCount;
    OutAsset->NonNullSceneProxyComponentCount =
        Result.NonNullSceneProxyComponentCount;
    OutAsset->ViewsWithRenderWriteCount = Result.ViewsWithRenderWriteCount;
    OutAsset->AllClearDepthViewCount = Result.AllClearDepthViewCount;
    OutAsset->InRangeDepthViewCount = Result.InRangeDepthViewCount;
    OutAsset->OccupiedLookupViewCount = Result.OccupiedLookupViewCount;
    OutAsset->bAllViewsClearDepth = Result.bAllViewsClearDepth;
    OutAsset->ColorCaptureDiagnosticSummary =
        Result.ColorCaptureDiagnosticSummary;
    OutAsset->CapturedColorVoxelCount = Result.CapturedColorVoxelCount;
    OutAsset->FallbackColorVoxelCount = Result.FallbackColorVoxelCount;
    OutAsset->UniqueColorCount = Result.UniqueColorCount;
    OutAsset->ColorCoverage = Result.ColorCoverage;
    OutAsset->ColorFallbackReasons = Result.ColorFallbackReasons;
    OutAsset->ColorCaptureViews = Result.ColorCaptureViews;
    OutAsset->BuildSummary = FString::Printf(
        TEXT("%d voxels, %d blocks, %d actors, %d components, %d mesh instances, %.3f s, ")
        TEXT("Geometry SHA1 %s, Color SHA1 %s, coverage %.2f%% (%s)"),
        Result.OccupiedVoxelCount,
        Result.BlockCount,
        Result.SourceActorCount,
        Result.SourceComponentCount,
        Result.SourceMeshInstanceCount,
        Result.BakeSeconds,
        *Result.DataHash,
        *Result.ColorHash,
        Result.ColorCoverage * 100.0f,
        *Result.ColorCaptureStatus);

    OutAsset->MarkPackageDirty();
    Package->MarkPackageDirty();
    if (bCreatedNewAsset)
    {
        FAssetRegistryModule::AssetCreated(OutAsset);
    }

    const FString PackageFilename =
        FPackageName::LongPackageNameToFilename(DataAssetPath, FPackageName::GetAssetPackageExtension());
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(PackageFilename), true);

    FSavePackageArgs SaveArgs;
    SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
    SaveArgs.SaveFlags = SAVE_None;
    SaveArgs.Error = GError;
    SaveArgs.bSlowTask = false;
    if (!UPackage::SavePackage(Package, OutAsset, *PackageFilename, SaveArgs))
    {
        OutError = FString::Printf(TEXT("Failed to save data asset: %s"), *PackageFilename);
        return false;
    }

    return true;
}

bool WriteReport(const FVoxelMapBakeOptions& Options, FVoxelMapBakeResult& Result, FString& OutError)
{
    if (!ValidateColorConsistency(Options, Result, Result.ColorCount, OutError))
    {
        return false;
    }

    FString ReportPath = Options.ReportPath;
    if (ReportPath.IsEmpty())
    {
        ReportPath = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("VoxelMapMVP"), TEXT("BakeReport.json"));
    }
    else if (FPaths::IsRelative(ReportPath))
    {
        ReportPath = FPaths::Combine(FPaths::ProjectSavedDir(), ReportPath);
    }
    FPaths::NormalizeFilename(ReportPath);
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(ReportPath), true);

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("source_map"), Options.SourceMapPath);
    Root->SetStringField(TEXT("output_map"), Options.OutputMapPath);
    Root->SetStringField(TEXT("data_asset"), Options.DataAssetPath);
    Root->SetNumberField(TEXT("voxel_size_cm"), Options.VoxelSize);
    Root->SetNumberField(TEXT("occupied_voxels"), Result.OccupiedVoxelCount);
    Root->SetNumberField(TEXT("blocks_4x4x4"), Result.BlockCount);
    Root->SetNumberField(TEXT("source_actors"), Result.SourceActorCount);
    Root->SetNumberField(TEXT("source_components"), Result.SourceComponentCount);
    Root->SetNumberField(TEXT("source_mesh_instances"), Result.SourceMeshInstanceCount);
    Root->SetNumberField(TEXT("unique_meshes"), Result.UniqueMeshCount);
    Root->SetNumberField(TEXT("triangle_instances"), static_cast<double>(Result.SourceTriangleInstanceCount));
    Root->SetNumberField(TEXT("candidate_tests"), static_cast<double>(Result.CandidateTests));
    Root->SetNumberField(TEXT("bake_seconds"), Result.BakeSeconds);
    Root->SetNumberField(TEXT("data_asset_bytes"), static_cast<double>(Result.DataAssetBytes));
    Root->SetNumberField(TEXT("output_map_bytes"), static_cast<double>(Result.OutputMapBytes));
    Root->SetStringField(TEXT("data_sha1"), Result.DataHash);
    Root->SetStringField(TEXT("geometry_hash"), Result.DataHash);
    Root->SetStringField(TEXT("GeometryHash"), Result.DataHash);
    Root->SetStringField(TEXT("color_mode"), Result.ColorMode);
    Root->SetStringField(TEXT("color_capture_version"), Result.ColorCaptureVersion);
    Root->SetStringField(TEXT("color_capture_status"), Result.ColorCaptureStatus);
    Root->SetStringField(TEXT("color_hash"), Result.ColorHash);
    Root->SetStringField(TEXT("ColorHash"), Result.ColorHash);
    Root->SetStringField(TEXT("capture_config_hash"), Result.CaptureConfigHash);
    Root->SetStringField(TEXT("ConfigHash"), Result.CaptureConfigHash);
    Root->SetStringField(
        TEXT("color_capture_diagnostic_summary"),
        Result.ColorCaptureDiagnosticSummary);
    Root->SetNumberField(
        TEXT("requested_show_only_components"),
        Result.RequestedShowOnlyComponentCount);
    Root->SetNumberField(
        TEXT("eligible_show_only_components"),
        Result.EligibleShowOnlyComponentCount);
    Root->SetNumberField(
        TEXT("render_state_created_components"),
        Result.RenderStateCreatedComponentCount);
    Root->SetNumberField(
        TEXT("valid_primitive_scene_id_components"),
        Result.ValidPrimitiveSceneIdComponentCount);
    Root->SetNumberField(
        TEXT("non_null_scene_proxy_components"),
        Result.NonNullSceneProxyComponentCount);
    Root->SetNumberField(
        TEXT("views_with_render_write"),
        Result.ViewsWithRenderWriteCount);
    Root->SetNumberField(
        TEXT("all_clear_depth_views"),
        Result.AllClearDepthViewCount);
    Root->SetNumberField(
        TEXT("in_range_depth_views"),
        Result.InRangeDepthViewCount);
    Root->SetNumberField(
        TEXT("occupied_lookup_views"),
        Result.OccupiedLookupViewCount);
    Root->SetBoolField(
        TEXT("all_views_clear_depth"),
        Result.bAllViewsClearDepth);
    Root->SetStringField(TEXT("preview_material"), Result.PreviewMaterialPath);
    Root->SetNumberField(TEXT("color_count"), Result.ColorCount);
    Root->SetNumberField(TEXT("captured_color_voxels"), Result.CapturedColorVoxelCount);
    Root->SetNumberField(TEXT("fallback_color_voxels"), Result.FallbackColorVoxelCount);
    Root->SetNumberField(TEXT("color_coverage"), Result.ColorCoverage);
    Root->SetNumberField(TEXT("unique_colors"), Result.UniqueColorCount);
    Root->SetBoolField(
        TEXT("color_capture_complete"),
        Result.bColorCaptureComplete);
    Root->SetBoolField(
        TEXT("color_succeeded_with_fallback"),
        Result.bColorCaptureSucceededWithFallback);
    Root->SetBoolField(TEXT("world_partitioned"), Result.bWorldPartitioned);
    Root->SetStringField(
        TEXT("output_update_mode"),
        Result.bOutputRefreshedInPlace ? TEXT("in_place") : TEXT("initial_save_as"));
    Root->SetBoolField(TEXT("world_partition_fully_loaded_for_bake"), Result.bWorldPartitionFullyLoaded);
    Root->SetNumberField(
        TEXT("world_partition_actor_descriptors"),
        Result.WorldPartitionActorDescriptorCount);
    Root->SetNumberField(
        TEXT("world_partition_loaded_references"),
        Result.WorldPartitionLoadedReferenceCount);
    Root->SetBoolField(TEXT("source_meshes_hidden_in_output_map"), Options.bHideIncludedSourceMeshes);

    TSharedRef<FJsonObject> Filtered = MakeShared<FJsonObject>();
    Filtered->SetNumberField(TEXT("hidden"), Result.FilteredHidden);
    Filtered->SetNumberField(TEXT("movable"), Result.FilteredMovable);
    Filtered->SetNumberField(TEXT("no_collision"), Result.FilteredNoCollision);
    Filtered->SetNumberField(TEXT("sky_sphere"), Result.FilteredSky);
    Filtered->SetNumberField(TEXT("no_mesh"), Result.FilteredNoMesh);
    Filtered->SetNumberField(TEXT("no_mesh_description"), Result.FilteredNoMeshDescription);
    Root->SetObjectField(TEXT("filtered_components"), Filtered);

    TArray<TSharedPtr<FJsonValue>> FallbackReasonValues;
    FallbackReasonValues.Reserve(Result.ColorFallbackReasons.Num());
    for (const FString& Reason : Result.ColorFallbackReasons)
    {
        FallbackReasonValues.Add(MakeShared<FJsonValueString>(Reason));
    }
    Root->SetArrayField(TEXT("color_fallback_reasons"), FallbackReasonValues);

    TArray<TSharedPtr<FJsonValue>> ViewValues;
    ViewValues.Reserve(Result.ColorCaptureViews.Num());
    for (const FVoxelMapColorCaptureViewStats& View : Result.ColorCaptureViews)
    {
        TSharedRef<FJsonObject> ViewObject = MakeShared<FJsonObject>();
        ViewObject->SetStringField(TEXT("view"), View.ViewName);
        ViewObject->SetNumberField(TEXT("resolution_x"), View.ResolutionX);
        ViewObject->SetNumberField(TEXT("resolution_y"), View.ResolutionY);
        ViewObject->SetNumberField(TEXT("capture_location_x"), View.CaptureLocation.X);
        ViewObject->SetNumberField(TEXT("capture_location_y"), View.CaptureLocation.Y);
        ViewObject->SetNumberField(TEXT("capture_location_z"), View.CaptureLocation.Z);
        ViewObject->SetNumberField(TEXT("capture_forward_x"), View.CaptureForward.X);
        ViewObject->SetNumberField(TEXT("capture_forward_y"), View.CaptureForward.Y);
        ViewObject->SetNumberField(TEXT("capture_forward_z"), View.CaptureForward.Z);
        ViewObject->SetNumberField(TEXT("ortho_width"), View.OrthoWidth);
        ViewObject->SetNumberField(TEXT("ortho_height"), View.OrthoHeight);
        ViewObject->SetNumberField(TEXT("near_clip"), View.NearClip);
        ViewObject->SetNumberField(TEXT("far_clip"), View.FarClip);
        ViewObject->SetNumberField(
            TEXT("basecolor_requested_format"),
            View.BaseColorRequestedFormat);
        ViewObject->SetNumberField(
            TEXT("basecolor_actual_format"),
            View.BaseColorActualFormat);
        ViewObject->SetNumberField(
            TEXT("basecolor_requested_size_x"),
            View.BaseColorRequestedSizeX);
        ViewObject->SetNumberField(
            TEXT("basecolor_requested_size_y"),
            View.BaseColorRequestedSizeY);
        ViewObject->SetNumberField(
            TEXT("basecolor_actual_size_x"),
            View.BaseColorActualSizeX);
        ViewObject->SetNumberField(
            TEXT("basecolor_actual_size_y"),
            View.BaseColorActualSizeY);
        ViewObject->SetBoolField(
            TEXT("basecolor_resource_valid"),
            View.bBaseColorRenderTargetResourceValid);
        ViewObject->SetBoolField(
            TEXT("basecolor_rhi_valid"),
            View.bBaseColorRenderTargetRHIValid);
        ViewObject->SetBoolField(
            TEXT("basecolor_capture_invoked"),
            View.bBaseColorCaptureInvoked);
        ViewObject->SetBoolField(
            TEXT("basecolor_readback_succeeded"),
            View.bBaseColorReadbackSucceeded);
        ViewObject->SetNumberField(
            TEXT("basecolor_readback_pixels"),
            View.BaseColorReadbackPixelCount);
        ViewObject->SetNumberField(
            TEXT("basecolor_non_clear_pixels"),
            View.BaseColorNonClearPixelCount);
        ViewObject->SetNumberField(
            TEXT("depth_requested_format"),
            View.DepthRequestedFormat);
        ViewObject->SetNumberField(
            TEXT("depth_actual_format"),
            View.DepthActualFormat);
        ViewObject->SetNumberField(
            TEXT("depth_requested_size_x"),
            View.DepthRequestedSizeX);
        ViewObject->SetNumberField(
            TEXT("depth_requested_size_y"),
            View.DepthRequestedSizeY);
        ViewObject->SetNumberField(
            TEXT("depth_actual_size_x"),
            View.DepthActualSizeX);
        ViewObject->SetNumberField(
            TEXT("depth_actual_size_y"),
            View.DepthActualSizeY);
        ViewObject->SetBoolField(
            TEXT("depth_resource_valid"),
            View.bDepthRenderTargetResourceValid);
        ViewObject->SetBoolField(
            TEXT("depth_rhi_valid"),
            View.bDepthRenderTargetRHIValid);
        ViewObject->SetBoolField(
            TEXT("depth_capture_invoked"),
            View.bDepthCaptureInvoked);
        ViewObject->SetBoolField(
            TEXT("depth_readback_succeeded"),
            View.bDepthReadbackSucceeded);
        ViewObject->SetNumberField(
            TEXT("depth_readback_pixels"),
            View.DepthReadbackPixelCount);
        ViewObject->SetBoolField(
            TEXT("has_finite_depth_range"),
            View.bHasFiniteDepthRange);
        ViewObject->SetNumberField(TEXT("raw_depth_minimum"), View.RawDepthMinimum);
        ViewObject->SetNumberField(TEXT("raw_depth_maximum"), View.RawDepthMaximum);
        ViewObject->SetNumberField(TEXT("depth_clear_sentinel"), View.DepthClearSentinel);
        ViewObject->SetNumberField(
            TEXT("raw_depth_finite_pixels"),
            View.RawDepthFinitePixelCount);
        ViewObject->SetNumberField(
            TEXT("raw_depth_non_finite_pixels"),
            View.RawDepthNonFinitePixelCount);
        ViewObject->SetNumberField(
            TEXT("raw_depth_clear_sentinel_pixels"),
            View.RawDepthClearSentinelPixelCount);
        ViewObject->SetNumberField(
            TEXT("raw_depth_non_clear_pixels"),
            View.RawDepthNonClearPixelCount);
        ViewObject->SetNumberField(
            TEXT("raw_depth_below_or_equal_near_pixels"),
            View.RawDepthBelowOrEqualNearPixelCount);
        ViewObject->SetNumberField(
            TEXT("raw_depth_in_range_pixels"),
            View.RawDepthInRangePixelCount);
        ViewObject->SetNumberField(
            TEXT("raw_depth_above_or_equal_far_pixels"),
            View.RawDepthAboveOrEqualFarPixelCount);
        ViewObject->SetNumberField(TEXT("depth_hit_pixels"), View.DepthHitPixelCount);
        ViewObject->SetNumberField(
            TEXT("occupied_lookup_pixels"),
            View.OccupiedLookupPixelCount);
        ViewObject->SetNumberField(TEXT("winning_voxels"), View.WinningVoxelCount);
        ViewObject->SetStringField(TEXT("fallback_reason"), View.FallbackReason);
        ViewValues.Add(MakeShared<FJsonValueObject>(ViewObject));
    }
    Root->SetArrayField(TEXT("color_capture_views"), ViewValues);

    Root->SetStringField(
        TEXT("color_note"),
        TEXT("Color uses Deferred SCS_BaseColor plus SCS_SceneDepth only; no lit SceneColor fallback is permitted. Unhit occupied voxels are explicit #808080."));
    Root->SetStringField(
        TEXT("scope_note"),
        TEXT("MVP surface voxelization and six-axis BaseColor capture only: static collision-enabled StaticMesh/ISM/HISM; no Landscape, Nanite fallback, Foliage, PCG, Skeletal Mesh, or Forward renderer. General World Partition is unsupported; only the allow-listed small FirstPerson template map is synchronously fully loaded."));

    FString Json;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Json);
    if (!FJsonSerializer::Serialize(Root, Writer) ||
        !FFileHelper::SaveStringToFile(Json, *ReportPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
    {
        OutError = FString::Printf(TEXT("Failed to write report: %s"), *ReportPath);
        return false;
    }

    Result.ReportPath = ReportPath;
    return true;
}
} // namespace

FVoxelMapBakeOptions FVoxelMapBaker::MakeDefaultOptionsForWorld(UWorld* World)
{
    FVoxelMapBakeOptions Options;
    Options.SourceMapPath = World ? World->GetOutermost()->GetName() : TEXT("/Game/Unknown");
    const FString SourceName = FPackageName::GetLongPackageAssetName(Options.SourceMapPath);
    Options.OutputMapPath = FString::Printf(TEXT("/Game/VoxelMapMVP/Maps/%s_Voxelized"), *SourceName);
    Options.DataAssetPath = FString::Printf(TEXT("/Game/VoxelMapMVP/Data/VM_%s"), *SourceName);
    Options.ReportPath = FPaths::Combine(TEXT("VoxelMapMVP"), TEXT("BakeReport.json"));
    return Options;
}

bool FVoxelMapBaker::BakeWorldAndSave(
    UWorld* World,
    const FVoxelMapBakeOptions& Options,
    FVoxelMapBakeResult& OutResult)
{
    OutResult = FVoxelMapBakeResult();
    OutResult.DataAssetPath = Options.DataAssetPath;
    OutResult.OutputMapPath = Options.OutputMapPath;
    OutResult.bWorldPartitioned = World && World->IsPartitionedWorld();

    if (!World)
    {
        OutResult.Error = TEXT("No world was supplied.");
        return false;
    }
    if (Options.VoxelSize < 5.0f || Options.VoxelSize > 500.0f)
    {
        OutResult.Error = TEXT("VoxelSize must be between 5 cm and 500 cm.");
        return false;
    }
    if (!FPackageName::IsValidLongPackageName(Options.OutputMapPath) ||
        !FPackageName::IsValidLongPackageName(Options.DataAssetPath))
    {
        OutResult.Error = TEXT("OutputMap or DataAsset is not a valid long package name.");
        return false;
    }
    if (Options.OutputMapPath.Equals(Options.SourceMapPath, ESearchCase::IgnoreCase))
    {
        OutResult.Error = TEXT("Output map must differ from the source map.");
        return false;
    }

    const double StartTime = FPlatformTime::Seconds();

    // Narrow WP exception for the known small UE 5.8 First Person template map.
    // Hard references remain alive through collection and Save-As, preventing cells
    // from unloading midway. Any other partitioned world fails closed.
    TArray<FWorldPartitionReference> LoadedWorldPartitionActorReferences;
    if (OutResult.bWorldPartitioned)
    {
        static const FString AllowedSmallWorldPartitionMap = TEXT("/Game/FirstPerson/Lvl_FirstPerson");
        constexpr int32 MaxWorldPartitionActorDescriptors = 2000;
        if (!Options.SourceMapPath.Equals(AllowedSmallWorldPartitionMap, ESearchCase::CaseSensitive))
        {
            OutResult.Error = FString::Printf(
                TEXT("World Partition is outside the general MVP scope. Only %s is allow-listed for bounded full-load bake."),
                *AllowedSmallWorldPartitionMap);
            return false;
        }

        UWorldPartition* WorldPartition = World->GetWorldPartition();
        if (!WorldPartition || !WorldPartition->IsInitialized())
        {
            OutResult.Error = TEXT("The allow-listed World Partition is not initialized.");
            return false;
        }

        WorldPartition->ForEachActorDescContainerInstance(
            [&OutResult](UActorDescContainerInstance* ContainerInstance)
            {
                if (ContainerInstance)
                {
                    OutResult.WorldPartitionActorDescriptorCount +=
                        static_cast<int32>(ContainerInstance->GetActorDescInstanceCount());
                }
            });

        if (OutResult.WorldPartitionActorDescriptorCount <= 0 ||
            OutResult.WorldPartitionActorDescriptorCount > MaxWorldPartitionActorDescriptors)
        {
            OutResult.Error = FString::Printf(
                TEXT("World Partition descriptor count %d is outside the bounded range 1..%d."),
                OutResult.WorldPartitionActorDescriptorCount,
                MaxWorldPartitionActorDescriptors);
            return false;
        }

        WorldPartition->LoadAllActors(LoadedWorldPartitionActorReferences);
        OutResult.WorldPartitionLoadedReferenceCount = LoadedWorldPartitionActorReferences.Num();
        if (OutResult.WorldPartitionLoadedReferenceCount != OutResult.WorldPartitionActorDescriptorCount)
        {
            OutResult.Error = FString::Printf(
                TEXT("World Partition full-load verification failed: %d descriptors but %d hard references."),
                OutResult.WorldPartitionActorDescriptorCount,
                OutResult.WorldPartitionLoadedReferenceCount);
            return false;
        }

        OutResult.bWorldPartitionFullyLoaded = true;
        UE_LOG(
            LogVoxelMapMVP,
            Display,
            TEXT("World Partition bounded full-load verified: descriptors=%d references=%d"),
            OutResult.WorldPartitionActorDescriptorCount,
            OutResult.WorldPartitionLoadedReferenceCount);
    }

    World->FlushLevelStreaming(EFlushLevelStreamingType::Full);
    World->UpdateWorldComponents(true, false);

    TArray<FMeshWorkItem> WorkItems;
    FCollectionStats CollectionStats;
    CollectWorkItems(World, WorkItems, CollectionStats);
    OutResult.SourceActorCount = CollectionStats.ActorCount;
    OutResult.SourceComponentCount = CollectionStats.ComponentCount;
    OutResult.SourceMeshInstanceCount = CollectionStats.MeshInstanceCount;
    OutResult.FilteredHidden = CollectionStats.FilteredHidden;
    OutResult.FilteredMovable = CollectionStats.FilteredMovable;
    OutResult.FilteredNoCollision = CollectionStats.FilteredNoCollision;
    OutResult.FilteredSky = CollectionStats.FilteredSky;
    OutResult.FilteredNoMesh = CollectionStats.FilteredNoMesh;

    if (WorkItems.IsEmpty())
    {
        OutResult.Error = TEXT("No eligible StaticMeshComponent, ISM, or HISM instances were found.");
        return false;
    }

    FBox WorldBounds(ForceInit);
    TSet<UStaticMesh*> UniqueMeshes;
    for (const FMeshWorkItem& Item : WorkItems)
    {
        WorldBounds += Item.Mesh->GetBoundingBox().TransformBy(Item.WorldTransform);
        UniqueMeshes.Add(Item.Mesh);
    }
    OutResult.UniqueMeshCount = UniqueMeshes.Num();

    if (!WorldBounds.IsValid)
    {
        OutResult.Error = TEXT("Eligible mesh bounds were invalid.");
        return false;
    }

    const double VoxelSize = static_cast<double>(Options.VoxelSize);
    const FVector3d Origin(
        FMath::FloorToDouble(WorldBounds.Min.X / VoxelSize) * VoxelSize,
        FMath::FloorToDouble(WorldBounds.Min.Y / VoxelSize) * VoxelSize,
        FMath::FloorToDouble(WorldBounds.Min.Z / VoxelSize) * VoxelSize);
    const FIntVector MaxCell = ToCellCoord(FVector3d(WorldBounds.Max), Origin, VoxelSize);
    const FIntVector Dimensions = MaxCell + FIntVector(1);
    if (Dimensions.X <= 0 || Dimensions.Y <= 0 || Dimensions.Z <= 0 ||
        Dimensions.X > Options.MaxAxisVoxels ||
        Dimensions.Y > Options.MaxAxisVoxels ||
        Dimensions.Z > Options.MaxAxisVoxels)
    {
        OutResult.Error = FString::Printf(
            TEXT("Bake bounds require %d x %d x %d cells; maximum axis is %d."),
            Dimensions.X,
            Dimensions.Y,
            Dimensions.Z,
            Options.MaxAxisVoxels);
        return false;
    }

    TSet<FIntVector> OccupiedCells;
    OccupiedCells.Reserve(FMath::Min(Options.MaxOccupiedVoxels, WorkItems.Num() * 512));
    const FVector3d HalfExtent(VoxelSize * 0.5);

    for (const FMeshWorkItem& Item : WorkItems)
    {
        FMeshDescription* MeshDescription = Item.Mesh->GetMeshDescription(0);
        if (!MeshDescription)
        {
            ++OutResult.FilteredNoMeshDescription;
            continue;
        }

        const FStaticMeshConstAttributes Attributes(*MeshDescription);
        const TVertexAttributesConstRef<FVector3f> VertexPositions = Attributes.GetVertexPositions();
        OutResult.SourceTriangleInstanceCount += MeshDescription->Triangles().Num();

        for (const FTriangleID TriangleID : MeshDescription->Triangles().GetElementIDs())
        {
            const TArrayView<const FVertexInstanceID> VertexInstances =
                MeshDescription->GetTriangleVertexInstances(TriangleID);
            if (VertexInstances.Num() != 3)
            {
                continue;
            }

            const FVector3d A = FVector3d(Item.WorldTransform.TransformPosition(
                FVector(VertexPositions[MeshDescription->GetVertexInstanceVertex(VertexInstances[0])])));
            const FVector3d B = FVector3d(Item.WorldTransform.TransformPosition(
                FVector(VertexPositions[MeshDescription->GetVertexInstanceVertex(VertexInstances[1])])));
            const FVector3d C = FVector3d(Item.WorldTransform.TransformPosition(
                FVector(VertexPositions[MeshDescription->GetVertexInstanceVertex(VertexInstances[2])])));

            const FVector3d TriangleMin(
                FMath::Min3(A.X, B.X, C.X),
                FMath::Min3(A.Y, B.Y, C.Y),
                FMath::Min3(A.Z, B.Z, C.Z));
            const FVector3d TriangleMax(
                FMath::Max3(A.X, B.X, C.X),
                FMath::Max3(A.Y, B.Y, C.Y),
                FMath::Max3(A.Z, B.Z, C.Z));
            FIntVector MinCell = ToCellCoord(TriangleMin, Origin, VoxelSize);
            FIntVector MaxTriangleCell = ToCellCoord(TriangleMax, Origin, VoxelSize);
            MinCell.X = FMath::Clamp(MinCell.X, 0, Dimensions.X - 1);
            MinCell.Y = FMath::Clamp(MinCell.Y, 0, Dimensions.Y - 1);
            MinCell.Z = FMath::Clamp(MinCell.Z, 0, Dimensions.Z - 1);
            MaxTriangleCell.X = FMath::Clamp(MaxTriangleCell.X, 0, Dimensions.X - 1);
            MaxTriangleCell.Y = FMath::Clamp(MaxTriangleCell.Y, 0, Dimensions.Y - 1);
            MaxTriangleCell.Z = FMath::Clamp(MaxTriangleCell.Z, 0, Dimensions.Z - 1);

            const int64 CandidateCount =
                static_cast<int64>(MaxTriangleCell.X - MinCell.X + 1) *
                static_cast<int64>(MaxTriangleCell.Y - MinCell.Y + 1) *
                static_cast<int64>(MaxTriangleCell.Z - MinCell.Z + 1);
            OutResult.CandidateTests += CandidateCount;
            if (OutResult.CandidateTests > Options.MaxCandidateTests)
            {
                OutResult.Error = FString::Printf(
                    TEXT("Candidate test limit exceeded (%lld > %lld). Increase voxel size or narrow the source geometry."),
                    OutResult.CandidateTests,
                    Options.MaxCandidateTests);
                return false;
            }

            for (int32 Z = MinCell.Z; Z <= MaxTriangleCell.Z; ++Z)
            {
                for (int32 Y = MinCell.Y; Y <= MaxTriangleCell.Y; ++Y)
                {
                    for (int32 X = MinCell.X; X <= MaxTriangleCell.X; ++X)
                    {
                        const FIntVector Cell(X, Y, Z);
                        const FVector3d Center =
                            Origin +
                            (FVector3d(Cell.X, Cell.Y, Cell.Z) + FVector3d(0.5)) * VoxelSize;
                        if (TriangleIntersectsBox(Center, HalfExtent, A, B, C))
                        {
                            OccupiedCells.Add(Cell);
                            if (OccupiedCells.Num() > Options.MaxOccupiedVoxels)
                            {
                                OutResult.Error = FString::Printf(
                                    TEXT("Occupied voxel limit exceeded (%d > %d). Increase voxel size or narrow the source geometry."),
                                    OccupiedCells.Num(),
                                    Options.MaxOccupiedVoxels);
                                return false;
                            }
                        }
                    }
                }
            }
        }
    }

    if (OccupiedCells.IsEmpty())
    {
        OutResult.Error = TEXT("Voxelization completed but produced zero occupied cells.");
        return false;
    }

    TMap<FIntVector, uint64> BlockMasks;
    for (const FIntVector& Cell : OccupiedCells)
    {
        const FIntVector BlockCoord(Cell.X / 4, Cell.Y / 4, Cell.Z / 4);
        const int32 LocalX = Cell.X & 3;
        const int32 LocalY = Cell.Y & 3;
        const int32 LocalZ = Cell.Z & 3;
        const uint32 BitIndex = static_cast<uint32>(LocalX + 4 * LocalY + 16 * LocalZ);
        BlockMasks.FindOrAdd(BlockCoord) |= (uint64(1) << BitIndex);
    }

    TArray<FVoxelMapBlock> Blocks;
    Blocks.Reserve(BlockMasks.Num());
    for (const TPair<FIntVector, uint64>& Pair : BlockMasks)
    {
        FVoxelMapBlock& Block = Blocks.AddDefaulted_GetRef();
        Block.BlockCoord = Pair.Key;
        Block.OccupancyMask = Pair.Value;
    }
    Blocks.Sort([](const FVoxelMapBlock& Left, const FVoxelMapBlock& Right)
    {
        if (Left.BlockCoord.Z != Right.BlockCoord.Z)
        {
            return Left.BlockCoord.Z < Right.BlockCoord.Z;
        }
        if (Left.BlockCoord.Y != Right.BlockCoord.Y)
        {
            return Left.BlockCoord.Y < Right.BlockCoord.Y;
        }
        return Left.BlockCoord.X < Right.BlockCoord.X;
    });

    OutResult.OccupiedVoxelCount = OccupiedCells.Num();
    OutResult.BlockCount = Blocks.Num();
    OutResult.DataHash = BuildDataHash(Blocks);

    // Color capture is strictly additive and runs only after canonical geometry,
    // sorting, and Geometry/DataHash are final. It must finish before an existing
    // output world is loaded, because that load replaces the source editor world.
    TArray<UPrimitiveComponent*> ColorShowOnlyComponents;
    ColorShowOnlyComponents.Reserve(WorkItems.Num());
    TSet<UPrimitiveComponent*> UniqueColorShowOnlyComponents;
    for (const FMeshWorkItem& Item : WorkItems)
    {
        UPrimitiveComponent* Component = Item.SourceComponent;
        if (Component && !UniqueColorShowOnlyComponents.Contains(Component))
        {
            UniqueColorShowOnlyComponents.Add(Component);
            ColorShowOnlyComponents.Add(Component);
        }
    }

    FVoxelMapColorCaptureSettings ColorSettings;
    ColorSettings.MinViewResolution = Options.ColorMinViewResolution;
    ColorSettings.MaxViewResolution = Options.ColorMaxViewResolution;
    ColorSettings.PixelsPerVoxel = Options.ColorPixelsPerVoxel;
    ColorSettings.MinimumAcceptedCoverage = Options.MinimumColorCoverage;

    FVoxelMapColorCaptureResult ColorCapture;
    if (!FVoxelMapColorCapture::Capture(
            World,
            WorldBounds,
            Origin,
            VoxelSize,
            Blocks,
            ColorShowOnlyComponents,
            ColorSettings,
            ColorCapture))
    {
        OutResult.Error = FString::Printf(
            TEXT("BaseColor capture failed closed: %s"),
            *ColorCapture.Error);
        return false;
    }

    OutResult.bColorCaptureComplete = ColorCapture.bComplete;
    OutResult.bColorCaptureSucceededWithFallback =
        ColorCapture.bSucceededWithFallback;
    OutResult.ColorMode = ColorCapture.ColorMode;
    OutResult.ColorCaptureVersion = ColorCapture.CaptureVersion;
    OutResult.ColorCaptureStatus = ColorCapture.CaptureStatus;
    OutResult.ColorHash = ColorCapture.ColorHash;
    OutResult.CaptureConfigHash = ColorCapture.ConfigHash;
    OutResult.ColorCaptureDiagnosticSummary = ColorCapture.DiagnosticSummary;
    OutResult.RequestedShowOnlyComponentCount =
        ColorCapture.RequestedShowOnlyComponentCount;
    OutResult.EligibleShowOnlyComponentCount =
        ColorCapture.EligibleShowOnlyComponentCount;
    OutResult.RenderStateCreatedComponentCount =
        ColorCapture.RenderStateCreatedComponentCount;
    OutResult.ValidPrimitiveSceneIdComponentCount =
        ColorCapture.ValidPrimitiveSceneIdComponentCount;
    OutResult.NonNullSceneProxyComponentCount =
        ColorCapture.NonNullSceneProxyComponentCount;
    OutResult.ViewsWithRenderWriteCount =
        ColorCapture.ViewsWithRenderWriteCount;
    OutResult.AllClearDepthViewCount =
        ColorCapture.AllClearDepthViewCount;
    OutResult.InRangeDepthViewCount =
        ColorCapture.InRangeDepthViewCount;
    OutResult.OccupiedLookupViewCount =
        ColorCapture.OccupiedLookupViewCount;
    OutResult.bAllViewsClearDepth = ColorCapture.bAllViewsClearDepth;
    OutResult.ColorCount = ColorCapture.PackedColors.Num();
    OutResult.CapturedColorVoxelCount = ColorCapture.CapturedVoxelCount;
    OutResult.FallbackColorVoxelCount = ColorCapture.FallbackVoxelCount;
    OutResult.UniqueColorCount = ColorCapture.UniqueColorCount;
    OutResult.ColorCoverage = ColorCapture.Coverage;
    OutResult.ColorFallbackReasons = ColorCapture.FallbackReasons;
    OutResult.ColorCaptureViews = ColorCapture.Views;

    if (!ValidateColorConsistency(
            Options,
            OutResult,
            ColorCapture.PackedColors.Num(),
            OutResult.Error))
    {
        return false;
    }

    UMaterialInterface* PreviewMaterial = nullptr;
    if (!FVoxelMapPreviewMaterial::EnsurePersistentMaterial(
            PreviewMaterial,
            OutResult.Error))
    {
        return false;
    }
    OutResult.PreviewMaterialPath = FVoxelMapPreviewMaterial::AssetPath;
    const TStrongObjectPtr<UMaterialInterface> PreviewMaterialGuard(PreviewMaterial);

    OutResult.BakeSeconds = FPlatformTime::Seconds() - StartTime;

    UVoxelMapDataAsset* DataAsset = nullptr;
    if (!SaveDataAsset(
            Options.DataAssetPath,
            Options,
            OutResult,
            Origin,
            WorldBounds,
            Blocks,
            ColorCapture.PackedColors,
            DataAsset,
            OutResult.Error))
    {
        return false;
    }

    FString ExistingOutputMapFilename;
    const bool bOutputMapExists =
        FPackageName::DoesPackageExist(Options.OutputMapPath, &ExistingOutputMapFilename);
    UWorld* WorldToSave = World;
    AVoxelMapPreviewActor* PreviewActor = nullptr;
    const TStrongObjectPtr<UVoxelMapDataAsset> DataAssetGuard(DataAsset);

    if (bOutputMapExists)
    {
        // Repeated Save-As over an existing WP map deletes its external actor
        // packages while AssetRegistry may still be gathering them. Refreshing
        // the existing output map in place avoids stale-file and CleanupWorld
        // warnings and preserves the stable output package name.
        LoadedWorldPartitionActorReferences.Empty();
        WorkItems.Empty();
        OccupiedCells.Empty();
        UniqueMeshes.Empty();

        WorldToSave = UEditorLoadingAndSavingUtils::LoadMap(ExistingOutputMapFilename);
        if (!WorldToSave ||
            !WorldToSave->GetOutermost()->GetName().Equals(Options.OutputMapPath, ESearchCase::CaseSensitive))
        {
            OutResult.Error = FString::Printf(
                TEXT("Failed to load existing output map for in-place refresh: %s"),
                *ExistingOutputMapFilename);
            return false;
        }

        int32 PreviewActorCount = 0;
        for (TActorIterator<AVoxelMapPreviewActor> ActorIt(WorldToSave); ActorIt; ++ActorIt)
        {
            PreviewActor = *ActorIt;
            ++PreviewActorCount;
        }
        if (PreviewActorCount != 1 || !PreviewActor)
        {
            OutResult.Error = FString::Printf(
                TEXT("Existing output map must contain exactly one VoxelMapPreviewActor; found %d."),
                PreviewActorCount);
            return false;
        }

        OutResult.bOutputRefreshedInPlace = true;
        UE_LOG(
            LogVoxelMapMVP,
            Display,
            TEXT("VOXELMAP_OUTPUT_REFRESH_IN_PLACE map=%s preview_actors=%d"),
            *Options.OutputMapPath,
            PreviewActorCount);
    }
    else
    {
        PreviewActor = WorldToSave->SpawnActor<AVoxelMapPreviewActor>(
            AVoxelMapPreviewActor::StaticClass(),
            FTransform::Identity);
        if (!PreviewActor)
        {
            OutResult.Error = TEXT("Failed to spawn the voxel preview actor.");
            return false;
        }

        if (Options.bHideIncludedSourceMeshes)
        {
            TSet<UStaticMeshComponent*> IncludedComponents;
            for (const FMeshWorkItem& Item : WorkItems)
            {
                IncludedComponents.Add(Item.SourceComponent);
            }
            for (UStaticMeshComponent* Component : IncludedComponents)
            {
                if (Component)
                {
                    Component->Modify();
                    Component->SetVisibility(false, true);
                    Component->SetHiddenInGame(true);
                    Component->MarkRenderStateDirty();
                }
            }
        }
    }

    PreviewActor->Modify();
    PreviewActor->PreviewInstances->Modify();
#if WITH_EDITOR
    PreviewActor->SetActorLabel(TEXT("VoxelMapMVP_Preview"));
#endif
    PreviewActor->VoxelData = DataAssetGuard.Get();
    PreviewActor->PreviewInstances->SetMaterial(0, PreviewMaterialGuard.Get());
    PreviewActor->RebuildPreview();
    PreviewActor->MarkPackageDirty();
    PreviewActor->PreviewInstances->MarkPackageDirty();
    WorldToSave->MarkPackageDirty();

    if (!UEditorLoadingAndSavingUtils::SaveMap(WorldToSave, Options.OutputMapPath))
    {
        OutResult.Error = FString::Printf(TEXT("Failed to save output map: %s"), *Options.OutputMapPath);
        return false;
    }

    const FString DataAssetFilename =
        FPackageName::LongPackageNameToFilename(Options.DataAssetPath, FPackageName::GetAssetPackageExtension());
    const FString OutputMapFilename =
        FPackageName::LongPackageNameToFilename(Options.OutputMapPath, FPackageName::GetMapPackageExtension());
    OutResult.DataAssetBytes = IFileManager::Get().FileSize(*DataAssetFilename);
    OutResult.OutputMapBytes = IFileManager::Get().FileSize(*OutputMapFilename);

    if (!WriteReport(Options, OutResult, OutResult.Error))
    {
        return false;
    }

    OutResult.bSuccess = true;
    UE_LOG(
        LogVoxelMapMVP,
        Display,
        TEXT("VOXELMAP_BAKE_SUCCESS voxels=%d blocks=%d actors=%d components=%d instances=%d ")
        TEXT("triangles=%lld candidates=%lld seconds=%.3f geometry_hash=%s color_status=%s ")
        TEXT("captured=%d fallback=%d coverage=%.6f unique=%d color_hash=%s config_hash=%s ")
        TEXT("data=%s map=%s report=%s"),
        OutResult.OccupiedVoxelCount,
        OutResult.BlockCount,
        OutResult.SourceActorCount,
        OutResult.SourceComponentCount,
        OutResult.SourceMeshInstanceCount,
        OutResult.SourceTriangleInstanceCount,
        OutResult.CandidateTests,
        OutResult.BakeSeconds,
        *OutResult.DataHash,
        *OutResult.ColorCaptureStatus,
        OutResult.CapturedColorVoxelCount,
        OutResult.FallbackColorVoxelCount,
        OutResult.ColorCoverage,
        OutResult.UniqueColorCount,
        *OutResult.ColorHash,
        *OutResult.CaptureConfigHash,
        *Options.DataAssetPath,
        *Options.OutputMapPath,
        *OutResult.ReportPath);
    return true;
}
