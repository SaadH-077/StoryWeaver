"""Download the on-device voice model (Kokoro-82M, ONNX) used for narration.

Usage:  uv run python scripts/download_models.py [--int8]

By default the full-precision model (~326 MB) is fetched: it is the fastest choice on most CPUs. ``--int8``
fetches the quantised model (~114 MB) instead — smaller, but on older CPUs without VNNI instructions it can
be several times slower; select it with STORYWEAVER_KOKORO_MODEL_FILE=kokoro-v1.0.int8.onnx.
Files are stored in ./models/kokoro (git-ignored). Re-running skips files that already exist.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
FILES = {
    "int8": "kokoro-v1.0.int8.onnx",
    "full": "kokoro-v1.0.onnx",
    "voices": "voices-v1.0.bin",
}
TARGET = Path(__file__).resolve().parent.parent / "models" / "kokoro"


def download(name: str) -> None:
    dest = TARGET / name
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"[skip] {name} already present ({dest.stat().st_size / 1e6:.0f} MB)")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    url = f"{RELEASE}/{name}"
    print(f"[get ] {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "storyweaver-model-downloader"})
    with urllib.request.urlopen(request, timeout=60) as response, open(tmp, "wb") as fh:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while chunk := response.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r       {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--int8", action="store_true", help="download the smaller int8 model instead")
    args = parser.parse_args()
    TARGET.mkdir(parents=True, exist_ok=True)
    download(FILES["int8" if args.int8 else "full"])
    download(FILES["voices"])
    print(f"Done. Models are in {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
