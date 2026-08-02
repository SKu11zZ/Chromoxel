#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "VoxelMapPreviewActor.generated.h"

class UHierarchicalInstancedStaticMeshComponent;
class UVoxelMapDataAsset;

UCLASS()
class VOXELMAPMVP_API AVoxelMapPreviewActor : public AActor
{
    GENERATED_BODY()

public:
    AVoxelMapPreviewActor();

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map")
    TObjectPtr<UHierarchicalInstancedStaticMeshComponent> PreviewInstances;

    /** 16x16x16-cell preview chunks. Unchanged chunks retain their HISM data. */
    UPROPERTY(VisibleAnywhere, Instanced, Category = "Voxel Map|Incremental")
    TArray<TObjectPtr<UHierarchicalInstancedStaticMeshComponent>> PreviewChunkComponents;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Incremental")
    TArray<FIntVector> PreviewChunkCoords;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Incremental")
    TArray<uint64> PreviewChunkHashes;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Incremental")
    int32 LastReusedPreviewChunkCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Incremental")
    int32 LastRebuiltPreviewChunkCount = 0;

    UPROPERTY(VisibleAnywhere, Category = "Voxel Map|Incremental")
    int32 LastRemovedPreviewChunkCount = 0;

    UPROPERTY(EditAnywhere, Category = "Voxel Map")
    TObjectPtr<UVoxelMapDataAsset> VoxelData;

    UFUNCTION(CallInEditor, Category = "Voxel Map")
    void RebuildPreview();

protected:
    virtual void OnConstruction(const FTransform& Transform) override;
};
