using UnrealBuildTool;

public class VoxelMapMVP : ModuleRules
{
    public VoxelMapMVP(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new[]
            {
                "Core",
                "CoreUObject",
                "Engine"
            });
    }
}
