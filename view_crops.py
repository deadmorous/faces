#!/usr/bin/env python3
"""Visualise face bounding boxes for a photo.

Usage:
    python view_crops.py PHOTO CROPS_DIR
"""

import json
import sys
from pathlib import Path

import matplotlib.patches as patches
import matplotlib.pyplot as plt
from PIL import Image


def main(photo_path: Path, crops_dir: Path) -> None:
    json_path = crops_dir / (photo_path.stem + ".json")
    if not json_path.exists():
        sys.exit(f"No crop file found: {json_path}")

    data = json.loads(json_path.read_text())
    img = Image.open(photo_path)

    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    ax.imshow(img)
    ax.axis("off")
    ax.set_title(photo_path.name)

    for face in data["faces"]:
        x1, y1, x2, y2 = face["bbox"]
        ax.add_patch(patches.Rectangle(
            (x1, y1), x2 - x1, y2 - y1,
            linewidth=2, edgecolor="lime", facecolor="none",
        ))
        ax.text(x1, y1 - 6, f"{face['score']:.2f}",
                color="lime", fontsize=8, fontweight="bold")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} PHOTO CROPS_DIR")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
