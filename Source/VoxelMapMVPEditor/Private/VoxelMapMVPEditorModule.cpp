#include "Modules/ModuleManager.h"

#include "Editor.h"
#include "Framework/Commands/UIAction.h"
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
            TEXT("Bake geometry and Deferred BaseColor for the current editor map at 25 cm."),
            FConsoleCommandDelegate::CreateRaw(this, &FVoxelMapMVPEditorModule::BakeCurrentWorld),
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
    void RegisterMenus()
    {
        FToolMenuOwnerScoped OwnerScoped(this);
        UToolMenu* ToolsMenu = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.MainMenu.Tools"));
        FToolMenuSection& Section = ToolsMenu->FindOrAddSection(TEXT("VoxelMapMVP"));
        Section.AddMenuEntry(
            TEXT("VoxelMapMVP_BakeCurrent"),
            LOCTEXT("BakeCurrentLabel", "Bake Current Level (25 cm)"),
            LOCTEXT(
                "BakeCurrentTooltip",
                "Surface-voxelize eligible StaticMesh/ISM/HISM components, capture Deferred BaseColor, and save a copied preview map."),
            FSlateIcon(),
            FUIAction(FExecuteAction::CreateRaw(this, &FVoxelMapMVPEditorModule::BakeCurrentWorld)));
    }

    void BakeCurrentWorld()
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
        FVoxelMapBakeResult Result;
        if (!FVoxelMapBaker::BakeWorldAndSave(World, Options, Result))
        {
            UE_LOG(LogVoxelMapMVPEditor, Error, TEXT("Chromoxel bake failed: %s"), *Result.Error);
            if (!IsRunningCommandlet())
            {
                FMessageDialog::Open(
                    EAppMsgType::Ok,
                    FText::Format(LOCTEXT("BakeFailed", "Chromoxel bake failed:\n{0}"), FText::FromString(Result.Error)));
            }
            return;
        }

        const FString SuccessMessage = FString::Printf(
            TEXT("Chromoxel bake completed.\n\nVoxels: %d\nBlocks: %d\nGeometry Hash: %s\n")
            TEXT("Color: %s (%d captured, %d fallback, %.2f%%)\nColor Hash: %s\nConfig Hash: %s\n")
            TEXT("Map: %s\nData: %s\nReport: %s"),
            Result.OccupiedVoxelCount,
            Result.BlockCount,
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
