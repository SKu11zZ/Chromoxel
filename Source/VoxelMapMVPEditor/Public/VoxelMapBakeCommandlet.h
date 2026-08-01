#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "VoxelMapBakeCommandlet.generated.h"

UCLASS()
class VOXELMAPMVPEDITOR_API UVoxelMapBakeCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UVoxelMapBakeCommandlet();
    virtual int32 Main(const FString& Params) override;
};
