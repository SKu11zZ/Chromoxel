#include "VoxelMapBakeCommandlet.h"

#include "Engine/World.h"
#include "FileHelpers.h"
#include "Misc/CommandLine.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "VoxelMapBaker.h"

DEFINE_LOG_CATEGORY_STATIC(LogVoxelMapBakeCommandlet, Log, All);

UVoxelMapBakeCommandlet::UVoxelMapBakeCommandlet()
{
    IsClient = true;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UVoxelMapBakeCommandlet::Main(const FString& Params)
{
    FString SourceMap = TEXT("/Game/FirstPerson/Lvl_FirstPerson");
    FString OutputMap = TEXT("/Game/VoxelMapMVP/Maps/Lvl_FirstPerson_Voxelized");
    FString DataAsset = TEXT("/Game/VoxelMapMVP/Data/VM_Lvl_FirstPerson");
    FString Report = FPaths::Combine(TEXT("VoxelMapMVP"), TEXT("BakeReport.json"));
    float VoxelSize = 25.0f;

    FParse::Value(*Params, TEXT("Map="), SourceMap);
    FParse::Value(*Params, TEXT("OutputMap="), OutputMap);
    FParse::Value(*Params, TEXT("DataAsset="), DataAsset);
    FParse::Value(*Params, TEXT("Report="), Report);
    FParse::Value(*Params, TEXT("VoxelSize="), VoxelSize);

    FString SourceFilename = SourceMap;
    if (FPackageName::IsValidLongPackageName(SourceMap))
    {
        SourceFilename =
            FPackageName::LongPackageNameToFilename(SourceMap, FPackageName::GetMapPackageExtension());
    }

    if (!FPaths::FileExists(SourceFilename))
    {
        UE_LOG(LogVoxelMapBakeCommandlet, Error, TEXT("Source map does not exist: %s"), *SourceFilename);
        return 2;
    }

    UWorld* World = UEditorLoadingAndSavingUtils::LoadMap(SourceFilename);
    if (!World)
    {
        UE_LOG(LogVoxelMapBakeCommandlet, Error, TEXT("Failed to load source map: %s"), *SourceFilename);
        return 3;
    }

    FVoxelMapBakeOptions Options = FVoxelMapBaker::MakeDefaultOptionsForWorld(World);
    Options.SourceMapPath = SourceMap;
    Options.OutputMapPath = OutputMap;
    Options.DataAssetPath = DataAsset;
    Options.ReportPath = Report;
    Options.VoxelSize = VoxelSize;

    FVoxelMapBakeResult Result;
    if (!FVoxelMapBaker::BakeWorldAndSave(World, Options, Result))
    {
        UE_LOG(LogVoxelMapBakeCommandlet, Error, TEXT("VOXELMAP_BAKE_FAILED: %s"), *Result.Error);
        return 4;
    }

    UE_LOG(
        LogVoxelMapBakeCommandlet,
        Display,
        TEXT("VOXELMAP_COMMANDLET_COMPLETE voxels=%d blocks=%d geometry_hash=%s ")
        TEXT("color_status=%s captured=%d fallback=%d coverage=%.6f color_hash=%s config_hash=%s"),
        Result.OccupiedVoxelCount,
        Result.BlockCount,
        *Result.DataHash,
        *Result.ColorCaptureStatus,
        Result.CapturedColorVoxelCount,
        Result.FallbackColorVoxelCount,
        Result.ColorCoverage,
        *Result.ColorHash,
        *Result.CaptureConfigHash);
    return 0;
}
