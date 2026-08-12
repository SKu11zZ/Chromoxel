"""Build deterministic legacy and extension ZIPs for a Chromoxel release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import zipfile


VERSION = "0.9.2"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_MODE = stat.S_IFREG | 0o644
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "voxelizer"
DIST_ROOT = REPOSITORY_ROOT / "dist"
PACKAGE_FILES = tuple(
    sorted(
        (
            "__init__.py",
            "core.py",
            "cli.py",
            "editable.py",
            "editor.py",
            "gpu_backend.py",
            "i18n.py",
            "preview.py",
            "live.py",
            "meshing.py",
            "vox_io.py",
            "PACKAGE_ID.txt",
            "blender_manifest.toml",
            "LICENSE.md",
        )
    )
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def build_archive(path: Path, *, legacy_layout: bool) -> dict[str, object]:
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for filename in PACKAGE_FILES:
            payload = (SOURCE_ROOT / filename).read_bytes()
            member_name = f"voxelizer/{filename}" if legacy_layout else filename
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

    payload = path.read_bytes()
    return {
        "file": f"dist/{path.name}",
        "bytes": len(payload),
        "sha256": sha256(payload),
        "members": members,
    }


def main() -> int:
    manifest = (SOURCE_ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
    init_py = (SOURCE_ROOT / "__init__.py").read_text(encoding="utf-8")
    if f'version = "{VERSION}"' not in manifest:
        raise RuntimeError("manifest version does not match package version")
    version_tuple = ", ".join(VERSION.split("."))
    if f'"version": ({version_tuple})' not in init_py:
        raise RuntimeError("bl_info version does not match package version")

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    legacy = build_archive(
        DIST_ROOT / f"chromoxel-blender-{VERSION}.zip",
        legacy_layout=True,
    )
    extension = build_archive(
        DIST_ROOT / f"chromoxel-blender-{VERSION}-extension.zip",
        legacy_layout=False,
    )
    report = {
        "schema": "chromoxel-blender-release/1",
        "version": VERSION,
        "visibility": "public",
        "status": "PASS",
        "artifacts": [legacy, extension],
    }
    (REPOSITORY_ROOT / "RELEASE_MANIFEST.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (REPOSITORY_ROOT / "SHA256SUMS.txt").write_text(
        "".join(
            f"{item['sha256']}  {item['file']}\n" for item in report["artifacts"]
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
