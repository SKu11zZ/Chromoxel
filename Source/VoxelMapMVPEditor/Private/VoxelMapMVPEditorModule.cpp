#include "Modules/ModuleManager.h"

#include "Editor.h"
#include "Engine/Selection.h"
#include "Framework/Commands/UIAction.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Volume.h"
#include "HAL/IConsoleManager.h"
#include "Misc/MessageDialog.h"
#include "Misc/PackageName.h"
#include "ToolMenus.h"
#include "VoxelMapBaker.h"

#define LOCTEXT_NAMESPACE "FVoxelMapMVPEditorModule"

DEFINE_LOG_CATEGORY_STATIC(LogVoxelMapMVPEditor, Log, All);

class FVoxelMapMVPEditorModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        UToolMenus::RegisterStartupCallback(
            FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FVoxelMapMVPEditorModule::RegisterMenus));

        BakeConsoleCommand = IConsoleManager::Get().RegisterConsoleCommand(
            TEXT("VoxelMapMVP.BakeCurrent"),
            TEXT("Bake current editor world. Usage: VoxelMapMVP.BakeCurrent [10|25|50] [World|Selected|Bounds]"),
            FConsoleCommandWithArgsDelegate::CreateRaw(this, &FVoxelMapMVPEditorModule::BakeFromConsoleArgs),
            ECVF_Default);
    }

    virtual void ShutdownModule() override
    {
        UToolMenus::UnRegisterStartupCallback(this);
        UToolMenus::UnregisterOwner(this);
        if (BakeConsoleCommand)
        {
            IConsoleManager::Get().UnregisterConsoleObject(BakeConsoleCommand);
            BakeConsoleCommand = nullptr;
        }
    }

private:
    static FString ScopeToken(EVoxelMapBakeScope Scope)
    {
        switch (Scope)
        {
        case EVoxelMapBakeScope::SelectedActors:
            return TEXT("Selected");
        case EVoxelMapBakeScope::Bounds:
            return TEXT("Bounds");
        default:
            return TEXT("World");
        }
    }

    static void ApplyDistinctOutputPaths(
        const UWorld* World,
        float VoxelSize,
        EVoxelMapBakeScope Scope,
        FVoxelMapBakeOptions& Options)
    {
        const FString SourceName = FPackageName::GetLongPackageAssetName(
            World ? World->GetOutermost()->GetName() : TEXT("Unknown"));
        const FString Token = ScopeToken(Scope);
        const int32 RoundedVoxelSize = FMath::RoundToInt(VoxelSize);
        Options.OutputMapPath = FString::Printf(
            TEXT("/Game/VoxelMapMVP/Maps/%s_Voxelized_%s_%dcm"),
            *SourceName,
            *Token,
            RoundedVoxelSize);
        Options.DataAssetPath = FString::Printf(
            TEXT("/Game/VoxelMapMVP/Data/VM_%s_%s_%dcm"),
            *SourceName,
            *Token,
            RoundedVoxelSize);
        Options.ReportPath = FString::Printf(
            TEXT("VoxelMapMVP/BakeReport_%s_%dcm.json"),
            *Token,
            RoundedVoxelSize);
    }

    static bool ConfigureScope(
        EVoxelMapBakeScope Scope,
        FVoxelMapBakeOptions& Options,
        FString& OutError)
    {
        Options.Scope = Scope;
        if (Scope == EVoxelMapBakeScope::World)
        {
            return true;
        }
        if (!GEditor || !GEditor->GetSelectedActors())
        {
            OutError = TEXT("The editor selection is unavailable.");
            return false;
        }

        USelection* Selection = GEditor->GetSelectedActors();
        if (Scope == EVoxelMapBakeScope::SelectedActors)
        {
            for (FSelectionIterator Iterator(*Selection); Iterator; ++Iterator)
            {
                if (const AActor* Actor = Cast<AActor>(*Iterator))
                {
                    Options.SelectedActorPaths.Add(Actor->GetPathName());
                }
            }
            if (Options.SelectedActorPaths.IsEmpty())
            {
                OutError = TEXT("Select at least one actor before using Selected scope.");
                return false;
            }
            return true;
        }

        FBox CombinedBounds(ForceInit);
        int32 VolumeCount = 0;
        for (FSelectionIterator Iterator(*Selection); Iterator; ++Iterator)
        {
            if (const AVolume* Volume = Cast<AVolume>(*Iterator))
            {
                CombinedBounds += Volume->GetComponentsBoundingBox(true);
                ++VolumeCount;
            }
        }
        if (VolumeCount == 0 || !CombinedBounds.IsValid)
        {
            OutError = TEXT("Select one or more Volume actors before using Bounds scope.");
            return false;
        }
        Options.ScopeBounds = CombinedBounds;
        return true;
    }

    void AddBakeEntry(
        FToolMenuSection& Section,
        const FName Name,
        const FString& Label,
        float VoxelSize,
        EVoxelMapBakeScope Scope)
    {
        Section.AddMenuEntry(
            Name,
            FText::FromString(Label),
            FText::FromString(FString::Printf(
                TEXT("Surface-voxelize %s at %.0f cm, capture all material-slot BaseColors, and incrementally update preview chunks."),
                VoxelMapBakeScopeToString(Scope),
                VoxelSize)),
            FSlateIcon(),
            FUIAction(FExecuteAction::CreateLambda([this, VoxelSize, Scope]()
            {
                BakeCurrentWorld(VoxelSize, Scope);
            })));
    }

    void RegisterMenus()
    {
        FToolMenuOwnerScoped OwnerScoped(this);
        UToolMenu* ToolsMenu = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.MainMenu.Tools"));
        FToolMenuSection& Section = ToolsMenu->FindOrAddSection(TEXT("VoxelMapMVP"));
        AddBakeEntry(Section, TEXT("Chromoxel_World_10"), TEXT("Chromoxel: Bake World — Fine (10 cm)"), 10.0f, EVoxelMapBakeScope::World);
        AddBakeEntry(Section, TEXT("Chromoxel_World_25"), TEXT("Chromoxel: Bake World — Standard (25 cm)"), 25.0f, EVoxelMapBakeScope::World);
        AddBakeEntry(Section, TEXT("Chromoxel_World_50"), TEXT("Chromoxel: Bake World — Coarse (50 cm)"), 50.0f, EVoxelMapBakeScope::World);
        AddBakeEntry(Section, TEXT("Chromoxel_Selected_10"), TEXT("Chromoxel: Bake Selected — Fine (10 cm)"), 10.0f, EVoxelMapBakeScope::SelectedActors);
        AddBakeEntry(Section, TEXT("Chromoxel_Selected_25"), TEXT("Chromoxel: Bake Selected — Standard (25 cm)"), 25.0f, EVoxelMapBakeScope::SelectedActors);
        AddBakeEntry(Section, TEXT("Chromoxel_Selected_50"), TEXT("Chromoxel: Bake Selected — Coarse (50 cm)"), 50.0f, EVoxelMapBakeScope::SelectedActors);
        AddBakeEntry(Section, TEXT("Chromoxel_Bounds_10"), TEXT("Chromoxel: Bake Selected Volume — Fine (10 cm)"), 10.0f, EVoxelMapBakeScope::Bounds);
        AddBakeEntry(Section, TEXT("Chromoxel_Bounds_25"), TEXT("Chromoxel: Bake Selected Volume — Standard (25 cm)"), 25.0f, EVoxelMapBakeScope::Bounds);
        AddBakeEntry(Section, TEXT("Chromoxel_Bounds_50"), TEXT("Chromoxel: Bake Selected Volume — Coarse (50 cm)"), 50.0f, EVoxelMapBakeScope::Bounds);
    }

    void BakeFromConsoleArgs(const TArray<FString>& Args)
    {
        float VoxelSize = 25.0f;
        if (Args.Num() > 0)
        {
            VoxelSize = FCString::Atof(*Args[0]);
        }
        EVoxelMapBakeScope Scope = EVoxelMapBakeScope::World;
        if (Args.Num() > 1)
        {
            if (Args[1].Equals(TEXT("Selected"), ESearchCase::IgnoreCase))
            {
                Scope = EVoxelMapBakeScope::SelectedActors;
            }
            else if (Args[1].Equals(TEXT("Bounds"), ESearchCase::IgnoreCase))
            {
                Scope = EVoxelMapBakeScope::Bounds;
            }
        }
        BakeCurrentWorld(VoxelSize, Scope);
    }

    void BakeCurrentWorld(float VoxelSize, EVoxelMapBakeScope Scope)
    {
        UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
        if (!World)
        {
            UE_LOG(LogVoxelMapMVPEditor, Error, TEXT("Chromoxel: no current editor world."));
            if (!IsRunningCommandlet())
            {
                FMessageDialog::Open(EAppMsgType::Ok, LOCTEXT("NoWorld", "No current editor world is available."));
            }
            return;
        }

        FVoxelMapBakeOptions Options = FVoxelMapBaker::MakeDefaultOptionsForWorld(World);
        Options.VoxelSize = VoxelSize;
        FString ScopeError;
        if (!ConfigureScope(Scope, Options, ScopeError))
        {
            FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(ScopeError));
            return;
        }
        ApplyDistinctOutputPaths(World, VoxelSize, Scope, Options);

        FVoxelMapBakeResult Result;
        if (!FVoxelMapBaker::BakeWorldAndSave(World, Options, Result))
        {
            UE_LOG(LogVoxelMapMVPEditor, Error, TEXT("Chromoxel bake failed: %s"), *Result.Error);
            if (!IsRunningCommandlet() && !Result.bCancelled)
            {
                FMessageDialog::Open(
                    EAppMsgType::Ok,
                    FText::Format(LOCTEXT("BakeFailed", "Chromoxel bake failed:\n{0}"), FText::FromString(Result.Error)));
            }
            return;
        }

        const FString SuccessMessage = FString::Printf(
            TEXT("Chromoxel bake completed.\n\nScope: %s\nVoxel size: %.0f cm\nVoxels: %d\nBlocks: %d\n")
            TEXT("Incremental blocks (reused / changed / removed): %d / %d / %d\n")
            TEXT("Materials: %d slots, %d unique, %d multi-material components\nGeometry Hash: %s\n")
            TEXT("Color: %s (%d captured, %d fallback, %.2f%%)\nColor Hash: %s\nConfig Hash: %s\n")
            TEXT("Map: %s\nData: %s\nReport: %s"),
            *Result.BakeScope,
            Options.VoxelSize,
            Result.OccupiedVoxelCount,
            Result.BlockCount,
            Result.ReusedBlockCount,
            Result.ChangedBlockCount,
            Result.RemovedBlockCount,
            Result.SourceMaterialSlotCount,
            Result.SourceUniqueMaterialCount,
            Result.MultiMaterialComponentCount,
            *Result.DataHash,
            *Result.ColorCaptureStatus,
            Result.CapturedColorVoxelCount,
            Result.FallbackColorVoxelCount,
            Result.ColorCoverage * 100.0f,
            *Result.ColorHash,
            *Result.CaptureConfigHash,
            *Result.OutputMapPath,
            *Result.DataAssetPath,
            *Result.ReportPath);
        UE_LOG(LogVoxelMapMVPEditor, Display, TEXT("%s"), *SuccessMessage);
        if (!IsRunningCommandlet())
        {
            FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(SuccessMessage));
        }
    }

    IConsoleObject* BakeConsoleCommand = nullptr;
};

IMPLEMENT_MODULE(FVoxelMapMVPEditorModule, VoxelMapMVPEditor)

#undef LOCTEXT_NAMESPACE
