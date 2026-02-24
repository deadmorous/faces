#!/usr/bin/env python3
"""Visualise face bounding boxes for a photo.

Usage:
    python view_crops.py PHOTO [DB_PATH]

DB_PATH defaults to ~/.local/share/faces/index.db
"""

import sys
from pathlib import Path

import lancedb
import matplotlib.patches as patches
import matplotlib.pyplot as plt
from PIL import Image

DEFAULT_DB = Path("~/.local/share/faces/index.db").expanduser()


def main(photo_path: Path, db_path: Path) -> None:
    from faces.db import compute_md5
    md5 = compute_md5(photo_path)

    conn = lancedb.connect(db_path)
    try:
        table = conn.open_table("faces")
    except Exception:
        sys.exit(f"No faces table found in database: {db_path}")

    rows = table.search().where(f"md5 = '{md5}'", prefilter=True).to_list()

    if not rows:
        sys.exit(f"No detections found for: {photo_path}")

    img = Image.open(photo_path)
    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    ax.imshow(img)
    ax.axis("off")
    ax.set_title(photo_path.name)

    for row in rows:
        x1, y1, x2, y2 = row["bbox"]
        ax.add_patch(patches.Rectangle(
            (x1, y1), x2 - x1, y2 - y1,
            linewidth=2, edgecolor="lime", facecolor="none",
        ))
        ax.text(x1, y1 - 6, f"{row['score']:.2f}",
                color="lime", fontsize=8, fontweight="bold")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    if not (2 <= len(sys.argv) <= 3):
        sys.exit(f"Usage: {sys.argv[0]} PHOTO [DB_PATH]")
    db_path = Path(sys.argv[2]) if len(sys.argv) == 3 else DEFAULT_DB
    main(Path(sys.argv[1]), db_path)
