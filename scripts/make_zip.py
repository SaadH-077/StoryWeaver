"""Package the submission ZIP: <Firstname_Lastname>_Immersive_Storytelling_Agent.zip

  uv run python scripts/make_zip.py --name Muhammad_Haroon

Excludes secrets, the virtual environment, downloaded models, runtime media and caches, and refuses to build if
any secret value from .env appears in a file that would be shipped.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {".venv", "models", "runtime", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".idea",
                 ".vscode", "node_modules", "dist", "build"}
EXCLUDED_FILES = {".env"}
EXCLUDED_SUFFIXES = {".pyc", ".log", ".part", ".tmp"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".lock", ".json", ".js", ".css", ".html", ".example", ".yml",
                 ".yaml", ".cfg", ".ini", ""}
MAX_VIDEO_MB = 200


def secret_values() -> list[str]:
    env = ROOT / ".env"
    if not env.exists():
        return []
    values = []
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if len(value) >= 16:
                values.append(value)
    return values


def shipped_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts) or not path.is_file():
            continue
        if path.name in EXCLUDED_FILES or path.suffix in EXCLUDED_SUFFIXES or path.name.endswith(".egg-info"):
            continue
        if any(part.endswith(".egg-info") for part in rel.parts) or rel.parts[:2] == ("eval", "cache"):
            continue  # downloaded datasets are re-fetched by eval/sources.py
        files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="Muhammad_Haroon", help="Firstname_Lastname for the ZIP file name")
    parser.add_argument("--out", type=Path, default=ROOT.parent, help="folder to write the ZIP into")
    args = parser.parse_args()

    files = shipped_files()
    secrets = secret_values()
    leaks = []
    for path in files:
        if path.suffix in TEXT_SUFFIXES or path.name.startswith("."):
            text = path.read_text(encoding="utf-8", errors="ignore")
            leaks += [str(path.relative_to(ROOT)) for secret in secrets if secret in text]
    if leaks:
        print("REFUSING to package — secret values found in:", *sorted(set(leaks)), sep="\n  ")
        return 1
    big = [p for p in files if p.stat().st_size > MAX_VIDEO_MB * 1024 * 1024]
    if big:
        print("Files over", MAX_VIDEO_MB, "MB — link them instead:", *big, sep="\n  ")
        return 1

    target = args.out / f"{args.name}_Immersive_Storytelling_Agent.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, Path("storyweaver") / path.relative_to(ROOT))
    size = target.stat().st_size / 1e6
    print(f"Wrote {target} ({len(files)} files, {size:.1f} MB). Secret scan: clean ({len(secrets)} values checked).")
    if not (ROOT / "demo").exists():
        print("Note: no demo/ folder — add the demo video (or a private link in README) before submitting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
