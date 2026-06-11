"""Build a standalone AFK Presser binary for the current OS.

PyInstaller cannot cross-compile: this produces a binary for whatever OS it is
run on, dropped into ``build/<os>/``. To get both (Windows, macOS) run this on
each platform -- e.g. via the GitHub Actions matrix in
``.github/workflows/build.yml``.

Usage:
    python build.py            # onefile, windowed (no console)
    python build.py --console  # keep a console window (handy for debugging)
    python build.py --clean    # wipe PyInstaller caches first
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "AfkPresser"
SRC_DIR = "src"
ENTRY = "afk_presser.py"  # lives under SRC_DIR

# platform.system() -> folder name used under build/
OS_FOLDERS = {"Windows": "windows", "Darwin": "macos"}


def build_dmg(app_path: Path, dmg_path: Path, volume_name: str) -> bool:
    """Package a macOS .app into a drag-to-Applications .dmg.

    Produces the familiar installer window where the user drags the app onto an
    Applications alias. Returns True on success, False if dmgbuild is missing
    (the .app is still a valid artifact, so a missing DMG isn't a hard error).
    """
    try:
        import dmgbuild
    except ImportError:
        print(
            "   note: dmgbuild not installed; skipping .dmg (the .app is fine).\n"
            "         install it with:  pip install dmgbuild",
            file=sys.stderr,
        )
        return False

    if dmg_path.exists():
        dmg_path.unlink()

    app_name = app_path.name
    dmgbuild.build_dmg(
        filename=str(dmg_path),
        volume_name=volume_name,
        settings={
            "files": [str(app_path)],
            "symlinks": {"Applications": "/Applications"},
            "icon_locations": {
                app_name: (140, 120),
                "Applications": (500, 120),
            },
            "window_rect": ((200, 200), (640, 300)),
            "icon_size": 96,
        },
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AFK Presser for the current OS.")
    parser.add_argument("--name", default=APP_NAME, help="output binary name")
    parser.add_argument("--console", action="store_true", help="keep a console window")
    parser.add_argument("--clean", action="store_true", help="clear PyInstaller caches")
    parser.add_argument(
        "--no-dmg",
        action="store_true",
        help="macOS: skip building the drag-to-Applications .dmg installer",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    src_dir = root / SRC_DIR
    entry = src_dir / ENTRY
    if not entry.exists():
        print(f"error: entry point not found: {entry}", file=sys.stderr)
        return 1

    os_name = OS_FOLDERS.get(platform.system())
    if os_name is None:
        print(f"error: unsupported OS: {platform.system()}", file=sys.stderr)
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "error: PyInstaller is not installed.\n"
            "       install it with:  pip install pyinstaller",
            file=sys.stderr,
        )
        return 1

    dist_dir = root / "build" / os_name
    work_dir = root / "build" / ".work" / os_name

    # Start each build from a clean output folder so stale binaries don't linger.
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # macOS .app bundles can't be a single file: onefile + windowed produces a
    # bundle that runs from the terminal but silently fails to launch via Finder
    # (the bootloader unpacks to a temp dir, which clashes with macOS security).
    # Use onedir there so the .app is a normal, Finder-launchable bundle.
    onefile = os_name != "macos" or args.console

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile" if onefile else "--onedir",
        "--console" if args.console else "--windowed",
        "--name", args.name,
        "--paths", str(src_dir),  # so 'import presser_engine' is found
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--specpath", str(work_dir),
    ]
    if args.clean:
        cmd.append("--clean")
    cmd.append(str(entry))

    print(f">> Building {args.name} for {os_name} ...")
    print("   " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=root)
    if result.returncode != 0:
        print("error: PyInstaller build failed.", file=sys.stderr)
        return result.returncode

    # macOS windowed builds produce an .app bundle; wrap it in a drag-to-
    # Applications .dmg installer (skipped for --console, which has no .app).
    app_path = dist_dir / f"{args.name}.app"
    if os_name == "macos" and not args.console and not args.no_dmg and app_path.exists():
        dmg_path = dist_dir / f"{args.name}-macos.dmg"
        print(f">> Packaging {dmg_path.name} ...")
        build_dmg(app_path, dmg_path, volume_name=args.name)

    produced = sorted(p.name for p in dist_dir.iterdir()) if dist_dir.exists() else []
    print(f"\n>> Done. Output in {dist_dir}")
    for name in produced:
        print(f"   - {name}")
    if os_name == "macos":
        print(
            "\n   macOS note: grant the app Accessibility + Input Monitoring\n"
            "   (System Settings > Privacy & Security) or key presses silently no-op."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
