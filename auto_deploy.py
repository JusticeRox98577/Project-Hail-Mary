"""
Project Hail Mary - Auto Deploy
Watches a folder for exported .mu files and moves them to the mod's
Models folder if the name matches a known part.

Usage: python auto_deploy.py
       python auto_deploy.py --watch "C:/some/other/folder"
"""

import os
import sys
import shutil
import time
import argparse
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
MODELS_DIR   = SCRIPT_DIR / "GameData" / "ProjectHailMary" / "Models"
DEFAULT_WATCH = Path.home() / "Desktop"   # change if you export elsewhere

VALID_PARTS = {
    "astrophage_tank_large",
    "astrophage_tank_small",
    "hailmary_pod",
    "astrophage_drive",
    "petrova_spectrometer",
    "rocky_comms_array",
}

POLL_INTERVAL = 1.5   # seconds between checks

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def deploy(src: Path):
    name = src.stem   # filename without .mu
    if name not in VALID_PARTS:
        return False

    dest = MODELS_DIR / src.name
    shutil.copy2(src, dest)
    log(f"Deployed: {src.name}  →  {dest}")
    return True

# ── Watcher ───────────────────────────────────────────────────────────────────

def watch(folder: Path):
    if not folder.exists():
        print(f"ERROR: Watch folder does not exist: {folder}")
        sys.exit(1)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print("  Project Hail Mary — Auto Deploy")
    print("=" * 55)
    print(f"  Watching : {folder}")
    print(f"  Models   : {MODELS_DIR}")
    print(f"  Parts    : {', '.join(sorted(VALID_PARTS))}")
    print("=" * 55)
    print("  Export a .mu from Blender and it will appear here.")
    print("  Press Ctrl+C to stop.\n")

    seen = {}   # path → last modified time

    while True:
        try:
            for f in folder.glob("*.mu"):
                mtime = f.stat().st_mtime
                if seen.get(f) != mtime:
                    seen[f] = mtime
                    if deploy(f):
                        pass   # already logged
                    else:
                        log(f"Ignored (unknown part): {f.name}")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopped.")
            break

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PHM Auto Deploy")
    parser.add_argument(
        "--watch", "-w",
        default=str(DEFAULT_WATCH),
        help=f"Folder to watch for .mu exports (default: {DEFAULT_WATCH})"
    )
    args = parser.parse_args()
    watch(Path(args.watch))
