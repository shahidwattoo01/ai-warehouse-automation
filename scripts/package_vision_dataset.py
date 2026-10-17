"""Package the camera dataset for GPU training on Google Colab (Phase 5).

    python scripts/package_vision_dataset.py        # -> data/exports/warehouse_vision_v3.zip

The images in data/processed/computer_vision/ are 640 x 480 RGBA PNGs (about 1 GB). Detectors
use RGB, so they are converted to high-quality RGB JPEGs, which makes the upload to Colab several
times smaller. YOLO labels, the split (train / validation / test) and the class names are kept
exactly; frames.csv is included so results can be traced back to the simulated scene.
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "processed" / "computer_vision"
OUT = ROOT / "data" / "exports" / "warehouse_vision_v3.zip"
SPLITS = ("train", "validation", "test")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quality", type=int, default=95, help="JPEG quality (default 95)")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    names = yaml.safe_load((SRC / "data.yaml").read_text(encoding="utf-8"))["names"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with zipfile.ZipFile(args.out, "w", compression=zipfile.ZIP_STORED) as z:
        for split in SPLITS:
            images = sorted((SRC / "images" / split).glob("*.png"))
            for path in images:
                buf = io.BytesIO()
                Image.open(path).convert("RGB").save(buf, "JPEG", quality=args.quality)
                z.writestr(f"warehouse_vision/images/{split}/{path.stem}.jpg", buf.getvalue())
                label = SRC / "labels" / split / f"{path.stem}.txt"
                z.writestr(
                    f"warehouse_vision/labels/{split}/{path.stem}.txt",
                    label.read_text(encoding="utf-8") if label.exists() else "",
                )
            counts[split] = len(images)
        data = {"path": ".", "train": "images/train", "val": "images/validation",
                "test": "images/test", "nc": len(names), "names": names}  # fmt: skip
        z.writestr("warehouse_vision/data.yaml", yaml.safe_dump(data, sort_keys=False))
        z.write(SRC / "frames.csv", "warehouse_vision/frames.csv")

    size = args.out.stat().st_size / 1e6
    print(f"wrote {args.out} ({size:.0f} MB): " + ", ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
