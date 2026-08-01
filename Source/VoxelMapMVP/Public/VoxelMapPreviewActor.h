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

    UPROPERTY(EditAnywhere, Category = "Voxel Map")
    TObjectPtr<UVoxelMapDataAsset> VoxelData;

    UFUNCTION(CallInEditor, Category = "Voxel Map")
    void RebuildPreview();

protected:
    virtual void OnConstruction(const FTransform& Transform) override;
};
