#include "VoxelMapPreviewActor.h"

#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Engine/CollisionProfile.h"
#include "Engine/StaticMesh.h"
#include "UObject/ConstructorHelpers.h"
#include "VoxelMapDataAsset.h"

AVoxelMapPreviewActor::AVoxelMapPreviewActor()
{
    PrimaryActorTick.bCanEverTick = false;

    PreviewInstances = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("VoxelPreviewInstances"));
    SetRootComponent(PreviewInstances);
    PreviewInstances->SetMobility(EComponentMobility::Static);
    PreviewInstances->SetCollisionProfileName(UCollisionProfile::NoCollision_ProfileName);
    PreviewInstances->SetGenerateOverlapEvents(false);
    PreviewInstances->SetCastShadow(false);
    PreviewInstances->bReceivesDecals = false;
    PreviewInstances->SetNumCustomDataFloats(3);

    static ConstructorHelpers::FObjectFinder<UStaticMesh> CubeMesh(TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (CubeMesh.Succeeded())
    {
        PreviewInstances->SetStaticMesh(CubeMesh.Object);
    }

}

void AVoxelMapPreviewActor::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    RebuildPreview();
}

void AVoxelMapPreviewActor::RebuildPreview()
{
    PreviewInstances->ClearInstances();
    PreviewInstances->SetNumCustomDataFloats(3);

    if (!VoxelData || VoxelData->VoxelSize <= 0.0f)
    {
        return;
    }

    // Leave a small gap so the voxel grid and curved/stepped silhouettes remain legible.
    const double Scale = static_cast<double>(VoxelData->VoxelSize) / 100.0 * 0.92;
    const FVector InstanceScale(Scale, Scale, Scale);
    int32 CanonicalVoxelIndex = 0;

    for (const FVoxelMapBlock& Block : VoxelData->Blocks)
    {
        uint64 RemainingMask = Block.OccupancyMask;
        while (RemainingMask != 0)
        {
            const uint32 BitIndex = static_cast<uint32>(FMath::CountTrailingZeros64(RemainingMask));
            RemainingMask &= RemainingMask - 1;

            const int32 LocalX = static_cast<int32>(BitIndex & 3u);
            const int32 LocalY = static_cast<int32>((BitIndex >> 2u) & 3u);
            const int32 LocalZ = static_cast<int32>((BitIndex >> 4u) & 3u);
            const FIntVector CellCoord = Block.BlockCoord * 4 + FIntVector(LocalX, LocalY, LocalZ);
            const FVector CellCenter =
                VoxelData->BakeOrigin +
                (FVector(CellCoord) + FVector(0.5)) * static_cast<double>(VoxelData->VoxelSize);

            const uint32 PackedColor = VoxelData->GetPackedVoxelColorOrDefault(CanonicalVoxelIndex);
            const FColor SRGBColor(
                static_cast<uint8>((PackedColor >> 16u) & 0xffu),
                static_cast<uint8>((PackedColor >> 8u) & 0xffu),
                static_cast<uint8>(PackedColor & 0xffu),
                255);
            const FLinearColor LinearColor = FLinearColor::FromSRGBColor(SRGBColor);

            const int32 InstanceIndex =
                PreviewInstances->AddInstance(FTransform(FQuat::Identity, CellCenter, InstanceScale), true);
            PreviewInstances->SetCustomDataValue(InstanceIndex, 0, LinearColor.R, false);
            PreviewInstances->SetCustomDataValue(InstanceIndex, 1, LinearColor.G, false);
            PreviewInstances->SetCustomDataValue(InstanceIndex, 2, LinearColor.B, false);
            ++CanonicalVoxelIndex;
        }
    }

    PreviewInstances->MarkRenderStateDirty();
}
