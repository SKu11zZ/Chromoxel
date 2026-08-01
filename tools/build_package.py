"""Build a deterministic source-only Unreal plug-in ZIP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import zipfile


VERSION = "0.2.0"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_MODE = stat.S_IFREG | 0o644
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = REPOSITORY_ROOT / "dist"
ROOT_FILES = (
    "VoxelMapMVP.uplugin",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "VALIDATION.md",
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def package_files() -> list[Path]:
    files = [REPOSITORY_ROOT / name for name in ROOT_FILES]
    files.extend(
        sorted(
            path
            for path in (REPOSITORY_ROOT / "Config").rglob("*")
            if path.is_file()
        )
    )
    files.extend(
        sorted(
            path
            for path in (REPOSITORY_ROOT / "Source").rglob("*")
            if path.is_file()
        )
    )
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing package files: {missing}")
    return files


def main() -> int:
    descriptor = json.loads(
        (REPOSITORY_ROOT / "VoxelMapMVP.uplugin").read_text(encoding="utf-8")
    )
    if descriptor.get("VersionName") != VERSION:
        raise RuntimeError("uplugin version does not match package version")

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    archive_path = DIST_ROOT / f"chromoxel-unreal-{VERSION}-UE5.8-source.zip"
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for source in package_files():
            relative = source.relative_to(REPOSITORY_ROOT).as_posix()
            member_name = f"Chromoxel/{relative}"
            payload = source.read_bytes()
            info = zipfile.ZipInfo(member_name, date_time=FIXED_TIMESTAMP)
            info.create_system = 3
            info.external_attr = FIXED_MODE << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload, compresslevel=9)
            members.append(
                {
                    "name": member_name,
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                }
            )

    archive_payload = archive_path.read_bytes()
    artifact = {
        "file": f"dist/{archive_path.name}",
        "bytes": len(archive_payload),
        "sha256": sha256(archive_payload),
        "members": members,
    }
    report = {
        "schema": "chromoxel-unreal-release/1",
        "version": VERSION,
        "engine": "Unreal Engine 5.8",
        "visibility": "public",
        "status": "PASS",
        "artifact": artifact,
    }
    (REPOSITORY_ROOT / "RELEASE_MANIFEST.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (REPOSITORY_ROOT / "SHA256SUMS.txt").write_text(
        f"{artifact['sha256']}  {artifact['file']}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
