#!/usr/bin/env python3
"""Build deterministic, credential-free public source and router archives."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
STAMP = (2026, 1, 1, 0, 0, 0)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(path: Path) -> bytes:
    """Store text artifacts with Unix LF regardless of the checkout setting."""
    data = path.read_bytes()
    if path.suffix in {"", ".sh", ".lua", ".py", ".ps1", ".json", ".md", ".txt", ".uci"} or path.name in {"campus-route", "campus-route-accel", "campus-route-update", "campus-route-rollback"}:
        return data.replace(b"\r\n", b"\n")
    return data


def ignored(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    return bool({".git", "build", "dist", "outputs", "work", "artifacts"} & set(rel.parts)) or "__pycache__" in rel.parts or path.suffix in {".pyc", ".pyo"}


def zip_tree(path: Path, output: Path, prefix: str = "") -> None:
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(path.rglob("*")):
            if not file.is_file() or ignored(file):
                continue
            rel = file.relative_to(path).as_posix()
            name = f"{prefix}{rel}"
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if file.suffix in {".sh", ".lua"} or file.name in {"campus-route", "campus-route-accel", "campus-route-update", "campus-route-rollback"} else 0o100644) << 16
            archive.writestr(info, payload(file))


def tar_tree(path: Path, output: Path, root_name: str) -> None:
    import gzip
    import tarfile

    if output.exists():
        output.unlink()
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as archive:
                for file in sorted(path.rglob("*")):
                    if ignored(file):
                        continue
                    rel = file.relative_to(path).as_posix()
                    info = tarfile.TarInfo(f"{root_name}/{rel}")
                    if file.is_dir():
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        info.size = 0
                    else:
                        data = payload(file)
                        info.mode = 0o600 if rel == "etc/config/campus_route" else (0o755 if file.suffix in {".sh", ".lua"} or file.name in {"campus-route", "campus-route-accel", "campus-route-update", "campus-route-rollback"} else 0o644)
                        info.size = len(data)
                        info.type = tarfile.REGTYPE
                        info.mtime = 0
                        archive.addfile(info, __import__("io").BytesIO(data))
                        continue
                    info.mtime = 0
                    archive.addfile(info)


source_zip = ARTIFACTS / "CampusRoute-public-source-v1.1.0.zip"
router_tar = ARTIFACTS / "CampusRoute-router-public-v1.1.0.tar.gz"
zip_tree(ROOT, source_zip)
tar_tree(ROOT / "router", router_tar, "router")

# Windows is intentionally unchanged for this feature; carry forward the
# already-published, dependency-free x64 package under the new release name.
old_windows = ARTIFACTS / "CampusRoute-Windows-x64-public-v1.zip"
windows_zip = ARTIFACTS / "CampusRoute-Windows-x64-public-v1.1.0.zip"
shutil.copy2(old_windows, windows_zip)

entries = [
    {"name": source_zip.name, "sha256": digest(source_zip), "bytes": source_zip.stat().st_size},
    {"name": router_tar.name, "sha256": digest(router_tar), "bytes": router_tar.stat().st_size},
    {"name": windows_zip.name, "sha256": digest(windows_zip), "bytes": windows_zip.stat().st_size},
]
manifest = {
    "product": "CampusRoute",
    "version": "v1.1.0-public",
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "owner": "Strayed2SE",
    "feature": "connection-level domestic spillover acceleration",
    "windows_unchanged": True,
    "artifacts": entries,
}
(ARTIFACTS / "release-manifest-v1.1.0.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
lines = [f"{item['sha256']}  {item['name']}" for item in entries]
(ARTIFACTS / "SHA256SUMS-v1.1.0.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
