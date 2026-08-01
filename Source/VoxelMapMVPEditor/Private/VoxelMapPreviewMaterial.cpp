#include "VoxelMapPreviewMaterial.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "HAL/FileManager.h"
#include "MaterialEditingLibrary.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpressionPerInstanceCustomData.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"

DEFINE_LOG_CATEGORY_STATIC(LogVoxelMapPreviewMaterial, Log, All);

bool FVoxelMapPreviewMaterial::EnsurePersistentMaterial(
    UMaterialInterface*& OutMaterial,
    FString& OutError)
{
    OutMaterial = nullptr;
    OutError.Reset();

    const FString MaterialPath(AssetPath);
    const FString AssetName = FPackageName::GetLongPackageAssetName(MaterialPath);
    if (AssetName.IsEmpty() || !FPackageName::IsValidLongPackageName(MaterialPath))
    {
        OutError = FString::Printf(TEXT("Invalid preview material path: %s"), *MaterialPath);
        return false;
    }

    const FString ObjectPath = FString::Printf(TEXT("%s.%s"), *MaterialPath, *AssetName);
    UMaterial* Material = LoadObject<UMaterial>(nullptr, *ObjectPath);
    bool bCreatedNewAsset = false;
    UPackage* Package = nullptr;

    if (!Material)
    {
        if (FPackageName::DoesPackageExist(MaterialPath))
        {
            UObject* ConflictingObject =
                StaticLoadObject(UObject::StaticClass(), nullptr, *ObjectPath);
            OutError = FString::Printf(
                TEXT("Preview material package exists but is not a UMaterial: %s (%s)."),
                *ObjectPath,
                ConflictingObject ? *ConflictingObject->GetClass()->GetName() : TEXT("unloadable"));
            return false;
        }

        Package = CreatePackage(*MaterialPath);
        Material = NewObject<UMaterial>(
            Package,
            *AssetName,
            RF_Public | RF_Standalone | RF_Transactional);
        bCreatedNewAsset = true;
    }
    else
    {
        Package = Material->GetOutermost();
        Material->Modify();
    }

    if (!Package || !Material)
    {
        OutError = TEXT("Failed to allocate or load the persistent voxel preview material.");
        return false;
    }

    Material->PreEditChange(nullptr);
    UMaterialEditingLibrary::DeleteAllMaterialExpressions(Material);
    Material->MaterialDomain = MD_Surface;
    Material->BlendMode = BLEND_Opaque;
    Material->SetShadingModel(MSM_DefaultLit);

    UMaterialExpressionPerInstanceCustomData3Vector* InstanceColor =
        Cast<UMaterialExpressionPerInstanceCustomData3Vector>(
            UMaterialEditingLibrary::CreateMaterialExpression(
                Material,
                UMaterialExpressionPerInstanceCustomData3Vector::StaticClass(),
                -300,
                0));
    if (!InstanceColor)
    {
        OutError = TEXT("Failed to create PerInstanceCustomData3Vector material expression.");
        return false;
    }

    InstanceColor->DataIndex = 0;
    InstanceColor->ConstDefaultValue =
        FLinearColor::FromSRGBColor(FColor(128, 128, 128, 255));
    if (!UMaterialEditingLibrary::ConnectMaterialProperty(
            InstanceColor,
            FString(),
            MP_BaseColor))
    {
        OutError = TEXT("Failed to connect PerInstanceCustomData RGB to material BaseColor.");
        return false;
    }

    UMaterialEditingLibrary::SetBaseMaterialUsage(
        Material,
        MATUSAGE_InstancedStaticMeshes,
        true);
    Material->PostEditChange();
    const TArray<FString> CompileErrors =
        UMaterialEditingLibrary::RecompileMaterial(Material);
    if (!CompileErrors.IsEmpty())
    {
        OutError = FString::Printf(
            TEXT("Voxel preview material compile failed: %s"),
            *FString::Join(CompileErrors, TEXT(" | ")));
        return false;
    }

    Material->MarkPackageDirty();
    Package->MarkPackageDirty();
    if (bCreatedNewAsset)
    {
        FAssetRegistryModule::AssetCreated(Material);
    }

    const FString PackageFilename =
        FPackageName::LongPackageNameToFilename(
            MaterialPath,
            FPackageName::GetAssetPackageExtension());
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(PackageFilename), true);

    FSavePackageArgs SaveArgs;
    SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
    SaveArgs.SaveFlags = SAVE_None;
    SaveArgs.Error = GError;
    SaveArgs.bSlowTask = false;
    if (!UPackage::SavePackage(Package, Material, *PackageFilename, SaveArgs))
    {
        OutError = FString::Printf(
            TEXT("Failed to save voxel preview material: %s"),
            *PackageFilename);
        return false;
    }

    OutMaterial = Material;
    UE_LOG(
        LogVoxelMapPreviewMaterial,
        Display,
        TEXT("VOXELMAP_PREVIEW_MATERIAL_READY path=%s mode=%s"),
        AssetPath,
        bCreatedNewAsset ? TEXT("created") : TEXT("updated"));
    return true;
}
