"""Build the Python JSON sidecar with a locally available PyInstaller.

This script is intentionally not run as part of Phase 1. Its output path and
name match Tauri's ``bundle.externalBin`` configuration:
``src-tauri/binaries/illegal-char-remover-<Rust target>``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
BUILD_DIR = BACKEND_DIR / "build"
BINARIES_DIR = PROJECT_ROOT / "src-tauri" / "binaries"
SIDECAR_BASE_NAME = "illegal-char-remover"


def rust_target_triple() -> str:
    result = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        check=True,
        capture_output=True,
        text=True,
    )
    target = result.stdout.strip()
    if not target:
        raise RuntimeError("rustc did not return a host target triple.")
    return target


def main() -> None:
    target = rust_target_triple()
    binary_name = f"{SIDECAR_BASE_NAME}-{target}"
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--paths",
            str(BACKEND_DIR),
            "--noconfirm",
            "--name",
            binary_name,
            "--distpath",
            str(BINARIES_DIR),
            "--workpath",
            str(BUILD_DIR / "work"),
            "--specpath",
            str(BUILD_DIR),
            str(BACKEND_DIR / "main.py"),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
