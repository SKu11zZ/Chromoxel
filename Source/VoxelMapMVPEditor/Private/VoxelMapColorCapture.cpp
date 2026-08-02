#include "VoxelMapColorCapture.h"

#include "AssetCompilingManager.h"
#include "Components/PrimitiveComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/RendererSettings.h"
#include "Engine/SceneCapture2D.h"
#include "Engine/StaticMesh.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "Math/OrthoMatrix.h"
#include "Misc/App.h"
#include "Misc/SecureHash.h"
#include "PipelineStateCache.h"
#include "PrimitiveComponentId.h"
#include "RenderingThread.h"
#include "RHIGlobals.h"
#include "SceneInterface.h"
#include "StaticMeshResources.h"
#include "UObject/StrongObjectPtr.h"
#include "UnrealClient.h"

DEFINE_LOG_CATEGORY_STATIC(LogVoxelMapColorCapture, Log, All);

namespace
{
constexpr TCHAR CaptureVersion[] = TEXT("VoxelMapBaseColorCapture_v5_rt_init_flush");
constexpr TCHAR ColorMode[] = TEXT("basecolor_buffer_depth");

struct FViewDefinition
{
    const TCHAR* Name;
    FVector Forward;
    FVector UpHint;
};

struct FViewSetup
{
    FString Name;
    FVector Location = FVector::ZeroVector;
    FVector Forward = FVector::ForwardVector;
    FVector Right = FVector::RightVector;
    FVector Up = FVector::UpVector;
    FRotator Rotation = FRotator::ZeroRotator;
    int32 ResolutionX = 0;
    int32 ResolutionY = 0;
    double OrthoWidth = 0.0;
    double OrthoHeight = 0.0;
    double NearClip = 0.0;
    double FarClip = 0.0;
};

struct FColorWinner
{
    bool bValid = false;
    double DistanceSquared = TNumericLimits<double>::Max();
    int32 ViewIndex = MAX_int32;
    int32 PixelIndex = MAX_int32;
    FLinearColor LinearColor = FLinearColor::Black;
};

class FScopedCaptureActor
{
public:
    FScopedCaptureActor(UWorld* InWorld, ASceneCapture2D* InActor)
        : World(InWorld)
        , Actor(InActor)
    {
    }

    ~FScopedCaptureActor()
    {
        if (World && Actor.IsValid())
        {
            World->DestroyActor(Actor.Get(), false, false);
        }
    }

private:
    UWorld* World = nullptr;
    TWeakObjectPtr<ASceneCapture2D> Actor;
};

class FScopedWorldTimeOverride
{
public:
    explicit FScopedWorldTimeOverride(UWorld* InWorld)
        : World(InWorld)
    {
        if (World)
        {
            TimeSeconds = World->TimeSeconds;
            UnpausedTimeSeconds = World->UnpausedTimeSeconds;
            RealTimeSeconds = World->RealTimeSeconds;
            AudioTimeSeconds = World->AudioTimeSeconds;
            DeltaRealTimeSeconds = World->DeltaRealTimeSeconds;
            DeltaTimeSeconds = World->DeltaTimeSeconds;

            World->TimeSeconds = 0.0;
            World->UnpausedTimeSeconds = 0.0;
            World->RealTimeSeconds = 0.0;
            World->AudioTimeSeconds = 0.0;
            World->DeltaRealTimeSeconds = 0.0f;
            World->DeltaTimeSeconds = 0.0f;
        }
    }

    ~FScopedWorldTimeOverride()
    {
        if (World)
        {
            World->TimeSeconds = TimeSeconds;
            World->UnpausedTimeSeconds = UnpausedTimeSeconds;
            World->RealTimeSeconds = RealTimeSeconds;
            World->AudioTimeSeconds = AudioTimeSeconds;
            World->DeltaRealTimeSeconds = DeltaRealTimeSeconds;
            World->DeltaTimeSeconds = DeltaTimeSeconds;
        }
    }

private:
    UWorld* World = nullptr;
    double TimeSeconds = 0.0;
    double UnpausedTimeSeconds = 0.0;
    double RealTimeSeconds = 0.0;
    double AudioTimeSeconds = 0.0;
    float DeltaRealTimeSeconds = 0.0f;
    float DeltaTimeSeconds = 0.0f;
};

FIntVector ToCellCoord(const FVector3d& Position, const FVector3d& Origin, double VoxelSize)
{
    const FVector3d Relative = (Position - Origin) / VoxelSize;
    return FIntVector(
        FMath::FloorToInt(Relative.X),
        FMath::FloorToInt(Relative.Y),
        FMath::FloorToInt(Relative.Z));
}

FString HashBytes(const void* Data, uint64 NumBytes)
{
    FSHA1 Sha;
    if (Data && NumBytes > 0)
    {
        Sha.Update(static_cast<const uint8*>(Data), NumBytes);
    }
    Sha.Final();

    uint8 Hash[FSHA1::DigestSize];
    Sha.GetHash(Hash);
    return BytesToHex(Hash, UE_ARRAY_COUNT(Hash));
}

FString BuildConfigHash(
    const FVoxelMapColorCaptureSettings& Settings,
    double VoxelSize,
    const TArray<FViewSetup>& Views)
{
    FString CanonicalConfig = FString::Printf(
        TEXT("version=%s;mode=%s;voxel=%.9f;min_resolution=%d;max_resolution=%d;pixels_per_voxel=%d;")
        TEXT("bounds_padding=%.9f;camera_padding=%.9f;near=%.9f;minimum_coverage=%.9f;")
        TEXT("show_only=enabled;render_in_main_renderer=false;")
        TEXT("show_flags=static_meshes_instanced_static_meshes_nanite_meshes_materials_unlit_")
        TEXT("no_atmosphere_no_post_no_aa_no_fog_no_shadows;")
        TEXT("component_refresh=finish_compilation_update_world_end_frame_flush_")
        TEXT("wait_pso_mark_proxyless_render_state_dirty_end_frame_flush;")
        TEXT("render_contract=is_client_can_render_real_rhi_world_scene_render_scene;")
        TEXT("render_target_policy=rt_init_update_flush_before_rhi_validation;")
        TEXT("time_policy=world_time_zero_no_tick_no_warmup;"),
        CaptureVersion,
        ColorMode,
        VoxelSize,
        Settings.MinViewResolution,
        Settings.MaxViewResolution,
        Settings.PixelsPerVoxel,
        Settings.BoundsPaddingVoxels,
        Settings.CameraPaddingVoxels,
        Settings.NearClipCm,
        Settings.MinimumAcceptedCoverage);

    for (const FViewSetup& View : Views)
    {
        CanonicalConfig += FString::Printf(
            TEXT("view=%s,res=%dx%d,ortho=%.9fx%.9f,near=%.9f,far=%.9f,")
            TEXT("location=%.9f,%.9f,%.9f,forward=%.9f,%.9f,%.9f,right=%.9f,%.9f,%.9f,up=%.9f,%.9f,%.9f;"),
            *View.Name,
            View.ResolutionX,
            View.ResolutionY,
            View.OrthoWidth,
            View.OrthoHeight,
            View.NearClip,
            View.FarClip,
            View.Location.X,
            View.Location.Y,
            View.Location.Z,
            View.Forward.X,
            View.Forward.Y,
            View.Forward.Z,
            View.Right.X,
            View.Right.Y,
            View.Right.Z,
            View.Up.X,
            View.Up.Y,
            View.Up.Z);
    }

    FTCHARToUTF8 UTF8(*CanonicalConfig);
    return HashBytes(UTF8.Get(), static_cast<uint64>(UTF8.Length()));
}

bool BuildCanonicalLookup(
    const TArray<FVoxelMapBlock>& Blocks,
    TMap<FIntVector, int32>& OutLookup,
    int32& OutOccupiedCount,
    FString& OutError)
{
    OutLookup.Reset();
    OutOccupiedCount = 0;

    for (const FVoxelMapBlock& Block : Blocks)
    {
        uint64 RemainingMask = Block.OccupancyMask;
        while (RemainingMask != 0)
        {
            const uint32 BitIndex = static_cast<uint32>(FMath::CountTrailingZeros64(RemainingMask));
            RemainingMask &= RemainingMask - 1;

            const FIntVector CellCoord =
                Block.BlockCoord * 4 +
                FIntVector(
                    static_cast<int32>(BitIndex & 3u),
                    static_cast<int32>((BitIndex >> 2u) & 3u),
                    static_cast<int32>((BitIndex >> 4u) & 3u));

            if (OutLookup.Contains(CellCoord))
            {
                OutError = FString::Printf(
                    TEXT("Canonical block payload contains duplicate occupied coordinate (%d,%d,%d)."),
                    CellCoord.X,
                    CellCoord.Y,
                    CellCoord.Z);
                return false;
            }

            OutLookup.Add(CellCoord, OutOccupiedCount++);
        }
    }

    if (OutOccupiedCount <= 0 || OutLookup.Num() != OutOccupiedCount)
    {
        OutError = TEXT("Canonical block payload contains no uniquely addressable occupied voxels.");
        return false;
    }

    return true;
}

TArray<FViewSetup> BuildViewSetups(
    const FBox& Bounds,
    double VoxelSize,
    const FVoxelMapColorCaptureSettings& Settings)
{
    static const FViewDefinition ViewDefinitions[] =
    {
        {TEXT("+X"), FVector(-1.0, 0.0, 0.0), FVector::UpVector},
        {TEXT("-X"), FVector(1.0, 0.0, 0.0), FVector::UpVector},
        {TEXT("+Y"), FVector(0.0, -1.0, 0.0), FVector::UpVector},
        {TEXT("-Y"), FVector(0.0, 1.0, 0.0), FVector::UpVector},
        {TEXT("+Z"), FVector(0.0, 0.0, -1.0), FVector::RightVector},
        {TEXT("-Z"), FVector(0.0, 0.0, 1.0), FVector::RightVector}
    };

    const FVector Center = Bounds.GetCenter();
    const FVector Extent = Bounds.GetExtent();
    const double BoundsPadding = VoxelSize * static_cast<double>(Settings.BoundsPaddingVoxels);
    const double CameraPadding = VoxelSize * static_cast<double>(Settings.CameraPaddingVoxels);
    TArray<FViewSetup> Views;
    Views.Reserve(UE_ARRAY_COUNT(ViewDefinitions));

    for (const FViewDefinition& Definition : ViewDefinitions)
    {
        FViewSetup& View = Views.AddDefaulted_GetRef();
        View.Name = Definition.Name;
        View.Rotation = FRotationMatrix::MakeFromXZ(
            Definition.Forward.GetSafeNormal(),
            Definition.UpHint.GetSafeNormal()).Rotator();

        const FRotationMatrix RotationMatrix(View.Rotation);
        View.Forward = RotationMatrix.GetUnitAxis(EAxis::X);
        View.Right = RotationMatrix.GetUnitAxis(EAxis::Y);
        View.Up = RotationMatrix.GetUnitAxis(EAxis::Z);

        const double HalfHorizontal =
            FMath::Abs(View.Right.X) * Extent.X +
            FMath::Abs(View.Right.Y) * Extent.Y +
            FMath::Abs(View.Right.Z) * Extent.Z +
            BoundsPadding;
        const double HalfVertical =
            FMath::Abs(View.Up.X) * Extent.X +
            FMath::Abs(View.Up.Y) * Extent.Y +
            FMath::Abs(View.Up.Z) * Extent.Z +
            BoundsPadding;
        const double HalfDepth =
            FMath::Abs(View.Forward.X) * Extent.X +
            FMath::Abs(View.Forward.Y) * Extent.Y +
            FMath::Abs(View.Forward.Z) * Extent.Z;

        const int32 DesiredResolutionX =
            FMath::CeilToInt((2.0 * HalfHorizontal / VoxelSize) * Settings.PixelsPerVoxel);
        const int32 DesiredResolutionY =
            FMath::CeilToInt((2.0 * HalfVertical / VoxelSize) * Settings.PixelsPerVoxel);
        View.ResolutionX =
            FMath::Clamp(DesiredResolutionX, Settings.MinViewResolution, Settings.MaxViewResolution);
        View.ResolutionY =
            FMath::Clamp(DesiredResolutionY, Settings.MinViewResolution, Settings.MaxViewResolution);

        const double WorldUnitsPerPixel = FMath::Max(
            2.0 * HalfHorizontal / static_cast<double>(View.ResolutionX),
            2.0 * HalfVertical / static_cast<double>(View.ResolutionY));
        View.OrthoWidth = WorldUnitsPerPixel * static_cast<double>(View.ResolutionX);
        View.OrthoHeight = WorldUnitsPerPixel * static_cast<double>(View.ResolutionY);
        View.NearClip = FMath::Max(0.01, static_cast<double>(Settings.NearClipCm));
        View.FarClip = FMath::Max(
            View.NearClip + 1.0,
            2.0 * HalfDepth + 2.0 * CameraPadding);
        View.Location = Center - View.Forward * (HalfDepth + CameraPadding);
    }

    return Views;
}

bool IsBetterWinner(
    double DistanceSquared,
    int32 ViewIndex,
    int32 PixelIndex,
    const FColorWinner& Existing)
{
    if (!Existing.bValid || DistanceSquared < Existing.DistanceSquared)
    {
        return true;
    }
    if (DistanceSquared > Existing.DistanceSquared)
    {
        return false;
    }
    if (ViewIndex != Existing.ViewIndex)
    {
        return ViewIndex < Existing.ViewIndex;
    }
    return PixelIndex < Existing.PixelIndex;
}

uint32 PackLinearColorToSRGB8(const FLinearColor& LinearColor)
{
    const FLinearColor Clamped(
        FMath::Clamp(LinearColor.R, 0.0f, 1.0f),
        FMath::Clamp(LinearColor.G, 0.0f, 1.0f),
        FMath::Clamp(LinearColor.B, 0.0f, 1.0f),
        1.0f);
    const FColor SRGB = Clamped.ToFColorSRGB();
    return
        (static_cast<uint32>(SRGB.R) << 16u) |
        (static_cast<uint32>(SRGB.G) << 8u) |
        static_cast<uint32>(SRGB.B);
}

bool ReadRenderTarget(
    UTextureRenderTarget2D* RenderTarget,
    int32 ExpectedPixelCount,
    TArray<FLinearColor>& OutPixels)
{
    if (!RenderTarget)
    {
        return false;
    }

    FTextureRenderTargetResource* Resource = RenderTarget->GameThread_GetRenderTargetResource();
    if (!Resource)
    {
        return false;
    }

    OutPixels.Reset();
    const bool bRead =
        Resource->ReadLinearColorPixels(OutPixels, FReadSurfaceDataFlags(RCM_MinMax));
    return bRead && OutPixels.Num() == ExpectedPixelCount;
}
} // namespace

bool FVoxelMapColorCapture::Capture(
    UWorld* World,
    const FBox& Bounds,
    const FVector3d& BakeOrigin,
    double VoxelSize,
    const TArray<FVoxelMapBlock>& CanonicalBlocks,
    TConstArrayView<UPrimitiveComponent*> ShowOnlyComponents,
    const FVoxelMapColorCaptureSettings& Settings,
    FVoxelMapColorCaptureResult& OutResult)
{
    OutResult = FVoxelMapColorCaptureResult();
    OutResult.ColorMode = ColorMode;
    OutResult.CaptureVersion = CaptureVersion;
    auto AbortIfCancelled = [&]() -> bool
    {
        if (Settings.ShouldCancel && Settings.ShouldCancel())
        {
            OutResult.CaptureStatus = TEXT("Cancelled");
            OutResult.Error = TEXT("BaseColor capture cancelled by the user.");
            return true;
        }
        return false;
    };
    if (AbortIfCancelled())
    {
        return false;
    }

    const bool bCommandletRenderingAllowed =
        !IsRunningCommandlet() || IsAllowCommandletRendering();
    const bool bIsClient = GIsClient;
    const bool bCanEverRender = FApp::CanEverRender();
    const bool bUsingNullRHI = GUsingNullRHI;
    const bool bWorldSceneExists = World && World->Scene;
    const bool bRenderSceneNonNull =
        bWorldSceneExists && World->Scene->GetRenderScene() != nullptr;

    UE_LOG(
        LogVoxelMapColorCapture,
        Display,
        TEXT("VOXELMAP_COLOR_CAPTURE_RENDER_CONTRACT is_client=%d can_render=%d null_rhi=%d ")
        TEXT("world_scene=%d render_scene_nonnull=%d commandlet_rendering_allowed=%d"),
        bIsClient ? 1 : 0,
        bCanEverRender ? 1 : 0,
        bUsingNullRHI ? 1 : 0,
        bWorldSceneExists ? 1 : 0,
        bRenderSceneNonNull ? 1 : 0,
        bCommandletRenderingAllowed ? 1 : 0);

    if (!bCommandletRenderingAllowed ||
        !bIsClient ||
        !bCanEverRender ||
        bUsingNullRHI ||
        !bRenderSceneNonNull)
    {
        OutResult.CaptureStatus = TEXT("FailedClosed");
        OutResult.Error = FString::Printf(
            TEXT("layer=render_contract reason=non_rendering_world_scene ")
            TEXT("is_client=%d can_render=%d null_rhi=%d world_scene=%d ")
            TEXT("render_scene_nonnull=%d commandlet_rendering_allowed=%d."),
            bIsClient ? 1 : 0,
            bCanEverRender ? 1 : 0,
            bUsingNullRHI ? 1 : 0,
            bWorldSceneExists ? 1 : 0,
            bRenderSceneNonNull ? 1 : 0,
            bCommandletRenderingAllowed ? 1 : 0);
        return false;
    }

    const URendererSettings* RendererSettings = GetDefault<URendererSettings>();
    const IConsoleVariable* ForwardShadingCVar =
        IConsoleManager::Get().FindConsoleVariable(TEXT("r.ForwardShading"));
    const bool bForwardShadingEnabled =
        !RendererSettings ||
        RendererSettings->bForwardShading ||
        (ForwardShadingCVar && ForwardShadingCVar->GetInt() != 0);
    if (bForwardShadingEnabled)
    {
        OutResult.Error =
            TEXT("BaseColor capture is Deferred-only. r.ForwardShading/project Forward Shading must be disabled.");
        return false;
    }

    if (!World || !Bounds.IsValid || VoxelSize <= 0.0)
    {
        OutResult.Error = TEXT("Color capture received an invalid world, bounds, or voxel size.");
        return false;
    }
    if (Settings.MinViewResolution <= 0 ||
        Settings.MaxViewResolution < Settings.MinViewResolution ||
        Settings.MaxViewResolution > 2048 ||
        Settings.PixelsPerVoxel <= 0)
    {
        OutResult.Error = TEXT("Color capture resolution settings are invalid or exceed the hard 2048 cap.");
        return false;
    }

    TMap<FIntVector, int32> CanonicalLookup;
    int32 OccupiedCount = 0;
    if (!BuildCanonicalLookup(CanonicalBlocks, CanonicalLookup, OccupiedCount, OutResult.Error))
    {
        return false;
    }

    const TArray<FViewSetup> Views = BuildViewSetups(Bounds, VoxelSize, Settings);
    if (Views.Num() != 6)
    {
        OutResult.Error = TEXT("Color capture failed to construct the fixed six-axis view set.");
        return false;
    }
    OutResult.ConfigHash = BuildConfigHash(Settings, VoxelSize, Views);

    FAssetCompilingManager::Get().FinishAllCompilation();
    World->UpdateWorldComponents(false, false);
    World->SendAllEndOfFrameUpdates();
    FlushRenderingCommands();

    OutResult.RequestedShowOnlyComponentCount = ShowOnlyComponents.Num();
    TArray<UPrimitiveComponent*> EligibleShowOnlyComponents;
    EligibleShowOnlyComponents.Reserve(ShowOnlyComponents.Num());
    TSet<UPrimitiveComponent*> UniqueShowOnlyComponents;
    for (UPrimitiveComponent* Component : ShowOnlyComponents)
    {
        if (AbortIfCancelled())
        {
            return false;
        }
        if (!Component ||
            !IsValid(Component) ||
            Component->GetWorld() != World ||
            !Component->IsRegistered() ||
            UniqueShowOnlyComponents.Contains(Component))
        {
            continue;
        }

        UniqueShowOnlyComponents.Add(Component);
        EligibleShowOnlyComponents.Add(Component);
        ++OutResult.EligibleShowOnlyComponentCount;
    }

    if (EligibleShowOnlyComponents.IsEmpty())
    {
        OutResult.CaptureStatus = TEXT("FailedClosed");
        OutResult.Error = FString::Printf(
            TEXT("layer=component_eligibility reason=no_eligible_show_only_components ")
            TEXT("requested=%d eligible=%d render_state_created=%d primitive_scene_id=%d scene_proxy=%d."),
            OutResult.RequestedShowOnlyComponentCount,
            OutResult.EligibleShowOnlyComponentCount,
            OutResult.RenderStateCreatedComponentCount,
            OutResult.ValidPrimitiveSceneIdComponentCount,
            OutResult.NonNullSceneProxyComponentCount);
        return false;
    }

    struct FStaticMeshAssetReadiness
    {
        const FStaticMeshRenderData* RenderData = nullptr;
        bool bIsCompiling = false;
        bool bRenderDataExists = false;
        bool bRenderDataInitialized = false;
    };

    TMap<UStaticMesh*, FStaticMeshAssetReadiness> StaticMeshAssetReadiness;
    int32 NonStaticMeshComponentCount = 0;
    int32 MissingStaticMeshComponentCount = 0;
    int32 CompilingStaticMeshAssetCount = 0;
    int32 MissingRenderDataAssetCount = 0;
    int32 UninitializedRenderDataAssetCount = 0;
    int32 InvalidLODComponentCount = 0;
    int32 PSOPrecachingComponentCountBeforeWait = 0;

    for (UPrimitiveComponent* Component : EligibleShowOnlyComponents)
    {
        if (AbortIfCancelled())
        {
            return false;
        }
        if (Component->IsPSOPrecaching())
        {
            ++PSOPrecachingComponentCountBeforeWait;
        }

        UStaticMeshComponent* StaticMeshComponent = Cast<UStaticMeshComponent>(Component);
        if (!StaticMeshComponent)
        {
            ++NonStaticMeshComponentCount;
            UE_LOG(
                LogVoxelMapColorCapture,
                Error,
                TEXT("VOXELMAP_COLOR_CAPTURE_STATIC_MESH_READINESS component=%s reason=not_static_mesh_component"),
                *Component->GetPathName());
            continue;
        }

        UStaticMesh* StaticMesh = StaticMeshComponent->GetStaticMesh();
        if (!StaticMesh)
        {
            ++MissingStaticMeshComponentCount;
            UE_LOG(
                LogVoxelMapColorCapture,
                Error,
                TEXT("VOXELMAP_COLOR_CAPTURE_STATIC_MESH_READINESS component=%s reason=missing_static_mesh"),
                *StaticMeshComponent->GetPathName());
            continue;
        }

        FStaticMeshAssetReadiness* Readiness = StaticMeshAssetReadiness.Find(StaticMesh);
        if (!Readiness)
        {
            FStaticMeshAssetReadiness NewReadiness;
            NewReadiness.bIsCompiling = StaticMesh->IsCompiling();
            if (!NewReadiness.bIsCompiling)
            {
                NewReadiness.RenderData = StaticMesh->GetRenderData();
                NewReadiness.bRenderDataExists = NewReadiness.RenderData != nullptr;
                NewReadiness.bRenderDataInitialized =
                    NewReadiness.RenderData && NewReadiness.RenderData->IsInitialized();
            }

            if (NewReadiness.bIsCompiling)
            {
                ++CompilingStaticMeshAssetCount;
            }
            else if (!NewReadiness.bRenderDataExists)
            {
                ++MissingRenderDataAssetCount;
            }
            else if (!NewReadiness.bRenderDataInitialized)
            {
                ++UninitializedRenderDataAssetCount;
            }

            UE_LOG(
                LogVoxelMapColorCapture,
                Display,
                TEXT("VOXELMAP_COLOR_CAPTURE_STATIC_MESH_ASSET asset=%s is_compiling=%s ")
                TEXT("render_data_exists=%s render_data_initialized=%s"),
                *StaticMesh->GetPathName(),
                NewReadiness.bIsCompiling ? TEXT("true") : TEXT("false"),
                NewReadiness.bRenderDataExists ? TEXT("true") : TEXT("false"),
                NewReadiness.bRenderDataInitialized ? TEXT("true") : TEXT("false"));
            StaticMeshAssetReadiness.Add(StaticMesh, NewReadiness);
            Readiness = StaticMeshAssetReadiness.Find(StaticMesh);
        }

        bool bLODValid = false;
        int32 EffectiveMinLOD = INDEX_NONE;
        int32 LODResourceCount = 0;
        int32 EffectiveLODVertexCount = 0;
        if (Readiness &&
            !Readiness->bIsCompiling &&
            Readiness->bRenderDataExists &&
            Readiness->bRenderDataInitialized)
        {
            const FStaticMeshLODResourcesArray& LODResources = Readiness->RenderData->LODResources;
            LODResourceCount = LODResources.Num();
            const int32 StaticMeshMinLOD = StaticMesh->GetMinLODIdx();
            EffectiveMinLOD = StaticMeshComponent->GetOverrideMinLOD()
                ? FMath::Max(StaticMeshComponent->GetMinLOD(), StaticMeshMinLOD)
                : StaticMeshMinLOD;
            if (LODResourceCount > 0)
            {
                const int32 EffectiveLODIndex =
                    FMath::Clamp<int32>(EffectiveMinLOD, 0, LODResourceCount - 1);
                EffectiveLODVertexCount =
                    LODResources[EffectiveLODIndex].VertexBuffers.StaticMeshVertexBuffer.GetNumVertices();
                bLODValid = EffectiveLODVertexCount > 0;
            }
        }

        if (!bLODValid)
        {
            ++InvalidLODComponentCount;
            UE_LOG(
                LogVoxelMapColorCapture,
                Error,
                TEXT("VOXELMAP_COLOR_CAPTURE_STATIC_MESH_READINESS component=%s asset=%s ")
                TEXT("reason=invalid_lod effective_min_lod=%d lod_resources=%d effective_lod_vertices=%d"),
                *StaticMeshComponent->GetPathName(),
                *StaticMesh->GetPathName(),
                EffectiveMinLOD,
                LODResourceCount,
                EffectiveLODVertexCount);
        }
    }

    UE_LOG(
        LogVoxelMapColorCapture,
        Display,
        TEXT("VOXELMAP_COLOR_CAPTURE_STATIC_MESH_READINESS eligible_components=%d static_mesh_assets=%d ")
        TEXT("non_static_mesh_components=%d missing_static_mesh_components=%d compiling_assets=%d ")
        TEXT("missing_render_data_assets=%d uninitialized_render_data_assets=%d invalid_lod_components=%d ")
        TEXT("pso_precaching_components=%d"),
        OutResult.EligibleShowOnlyComponentCount,
        StaticMeshAssetReadiness.Num(),
        NonStaticMeshComponentCount,
        MissingStaticMeshComponentCount,
        CompilingStaticMeshAssetCount,
        MissingRenderDataAssetCount,
        UninitializedRenderDataAssetCount,
        InvalidLODComponentCount,
        PSOPrecachingComponentCountBeforeWait);

    const bool bStaticMeshAssetsReady =
        NonStaticMeshComponentCount == 0 &&
        MissingStaticMeshComponentCount == 0 &&
        CompilingStaticMeshAssetCount == 0 &&
        MissingRenderDataAssetCount == 0 &&
        UninitializedRenderDataAssetCount == 0 &&
        InvalidLODComponentCount == 0;
    if (!bStaticMeshAssetsReady)
    {
        OutResult.CaptureStatus = TEXT("FailedClosed");
        OutResult.Error = FString::Printf(
            TEXT("layer=static_mesh_render_readiness reason=asset_not_ready ")
            TEXT("eligible=%d assets=%d non_static_components=%d missing_mesh_components=%d ")
            TEXT("compiling_assets=%d missing_render_data_assets=%d ")
            TEXT("uninitialized_render_data_assets=%d invalid_lod_components=%d."),
            OutResult.EligibleShowOnlyComponentCount,
            StaticMeshAssetReadiness.Num(),
            NonStaticMeshComponentCount,
            MissingStaticMeshComponentCount,
            CompilingStaticMeshAssetCount,
            MissingRenderDataAssetCount,
            UninitializedRenderDataAssetCount,
            InvalidLODComponentCount);
        return false;
    }

    const uint32 ActivePrecacheRequestsBeforeWait =
        PipelineStateCache::NumActivePrecacheRequests();
    PipelineStateCache::WaitForAllTasks();
    FlushRenderingCommands();
    const uint32 ActivePrecacheRequestsAfterWait =
        PipelineStateCache::NumActivePrecacheRequests();

    int32 PSOPrecachingComponentCountAfterWait = 0;
    for (UPrimitiveComponent* Component : EligibleShowOnlyComponents)
    {
        if (Component->IsPSOPrecaching())
        {
            ++PSOPrecachingComponentCountAfterWait;
        }
    }

    UE_LOG(
        LogVoxelMapColorCapture,
        Display,
        TEXT("VOXELMAP_COLOR_CAPTURE_PSO_WAIT active_requests_before=%u active_requests_after=%u ")
        TEXT("components_precaching_before=%d components_precaching_after=%d"),
        ActivePrecacheRequestsBeforeWait,
        ActivePrecacheRequestsAfterWait,
        PSOPrecachingComponentCountBeforeWait,
        PSOPrecachingComponentCountAfterWait);

    if (ActivePrecacheRequestsAfterWait != 0 || PSOPrecachingComponentCountAfterWait != 0)
    {
        OutResult.CaptureStatus = TEXT("FailedClosed");
        OutResult.Error = FString::Printf(
            TEXT("layer=pso_precache reason=not_ready_after_wait active_requests_before=%u ")
            TEXT("active_requests_after=%u components_precaching_before=%d components_precaching_after=%d."),
            ActivePrecacheRequestsBeforeWait,
            ActivePrecacheRequestsAfterWait,
            PSOPrecachingComponentCountBeforeWait,
            PSOPrecachingComponentCountAfterWait);
        return false;
    }

    int32 RenderStateDirtyComponentCount = 0;
    for (UPrimitiveComponent* Component : EligibleShowOnlyComponents)
    {
        if (Component->IsRegistered() &&
            Component->IsRenderStateCreated() &&
            Component->GetSceneProxy() == nullptr)
        {
            Component->MarkRenderStateDirty();
            ++RenderStateDirtyComponentCount;
        }
    }

    World->SendAllEndOfFrameUpdates();
    FlushRenderingCommands();

    OutResult.RenderStateCreatedComponentCount = 0;
    OutResult.ValidPrimitiveSceneIdComponentCount = 0;
    OutResult.NonNullSceneProxyComponentCount = 0;
    for (UPrimitiveComponent* Component : EligibleShowOnlyComponents)
    {
        if (Component->IsRenderStateCreated())
        {
            ++OutResult.RenderStateCreatedComponentCount;
        }
        if (Component->GetPrimitiveSceneId().IsValid())
        {
            ++OutResult.ValidPrimitiveSceneIdComponentCount;
        }
        if (Component->GetSceneProxy() != nullptr)
        {
            ++OutResult.NonNullSceneProxyComponentCount;
        }
    }

    UE_LOG(
        LogVoxelMapColorCapture,
        Display,
        TEXT("VOXELMAP_COLOR_CAPTURE_PROXY_REFRESH eligible=%d marked_render_state_dirty=%d ")
        TEXT("render_state_created=%d primitive_scene_id=%d scene_proxy=%d"),
        OutResult.EligibleShowOnlyComponentCount,
        RenderStateDirtyComponentCount,
        OutResult.RenderStateCreatedComponentCount,
        OutResult.ValidPrimitiveSceneIdComponentCount,
        OutResult.NonNullSceneProxyComponentCount);

    const bool bAllEligibleComponentsHaveSceneRegistration =
        OutResult.RenderStateCreatedComponentCount == OutResult.EligibleShowOnlyComponentCount &&
        OutResult.ValidPrimitiveSceneIdComponentCount == OutResult.EligibleShowOnlyComponentCount &&
        OutResult.NonNullSceneProxyComponentCount == OutResult.EligibleShowOnlyComponentCount;
    if (!bAllEligibleComponentsHaveSceneRegistration)
    {
        OutResult.CaptureStatus = TEXT("FailedClosed");
        OutResult.Error = FString::Printf(
            TEXT("layer=component_scene_registration reason=partial_or_zero_scene_registration ")
            TEXT("requested=%d eligible=%d marked_render_state_dirty=%d render_state_created=%d ")
            TEXT("primitive_scene_id=%d scene_proxy=%d."),
            OutResult.RequestedShowOnlyComponentCount,
            OutResult.EligibleShowOnlyComponentCount,
            RenderStateDirtyComponentCount,
            OutResult.RenderStateCreatedComponentCount,
            OutResult.ValidPrimitiveSceneIdComponentCount,
            OutResult.NonNullSceneProxyComponentCount);
        return false;
    }

    FActorSpawnParameters SpawnInfo;
    SpawnInfo.ObjectFlags |= RF_Transient;
    SpawnInfo.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    ASceneCapture2D* CaptureActor =
        World->SpawnActor<ASceneCapture2D>(ASceneCapture2D::StaticClass(), FTransform::Identity, SpawnInfo);
    if (!CaptureActor)
    {
        OutResult.Error = TEXT("Failed to spawn the transient SceneCapture2D actor.");
        return false;
    }
    FScopedCaptureActor CaptureActorGuard(World, CaptureActor);

    USceneCaptureComponent2D* CaptureComponent = CaptureActor->GetCaptureComponent2D();
    if (!CaptureComponent)
    {
        OutResult.Error = TEXT("Transient SceneCapture2D actor has no capture component.");
        return false;
    }

    CaptureComponent->PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
    CaptureComponent->ClearShowOnlyComponents();
    for (UPrimitiveComponent* Component : EligibleShowOnlyComponents)
    {
        CaptureComponent->ShowOnlyComponent(Component);
    }
    CaptureComponent->ProjectionType = ECameraProjectionMode::Orthographic;
    CaptureComponent->bUseCustomProjectionMatrix = true;
    CaptureComponent->bAutoCalculateOrthoPlanes = false;
    CaptureComponent->bUpdateOrthoPlanes = false;
    CaptureComponent->bCaptureEveryFrame = false;
    CaptureComponent->bCaptureOnMovement = false;
    CaptureComponent->bAlwaysPersistRenderingState = false;
    CaptureComponent->bRenderInMainRenderer = false;
    CaptureComponent->PostProcessBlendWeight = 0.0f;
    CaptureComponent->ShowFlags.StaticMeshes = true;
    CaptureComponent->ShowFlags.InstancedStaticMeshes = true;
    CaptureComponent->ShowFlags.NaniteMeshes = true;
    CaptureComponent->ShowFlags.Materials = true;
    CaptureComponent->ShowFlags.Lighting = false;
    CaptureComponent->ShowFlags.Atmosphere = false;
    CaptureComponent->ShowFlags.PostProcessing = false;
    CaptureComponent->ShowFlags.AntiAliasing = false;
    CaptureComponent->ShowFlags.TemporalAA = false;
    CaptureComponent->ShowFlags.MotionBlur = false;
    CaptureComponent->ShowFlags.Fog = false;
    CaptureComponent->ShowFlags.VolumetricFog = false;
    CaptureComponent->ShowFlags.DynamicShadows = false;
    CaptureComponent->ShowFlags.SkyLighting = false;

    TStrongObjectPtr<UTextureRenderTarget2D> BaseColorTarget(
        NewObject<UTextureRenderTarget2D>(GetTransientPackage(), NAME_None, RF_Transient));
    TStrongObjectPtr<UTextureRenderTarget2D> DepthTarget(
        NewObject<UTextureRenderTarget2D>(GetTransientPackage(), NAME_None, RF_Transient));
    if (!BaseColorTarget.IsValid() || !DepthTarget.IsValid())
    {
        OutResult.Error = TEXT("Failed to allocate transient color/depth render targets.");
        return false;
    }

    TArray<FColorWinner> Winners;
    Winners.SetNum(OccupiedCount);
    OutResult.Views.SetNum(Views.Num());
    FScopedWorldTimeOverride WorldTimeOverride(World);
    const double VoxelHalfExtent = VoxelSize * 0.5;
    const double LookupTolerance = FMath::Max(0.05, VoxelSize * 0.08);
    const double MaximumCenterDelta = VoxelHalfExtent + LookupTolerance;

    for (int32 ViewIndex = 0; ViewIndex < Views.Num(); ++ViewIndex)
    {
        if (Settings.ReportViewProgress)
        {
            Settings.ReportViewProgress(ViewIndex, Views.Num());
        }
        if (AbortIfCancelled())
        {
            return false;
        }
        const FViewSetup& View = Views[ViewIndex];
        FVoxelMapColorCaptureViewStats& ViewStats = OutResult.Views[ViewIndex];
        ViewStats.ViewName = View.Name;
        ViewStats.ResolutionX = View.ResolutionX;
        ViewStats.ResolutionY = View.ResolutionY;
        ViewStats.CaptureLocation = View.Location;
        ViewStats.CaptureForward = View.Forward;
        ViewStats.OrthoWidth = static_cast<float>(View.OrthoWidth);
        ViewStats.OrthoHeight = static_cast<float>(View.OrthoHeight);
        ViewStats.NearClip = static_cast<float>(View.NearClip);
        ViewStats.FarClip = static_cast<float>(View.FarClip);
        ViewStats.DepthClearSentinel = View.FarClip;
        const int32 ExpectedPixelCount = View.ResolutionX * View.ResolutionY;

        CaptureActor->SetActorLocationAndRotation(View.Location, View.Rotation, false, nullptr, ETeleportType::TeleportPhysics);
        CaptureComponent->OrthoWidth = static_cast<float>(View.OrthoWidth);
        CaptureComponent->bOverride_CustomNearClippingPlane = true;
        CaptureComponent->CustomNearClippingPlane = static_cast<float>(View.NearClip);
        CaptureComponent->bFiniteFarPlane = true;
        CaptureComponent->MaxViewDistanceOverride = static_cast<float>(View.FarClip);
        CaptureComponent->CustomProjectionMatrix = FReversedZOrthoMatrix(
            View.OrthoWidth * 0.5,
            View.OrthoHeight * 0.5,
            1.0 / (View.FarClip - View.NearClip),
            -View.NearClip);

        BaseColorTarget->ClearColor = FLinearColor::Transparent;
        ViewStats.BaseColorRequestedFormat = static_cast<int32>(PF_FloatRGBA);
        ViewStats.BaseColorRequestedSizeX = View.ResolutionX;
        ViewStats.BaseColorRequestedSizeY = View.ResolutionY;
        BaseColorTarget->InitCustomFormat(
            View.ResolutionX,
            View.ResolutionY,
            PF_FloatRGBA,
            true);
        BaseColorTarget->UpdateResourceImmediate(true);
        FlushRenderingCommands();
        FTextureRenderTargetResource* BaseColorResource =
            BaseColorTarget->GameThread_GetRenderTargetResource();
        const bool bBaseColorResourceInitialized =
            BaseColorResource && BaseColorResource->IsInitialized();
        ViewStats.bBaseColorRenderTargetResourceValid = BaseColorResource != nullptr;
        ViewStats.bBaseColorRenderTargetRHIValid =
            bBaseColorResourceInitialized &&
            BaseColorResource->GetRenderTargetTexture().IsValid();
        ViewStats.BaseColorActualFormat =
            static_cast<int32>(BaseColorTarget->GetFormat());
        ViewStats.BaseColorActualSizeX = BaseColorTarget->SizeX;
        ViewStats.BaseColorActualSizeY = BaseColorTarget->SizeY;
        UE_LOG(
            LogVoxelMapColorCapture,
            Display,
            TEXT("VOXELMAP_COLOR_CAPTURE_RT_READY view=%s target=basecolor ")
            TEXT("resource_valid=%s resource_initialized=%s rhi_valid=%s"),
            *View.Name,
            ViewStats.bBaseColorRenderTargetResourceValid ? TEXT("true") : TEXT("false"),
            bBaseColorResourceInitialized ? TEXT("true") : TEXT("false"),
            ViewStats.bBaseColorRenderTargetRHIValid ? TEXT("true") : TEXT("false"));
        if (!ViewStats.bBaseColorRenderTargetResourceValid ||
            !ViewStats.bBaseColorRenderTargetRHIValid)
        {
            ViewStats.FallbackReason = TEXT("no_render_write");
            OutResult.CaptureStatus = TEXT("FailedClosed");
            OutResult.Error = FString::Printf(
                TEXT("layer=basecolor_render_target reason=no_render_write view=%s ")
                TEXT("resource_valid=%s rhi_valid=%s requested_format=%d actual_format=%d ")
                TEXT("requested_size=%dx%d actual_size=%dx%d."),
                *View.Name,
                ViewStats.bBaseColorRenderTargetResourceValid ? TEXT("true") : TEXT("false"),
                ViewStats.bBaseColorRenderTargetRHIValid ? TEXT("true") : TEXT("false"),
                ViewStats.BaseColorRequestedFormat,
                ViewStats.BaseColorActualFormat,
                ViewStats.BaseColorRequestedSizeX,
                ViewStats.BaseColorRequestedSizeY,
                ViewStats.BaseColorActualSizeX,
                ViewStats.BaseColorActualSizeY);
            return false;
        }
        CaptureComponent->CaptureSource = SCS_BaseColor;
        CaptureComponent->TextureTarget = BaseColorTarget.Get();
        ViewStats.bBaseColorCaptureInvoked = true;
        CaptureComponent->CaptureScene();
        FlushRenderingCommands();

        TArray<FLinearColor> BaseColorPixels;
        ViewStats.bBaseColorReadbackSucceeded =
            ReadRenderTarget(BaseColorTarget.Get(), ExpectedPixelCount, BaseColorPixels);
        ViewStats.BaseColorReadbackPixelCount = BaseColorPixels.Num();
        if (!ViewStats.bBaseColorReadbackSucceeded)
        {
            ViewStats.FallbackReason = TEXT("no_render_write");
            OutResult.CaptureStatus = TEXT("FailedClosed");
            OutResult.Error = FString::Printf(
                TEXT("layer=basecolor_readback reason=no_render_write view=%s ")
                TEXT("capture_invoked=%s readback_succeeded=%s actual_pixels=%d expected_pixels=%d."),
                *View.Name,
                ViewStats.bBaseColorCaptureInvoked ? TEXT("true") : TEXT("false"),
                ViewStats.bBaseColorReadbackSucceeded ? TEXT("true") : TEXT("false"),
                ViewStats.BaseColorReadbackPixelCount,
                ExpectedPixelCount);
            return false;
        }

        DepthTarget->ClearColor =
            FLinearColor(static_cast<float>(View.FarClip), 0.0f, 0.0f, 0.0f);
        ViewStats.DepthRequestedFormat = static_cast<int32>(PF_A32B32G32R32F);
        ViewStats.DepthRequestedSizeX = View.ResolutionX;
        ViewStats.DepthRequestedSizeY = View.ResolutionY;
        DepthTarget->InitCustomFormat(
            View.ResolutionX,
            View.ResolutionY,
            PF_A32B32G32R32F,
            true);
        DepthTarget->UpdateResourceImmediate(true);
        FlushRenderingCommands();
        FTextureRenderTargetResource* DepthResource =
            DepthTarget->GameThread_GetRenderTargetResource();
        const bool bDepthResourceInitialized =
            DepthResource && DepthResource->IsInitialized();
        ViewStats.bDepthRenderTargetResourceValid = DepthResource != nullptr;
        ViewStats.bDepthRenderTargetRHIValid =
            bDepthResourceInitialized &&
            DepthResource->GetRenderTargetTexture().IsValid();
        ViewStats.DepthActualFormat =
            static_cast<int32>(DepthTarget->GetFormat());
        ViewStats.DepthActualSizeX = DepthTarget->SizeX;
        ViewStats.DepthActualSizeY = DepthTarget->SizeY;
        UE_LOG(
            LogVoxelMapColorCapture,
            Display,
            TEXT("VOXELMAP_COLOR_CAPTURE_RT_READY view=%s target=depth ")
            TEXT("resource_valid=%s resource_initialized=%s rhi_valid=%s"),
            *View.Name,
            ViewStats.bDepthRenderTargetResourceValid ? TEXT("true") : TEXT("false"),
            bDepthResourceInitialized ? TEXT("true") : TEXT("false"),
            ViewStats.bDepthRenderTargetRHIValid ? TEXT("true") : TEXT("false"));
        if (!ViewStats.bDepthRenderTargetResourceValid ||
            !ViewStats.bDepthRenderTargetRHIValid)
        {
            ViewStats.FallbackReason = TEXT("no_render_write");
            OutResult.CaptureStatus = TEXT("FailedClosed");
            OutResult.Error = FString::Printf(
                TEXT("layer=depth_render_target reason=no_render_write view=%s ")
                TEXT("resource_valid=%s rhi_valid=%s requested_format=%d actual_format=%d ")
                TEXT("requested_size=%dx%d actual_size=%dx%d."),
                *View.Name,
                ViewStats.bDepthRenderTargetResourceValid ? TEXT("true") : TEXT("false"),
                ViewStats.bDepthRenderTargetRHIValid ? TEXT("true") : TEXT("false"),
                ViewStats.DepthRequestedFormat,
                ViewStats.DepthActualFormat,
                ViewStats.DepthRequestedSizeX,
                ViewStats.DepthRequestedSizeY,
                ViewStats.DepthActualSizeX,
                ViewStats.DepthActualSizeY);
            return false;
        }
        CaptureComponent->CaptureSource = SCS_SceneDepth;
        CaptureComponent->TextureTarget = DepthTarget.Get();
        ViewStats.bDepthCaptureInvoked = true;
        CaptureComponent->CaptureScene();
        FlushRenderingCommands();

        TArray<FLinearColor> DepthPixels;
        ViewStats.bDepthReadbackSucceeded =
            ReadRenderTarget(DepthTarget.Get(), ExpectedPixelCount, DepthPixels);
        ViewStats.DepthReadbackPixelCount = DepthPixels.Num();
        if (!ViewStats.bDepthReadbackSucceeded)
        {
            ViewStats.FallbackReason = TEXT("no_render_write");
            OutResult.CaptureStatus = TEXT("FailedClosed");
            OutResult.Error = FString::Printf(
                TEXT("layer=depth_readback reason=no_render_write view=%s ")
                TEXT("capture_invoked=%s readback_succeeded=%s actual_pixels=%d expected_pixels=%d."),
                *View.Name,
                ViewStats.bDepthCaptureInvoked ? TEXT("true") : TEXT("false"),
                ViewStats.bDepthReadbackSucceeded ? TEXT("true") : TEXT("false"),
                ViewStats.DepthReadbackPixelCount,
                ExpectedPixelCount);
            return false;
        }

        const double ClearSentinelTolerance =
            FMath::Max(1.0e-4, FMath::Abs(View.FarClip) * 1.0e-6);
        double FiniteDepthMinimum = TNumericLimits<double>::Max();
        double FiniteDepthMaximum = TNumericLimits<double>::Lowest();
        for (int32 PixelIndex = 0; PixelIndex < ExpectedPixelCount; ++PixelIndex)
        {
            if ((PixelIndex & 65535) == 0 && AbortIfCancelled())
            {
                return false;
            }
            const double Depth = static_cast<double>(DepthPixels[PixelIndex].R);
            const FLinearColor& LinearColor = BaseColorPixels[PixelIndex];
            const bool bFiniteDepth = FMath::IsFinite(Depth);
            const bool bFiniteColor =
                FMath::IsFinite(LinearColor.R) &&
                FMath::IsFinite(LinearColor.G) &&
                FMath::IsFinite(LinearColor.B);
            const bool bBaseColorClear =
                FMath::IsNearlyZero(LinearColor.R) &&
                FMath::IsNearlyZero(LinearColor.G) &&
                FMath::IsNearlyZero(LinearColor.B) &&
                FMath::IsNearlyZero(LinearColor.A);
            if (!bBaseColorClear)
            {
                ++ViewStats.BaseColorNonClearPixelCount;
            }

            if (!bFiniteDepth)
            {
                ++ViewStats.RawDepthNonFinitePixelCount;
                continue;
            }

            ++ViewStats.RawDepthFinitePixelCount;
            FiniteDepthMinimum = FMath::Min(FiniteDepthMinimum, Depth);
            FiniteDepthMaximum = FMath::Max(FiniteDepthMaximum, Depth);
            const bool bClearSentinel =
                FMath::IsNearlyEqual(Depth, View.FarClip, ClearSentinelTolerance);
            if (bClearSentinel)
            {
                ++ViewStats.RawDepthClearSentinelPixelCount;
                ++ViewStats.RawDepthAboveOrEqualFarPixelCount;
                continue;
            }
            ++ViewStats.RawDepthNonClearPixelCount;

            if (Depth <= View.NearClip)
            {
                ++ViewStats.RawDepthBelowOrEqualNearPixelCount;
                continue;
            }
            if (Depth >= View.FarClip)
            {
                ++ViewStats.RawDepthAboveOrEqualFarPixelCount;
                continue;
            }

            ++ViewStats.RawDepthInRangePixelCount;
            if (!bFiniteColor)
            {
                continue;
            }

            ++ViewStats.DepthHitPixelCount;
            const int32 PixelX = PixelIndex % View.ResolutionX;
            const int32 PixelY = PixelIndex / View.ResolutionX;
            const double HorizontalOffset =
                ((static_cast<double>(PixelX) + 0.5) / static_cast<double>(View.ResolutionX) - 0.5) *
                View.OrthoWidth;
            const double VerticalOffset =
                (0.5 - (static_cast<double>(PixelY) + 0.5) / static_cast<double>(View.ResolutionY)) *
                View.OrthoHeight;
            const FVector3d WorldPosition =
                FVector3d(View.Location) +
                FVector3d(View.Forward) * Depth +
                FVector3d(View.Right) * HorizontalOffset +
                FVector3d(View.Up) * VerticalOffset;
            const FIntVector BaseCell = ToCellCoord(WorldPosition, BakeOrigin, VoxelSize);
            bool bMappedPixel = false;

            // A surface exactly on a voxel boundary legitimately belongs to
            // both triangle/AABB cells. Probe only the immediate neighborhood,
            // and only accept coordinates already present in canonical geometry.
            for (int32 ZOffset = -1; ZOffset <= 1; ++ZOffset)
            {
                for (int32 YOffset = -1; YOffset <= 1; ++YOffset)
                {
                    for (int32 XOffset = -1; XOffset <= 1; ++XOffset)
                    {
                        const FIntVector CandidateCell =
                            BaseCell + FIntVector(XOffset, YOffset, ZOffset);
                        const int32* CanonicalIndex = CanonicalLookup.Find(CandidateCell);
                        if (!CanonicalIndex)
                        {
                            continue;
                        }

                        const FVector3d CellCenter =
                            BakeOrigin +
                            (FVector3d(CandidateCell.X, CandidateCell.Y, CandidateCell.Z) +
                             FVector3d(0.5)) *
                                VoxelSize;
                        const FVector3d Delta = WorldPosition - CellCenter;
                        if (FMath::Abs(Delta.X) > MaximumCenterDelta ||
                            FMath::Abs(Delta.Y) > MaximumCenterDelta ||
                            FMath::Abs(Delta.Z) > MaximumCenterDelta)
                        {
                            continue;
                        }

                        bMappedPixel = true;
                        const double DistanceSquared = Delta.SizeSquared();
                        FColorWinner& Winner = Winners[*CanonicalIndex];
                        if (IsBetterWinner(DistanceSquared, ViewIndex, PixelIndex, Winner))
                        {
                            Winner.bValid = true;
                            Winner.DistanceSquared = DistanceSquared;
                            Winner.ViewIndex = ViewIndex;
                            Winner.PixelIndex = PixelIndex;
                            Winner.LinearColor = LinearColor;
                        }
                    }
                }
            }

            if (bMappedPixel)
            {
                ++ViewStats.OccupiedLookupPixelCount;
            }
        }

        ViewStats.bHasFiniteDepthRange = ViewStats.RawDepthFinitePixelCount > 0;
        if (ViewStats.bHasFiniteDepthRange)
        {
            ViewStats.RawDepthMinimum = FiniteDepthMinimum;
            ViewStats.RawDepthMaximum = FiniteDepthMaximum;
        }

        const bool bAllClearDepth =
            ViewStats.RawDepthClearSentinelPixelCount == ExpectedPixelCount;
        const bool bRenderWrite =
            ViewStats.BaseColorNonClearPixelCount > 0 ||
            ViewStats.RawDepthNonClearPixelCount > 0;
        if (bRenderWrite)
        {
            ++OutResult.ViewsWithRenderWriteCount;
        }
        if (bAllClearDepth)
        {
            ++OutResult.AllClearDepthViewCount;
        }
        if (ViewStats.RawDepthInRangePixelCount > 0)
        {
            ++OutResult.InRangeDepthViewCount;
        }
        if (ViewStats.OccupiedLookupPixelCount > 0)
        {
            ++OutResult.OccupiedLookupViewCount;
        }

        if (bAllClearDepth)
        {
            ViewStats.FallbackReason = TEXT("all_clear_depth");
        }
        else if (!bRenderWrite)
        {
            ViewStats.FallbackReason = TEXT("no_render_write");
        }
        else if (ViewStats.RawDepthInRangePixelCount == 0)
        {
            ViewStats.FallbackReason = TEXT("depth_out_of_range");
        }
        else if (ViewStats.OccupiedLookupPixelCount == 0)
        {
            ViewStats.FallbackReason = TEXT("no_occupied_lookup");
        }
        else
        {
            ViewStats.FallbackReason = TEXT("none");
        }

        UE_LOG(
            LogVoxelMapColorCapture,
            Display,
            TEXT("VOXELMAP_COLOR_CAPTURE_VIEW view=%s location=(%.3f,%.3f,%.3f) ")
            TEXT("forward=(%.3f,%.3f,%.3f) ortho=(%.3f,%.3f) near=%.3f far=%.3f ")
            TEXT("base_rt=resource:%s,rhi:%s,format:%d/%d,size:%dx%d/%dx%d,capture:%s,read:%s,pixels:%d,non_clear:%d ")
            TEXT("depth_rt=resource:%s,rhi:%s,format:%d/%d,size:%dx%d/%dx%d,capture:%s,read:%s,pixels:%d ")
            TEXT("raw_depth=finite:%d,nonfinite:%d,min:%.6f,max:%.6f,clear:%.6f,clear_pixels:%d,")
            TEXT("non_clear:%d,below_near:%d,in_range:%d,above_far:%d ")
            TEXT("depth_hits=%d occupied_lookup=%d reason=%s"),
            *ViewStats.ViewName,
            ViewStats.CaptureLocation.X,
            ViewStats.CaptureLocation.Y,
            ViewStats.CaptureLocation.Z,
            ViewStats.CaptureForward.X,
            ViewStats.CaptureForward.Y,
            ViewStats.CaptureForward.Z,
            ViewStats.OrthoWidth,
            ViewStats.OrthoHeight,
            ViewStats.NearClip,
            ViewStats.FarClip,
            ViewStats.bBaseColorRenderTargetResourceValid ? TEXT("true") : TEXT("false"),
            ViewStats.bBaseColorRenderTargetRHIValid ? TEXT("true") : TEXT("false"),
            ViewStats.BaseColorRequestedFormat,
            ViewStats.BaseColorActualFormat,
            ViewStats.BaseColorRequestedSizeX,
            ViewStats.BaseColorRequestedSizeY,
            ViewStats.BaseColorActualSizeX,
            ViewStats.BaseColorActualSizeY,
            ViewStats.bBaseColorCaptureInvoked ? TEXT("true") : TEXT("false"),
            ViewStats.bBaseColorReadbackSucceeded ? TEXT("true") : TEXT("false"),
            ViewStats.BaseColorReadbackPixelCount,
            ViewStats.BaseColorNonClearPixelCount,
            ViewStats.bDepthRenderTargetResourceValid ? TEXT("true") : TEXT("false"),
            ViewStats.bDepthRenderTargetRHIValid ? TEXT("true") : TEXT("false"),
            ViewStats.DepthRequestedFormat,
            ViewStats.DepthActualFormat,
            ViewStats.DepthRequestedSizeX,
            ViewStats.DepthRequestedSizeY,
            ViewStats.DepthActualSizeX,
            ViewStats.DepthActualSizeY,
            ViewStats.bDepthCaptureInvoked ? TEXT("true") : TEXT("false"),
            ViewStats.bDepthReadbackSucceeded ? TEXT("true") : TEXT("false"),
            ViewStats.DepthReadbackPixelCount,
            ViewStats.RawDepthFinitePixelCount,
            ViewStats.RawDepthNonFinitePixelCount,
            ViewStats.RawDepthMinimum,
            ViewStats.RawDepthMaximum,
            ViewStats.DepthClearSentinel,
            ViewStats.RawDepthClearSentinelPixelCount,
            ViewStats.RawDepthNonClearPixelCount,
            ViewStats.RawDepthBelowOrEqualNearPixelCount,
            ViewStats.RawDepthInRangePixelCount,
            ViewStats.RawDepthAboveOrEqualFarPixelCount,
            ViewStats.DepthHitPixelCount,
            ViewStats.OccupiedLookupPixelCount,
            *ViewStats.FallbackReason);
    }

    if (Settings.ReportViewProgress)
    {
        Settings.ReportViewProgress(Views.Num(), Views.Num());
    }

    OutResult.bAllViewsClearDepth =
        OutResult.AllClearDepthViewCount == Views.Num();
    OutResult.DiagnosticSummary = FString::Printf(
        TEXT("requested=%d eligible=%d render_state_created=%d primitive_scene_id=%d ")
        TEXT("scene_proxy=%d render_write_views=%d all_clear_depth_views=%d ")
        TEXT("in_range_depth_views=%d occupied_lookup_views=%d"),
        OutResult.RequestedShowOnlyComponentCount,
        OutResult.EligibleShowOnlyComponentCount,
        OutResult.RenderStateCreatedComponentCount,
        OutResult.ValidPrimitiveSceneIdComponentCount,
        OutResult.NonNullSceneProxyComponentCount,
        OutResult.ViewsWithRenderWriteCount,
        OutResult.AllClearDepthViewCount,
        OutResult.InRangeDepthViewCount,
        OutResult.OccupiedLookupViewCount);
    if (OutResult.bAllViewsClearDepth)
    {
        OutResult.CaptureStatus = TEXT("FailedClosed");
        OutResult.Error = FString::Printf(
            TEXT("layer=depth_capture reason=all_clear_depth views=%d/%d; %s."),
            OutResult.AllClearDepthViewCount,
            Views.Num(),
            *OutResult.DiagnosticSummary);
        return false;
    }

    OutResult.PackedColors.Init(UVoxelMapDataAsset::DefaultPackedColor, OccupiedCount);
    for (int32 CanonicalIndex = 0; CanonicalIndex < Winners.Num(); ++CanonicalIndex)
    {
        const FColorWinner& Winner = Winners[CanonicalIndex];
        if (!Winner.bValid)
        {
            continue;
        }

        OutResult.PackedColors[CanonicalIndex] = PackLinearColorToSRGB8(Winner.LinearColor);
        ++OutResult.CapturedVoxelCount;
        if (OutResult.Views.IsValidIndex(Winner.ViewIndex))
        {
            ++OutResult.Views[Winner.ViewIndex].WinningVoxelCount;
        }
    }

    OutResult.FallbackVoxelCount = OccupiedCount - OutResult.CapturedVoxelCount;
    OutResult.Coverage = OccupiedCount > 0
        ? static_cast<float>(OutResult.CapturedVoxelCount) / static_cast<float>(OccupiedCount)
        : 0.0f;

    TSet<uint32> UniqueColors;
    UniqueColors.Reserve(OutResult.PackedColors.Num());
    for (uint32 PackedColor : OutResult.PackedColors)
    {
        UniqueColors.Add(PackedColor);
    }
    OutResult.UniqueColorCount = UniqueColors.Num();
    OutResult.ColorHash = HashBytes(
        OutResult.PackedColors.GetData(),
        static_cast<uint64>(OutResult.PackedColors.Num()) * sizeof(uint32));

    if (OutResult.FallbackVoxelCount > 0)
    {
        OutResult.FallbackReasons.AddUnique(TEXT("unhit_occupied_voxels"));
        for (const FVoxelMapColorCaptureViewStats& ViewStats : OutResult.Views)
        {
            if (!ViewStats.FallbackReason.Equals(TEXT("none"), ESearchCase::CaseSensitive))
            {
                OutResult.FallbackReasons.AddUnique(ViewStats.FallbackReason);
            }
        }
    }

    const bool bCountsAreConsistent =
        OutResult.PackedColors.Num() == OccupiedCount &&
        OutResult.CapturedVoxelCount >= 0 &&
        OutResult.FallbackVoxelCount >= 0 &&
        OutResult.CapturedVoxelCount + OutResult.FallbackVoxelCount == OccupiedCount;
    if (!bCountsAreConsistent || OutResult.ColorHash.IsEmpty() || OutResult.ConfigHash.IsEmpty())
    {
        OutResult.Error = FString::Printf(
            TEXT("Color capture consistency guard failed: colors=%d captured=%d fallback=%d occupied=%d."),
            OutResult.PackedColors.Num(),
            OutResult.CapturedVoxelCount,
            OutResult.FallbackVoxelCount,
            OccupiedCount);
        return false;
    }

    OutResult.bSucceededWithFallback =
        OutResult.FallbackVoxelCount > 0 ||
        OutResult.Coverage < Settings.MinimumAcceptedCoverage;
    OutResult.CaptureStatus =
        OutResult.bSucceededWithFallback ? TEXT("SucceededWithFallback") : TEXT("Succeeded");
    OutResult.bComplete = true;

    UE_LOG(
        LogVoxelMapColorCapture,
        Display,
        TEXT("VOXELMAP_COLOR_CAPTURE_COMPLETE status=%s captured=%d fallback=%d occupied=%d coverage=%.6f unique=%d color_hash=%s config_hash=%s"),
        *OutResult.CaptureStatus,
        OutResult.CapturedVoxelCount,
        OutResult.FallbackVoxelCount,
        OccupiedCount,
        OutResult.Coverage,
        OutResult.UniqueColorCount,
        *OutResult.ColorHash,
        *OutResult.ConfigHash);
    return true;
}
