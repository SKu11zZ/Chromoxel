using UnrealBuildTool;

public class VoxelMapMVPEditor : ModuleRules
{
    public VoxelMapMVPEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PrivateDependencyModuleNames.AddRange(
            new[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "UnrealEd",
                "AssetRegistry",
                "Json",
                "JsonUtilities",
                "LevelEditor",
                "MaterialEditor",
                "MeshDescription",
                "RenderCore",
                "RHI",
                "StaticMeshDescription",
                "Slate",
                "SlateCore",
                "ToolMenus",
                "VoxelMapMVP"
            });
    }
}
