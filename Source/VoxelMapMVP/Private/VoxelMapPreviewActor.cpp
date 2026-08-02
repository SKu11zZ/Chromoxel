#include "VoxelMapPreviewActor.h"

#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Engine/CollisionProfile.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"
#include "UObject/UObjectGlobals.h"
#include "VoxelMapDataAsset.h"

namespace
{
constexpr int32 BlocksPerPreviewChunk = 4;
constexpr uint64 FNVOffset = 1469598103934665603ull;
constexpr uint64 FNVPrime = 1099511628211ull;

struct FPreviewChunkBuild
{
    uint64 Hash = FNVOffset;
    TArray<FTransform> Transforms;
    TArray<FLinearColor> Colors;
};

void AppendHash(uint64& Hash, const void* Data, int64 NumBytes)
{
    const uint8* Bytes = static_cast<const uint8*>(Data);
    for (int64 Index = 0; Index < NumBytes; ++Index)
    {
        Hash ^= Bytes[Index];
        Hash *= FNVPrime;
    }
}

void ConfigurePreviewComponent(
    UHierarchicalInstancedStaticMeshComponent* Component,
    UStaticMesh* CubeMesh)
{
    if (!Component)
    {
        return;
    }
    Component->SetMobility(EComponentMobility::Static);
    Component->SetCollisionProfileName(UCollisionProfile::NoCollision_ProfileName);
    Component->SetGenerateOverlapEvents(false);
    Component->SetCastShadow(false);
    Component->bReceivesDecals = false;
    Component->SetNumCustomDataFloats(3);
    Component->SetStaticMesh(CubeMesh);
}

bool PreviewCoordLess(const FIntVector& Left, const FIntVector& Right)
{
    if (Left.Z != Right.Z)
    {
        return Left.Z < Right.Z;
    }
    if (Left.Y != Right.Y)
    {
        return Left.Y < Right.Y;
    }
    return Left.X < Right.X;
}

int32 FloorDivide(const int32 Value, const int32 PositiveDivisor)
{
    check(PositiveDivisor > 0);
    const int32 Quotient = Value / PositiveDivisor;
    const int32 Remainder = Value % PositiveDivisor;
    return Remainder < 0 ? Quotient - 1 : Quotient;
}

FIntVector ToPreviewChunkCoord(const FIntVector& BlockCoord)
{
    return FIntVector(
        FloorDivide(BlockCoord.X, BlocksPerPreviewChunk),
        FloorDivide(BlockCoord.Y, BlocksPerPreviewChunk),
        FloorDivide(BlockCoord.Z, BlocksPerPreviewChunk));
}
} // namespace

AVoxelMapPreviewActor::AVoxelMapPreviewActor()
{
    PrimaryActorTick.bCanEverTick = false;

    PreviewInstances = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("VoxelPreviewInstances"));
    SetRootComponent(PreviewInstances);

    static ConstructorHelpers::FObjectFinder<UStaticMesh> CubeMesh(TEXT("/Engine/BasicShapes/Cube.Cube"));
    ConfigurePreviewComponent(PreviewInstances, CubeMesh.Succeeded() ? CubeMesh.Object : nullptr);
}

void AVoxelMapPreviewActor::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    RebuildPreview();
}

void AVoxelMapPreviewActor::RebuildPreview()
{
    LastReusedPreviewChunkCount = 0;
    LastRebuiltPreviewChunkCount = 0;
    LastRemovedPreviewChunkCount = 0;

    // v0.2 stored every instance on the root HISM. The root is retained as a
    // stable attachment/material template while v0.3 stores instances in
    // independently reusable 16-cell chunks.
    PreviewInstances->ClearInstances();
    PreviewInstances->SetNumCustomDataFloats(3);

    TMap<FIntVector, int32> ExistingIndices;
    const int32 ExistingCount = FMath::Min3(
        PreviewChunkComponents.Num(),
        PreviewChunkCoords.Num(),
        PreviewChunkHashes.Num());
    for (int32 Index = 0; Index < ExistingCount; ++Index)
    {
        if (IsValid(PreviewChunkComponents[Index]))
        {
            ExistingIndices.FindOrAdd(PreviewChunkCoords[Index], Index);
        }
    }

    TMap<FIntVector, FPreviewChunkBuild> DesiredChunks;
    if (VoxelData && VoxelData->VoxelSize > 0.0f)
    {
        const double Scale = static_cast<double>(VoxelData->VoxelSize) / 100.0 * 0.92;
        const FVector InstanceScale(Scale, Scale, Scale);
        int32 CanonicalVoxelIndex = 0;
        for (const FVoxelMapBlock& Block : VoxelData->Blocks)
        {
            // C++ integer division truncates toward zero. Floor division keeps
            // negative and positive grid quadrants in equally sized chunks.
            const FIntVector PreviewChunkCoord = ToPreviewChunkCoord(Block.BlockCoord);
            FPreviewChunkBuild& Chunk = DesiredChunks.FindOrAdd(PreviewChunkCoord);
            AppendHash(Chunk.Hash, &Block.BlockCoord, sizeof(Block.BlockCoord));
            AppendHash(Chunk.Hash, &Block.OccupancyMask, sizeof(Block.OccupancyMask));

            uint64 RemainingMask = Block.OccupancyMask;
            while (RemainingMask != 0)
            {
                const uint32 BitIndex = static_cast<uint32>(FMath::CountTrailingZeros64(RemainingMask));
                RemainingMask &= RemainingMask - 1;

                const int32 LocalX = static_cast<int32>(BitIndex & 3u);
                const int32 LocalY = static_cast<int32>((BitIndex >> 2u) & 3u);
                const int32 LocalZ = static_cast<int32>((BitIndex >> 4u) & 3u);
                const FIntVector CellCoord =
                    Block.BlockCoord * 4 + FIntVector(LocalX, LocalY, LocalZ);
                const FVector CellCenter =
                    VoxelData->BakeOrigin +
                    (FVector(CellCoord) + FVector(0.5)) *
                        static_cast<double>(VoxelData->VoxelSize);

                const uint32 PackedColor =
                    VoxelData->GetPackedVoxelColorOrDefault(CanonicalVoxelIndex);
                const FColor SRGBColor(
                    static_cast<uint8>((PackedColor >> 16u) & 0xffu),
                    static_cast<uint8>((PackedColor >> 8u) & 0xffu),
                    static_cast<uint8>(PackedColor & 0xffu),
                    255);
                Chunk.Transforms.Add(FTransform(FQuat::Identity, CellCenter, InstanceScale));
                Chunk.Colors.Add(FLinearColor::FromSRGBColor(SRGBColor));
                AppendHash(Chunk.Hash, &CellCoord, sizeof(CellCoord));
                AppendHash(Chunk.Hash, &PackedColor, sizeof(PackedColor));
                ++CanonicalVoxelIndex;
            }
        }
    }

    TArray<FIntVector> DesiredCoords;
    DesiredChunks.GetKeys(DesiredCoords);
    DesiredCoords.Sort(PreviewCoordLess);

    TArray<TObjectPtr<UHierarchicalInstancedStaticMeshComponent>> NewComponents;
    TArray<FIntVector> NewCoords;
    TArray<uint64> NewHashes;
    NewComponents.Reserve(DesiredCoords.Num());
    NewCoords.Reserve(DesiredCoords.Num());
    NewHashes.Reserve(DesiredCoords.Num());
    TSet<int32> RetainedExistingIndices;
    UStaticMesh* CubeMesh = PreviewInstances->GetStaticMesh();
    UMaterialInterface* PreviewMaterial = PreviewInstances->GetMaterial(0);

    for (const FIntVector& Coord : DesiredCoords)
    {
        FPreviewChunkBuild& Chunk = DesiredChunks.FindChecked(Coord);
        UHierarchicalInstancedStaticMeshComponent* Component = nullptr;
        const int32* ExistingIndex = ExistingIndices.Find(Coord);
        const bool bCanReuse =
            ExistingIndex &&
            PreviewChunkComponents.IsValidIndex(*ExistingIndex) &&
            PreviewChunkHashes.IsValidIndex(*ExistingIndex) &&
            IsValid(PreviewChunkComponents[*ExistingIndex]);
        if (bCanReuse)
        {
            Component = PreviewChunkComponents[*ExistingIndex];
            RetainedExistingIndices.Add(*ExistingIndex);
        }
        else
        {
            const FName BaseName(*FString::Printf(
                TEXT("VoxelPreviewChunk_%d_%d_%d"),
                Coord.X,
                Coord.Y,
                Coord.Z));
            Component = NewObject<UHierarchicalInstancedStaticMeshComponent>(
                this,
                MakeUniqueObjectName(this, UHierarchicalInstancedStaticMeshComponent::StaticClass(), BaseName),
                RF_Transactional);
            Component->CreationMethod = EComponentCreationMethod::Instance;
            Component->SetupAttachment(PreviewInstances);
            AddInstanceComponent(Component);
            Component->RegisterComponent();
        }

        ConfigurePreviewComponent(Component, CubeMesh);
        if (PreviewMaterial)
        {
            Component->SetMaterial(0, PreviewMaterial);
        }

        const bool bContentUnchanged =
            bCanReuse && PreviewChunkHashes[*ExistingIndex] == Chunk.Hash;
        if (bContentUnchanged)
        {
            ++LastReusedPreviewChunkCount;
        }
        else
        {
            Component->Modify();
            Component->ClearInstances();
            Component->SetNumCustomDataFloats(3);
            for (int32 InstanceIndex = 0; InstanceIndex < Chunk.Transforms.Num(); ++InstanceIndex)
            {
                const int32 AddedIndex = Component->AddInstance(Chunk.Transforms[InstanceIndex], true);
                const FLinearColor& Color = Chunk.Colors[InstanceIndex];
                Component->SetCustomDataValue(AddedIndex, 0, Color.R, false);
                Component->SetCustomDataValue(AddedIndex, 1, Color.G, false);
                Component->SetCustomDataValue(AddedIndex, 2, Color.B, false);
            }
            Component->MarkRenderStateDirty();
            ++LastRebuiltPreviewChunkCount;
        }

        NewComponents.Add(Component);
        NewCoords.Add(Coord);
        NewHashes.Add(Chunk.Hash);
    }

    for (int32 Index = 0; Index < PreviewChunkComponents.Num(); ++Index)
    {
        UHierarchicalInstancedStaticMeshComponent* Component = PreviewChunkComponents[Index];
        if (IsValid(Component) && !RetainedExistingIndices.Contains(Index))
        {
            RemoveInstanceComponent(Component);
            Component->DestroyComponent();
            ++LastRemovedPreviewChunkCount;
        }
    }

    PreviewChunkComponents = MoveTemp(NewComponents);
    PreviewChunkCoords = MoveTemp(NewCoords);
    PreviewChunkHashes = MoveTemp(NewHashes);
    PreviewInstances->MarkRenderStateDirty();
}
