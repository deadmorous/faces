#!/usr/bin/env python3
"""Visualise all face crops belonging to a cluster.

Usage:
    python view_cluster.py [--config CONFIG] CLUSTER_ID

Photos directory and database path are resolved from the config file.
"""

import argparse
import math
import sys
from pathlib import Path

import lancedb
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

THUMB_PX = 112          # thumbnail size (square)
MAX_DISPLAY = 200       # cap to avoid huge grids
PADDING_FRAC = 0.25     # extra padding around bbox, as fraction of bbox size


def load_config(config_file=None):
    try:
        from faces.config import load
        return load(config_file)
    except Exception:
        return None


def crop_face(img: Image.Image, bbox: list[int]) -> Image.Image:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    pad_x = int(w * PADDING_FRAC)
    pad_y = int(h * PADDING_FRAC)
    cx1 = max(0, x1 - pad_x)
    cy1 = max(0, y1 - pad_y)
    cx2 = min(img.width,  x2 + pad_x)
    cy2 = min(img.height, y2 + pad_y)
    return img.crop((cx1, cy1, cx2, cy2)).resize((THUMB_PX, THUMB_PX), Image.LANCZOS)


def main(cluster_id: int, db_path: Path, photos_dir) -> None:

    conn = lancedb.connect(db_path)

    try:
        clusters_table = conn.open_table("clusters")
    except Exception:
        sys.exit(f"No clusters table in {db_path}. Run `faces clusterize` first.")

    try:
        photos_table = conn.open_table("photos")
    except Exception:
        sys.exit(f"No photos table in {db_path}.")

    # Faces in this cluster
    faces = (
        clusters_table.search()
        .where(f"cluster_id = {cluster_id}", prefilter=True)
        .to_list()
    )
    if not faces:
        sys.exit(f"Cluster {cluster_id} not found or empty.")

    total = len(faces)
    displayed = faces[:MAX_DISPLAY]
    print(f"Cluster {cluster_id}: {total} faces"
          + (f" (showing first {MAX_DISPLAY})" if total > MAX_DISPLAY else ""))

    # Build md5 → relative_path mapping for needed photos
    needed_md5s = {f["md5"] for f in displayed}
    path_map: dict[str, Path] = {}
    for md5 in needed_md5s:
        rows = (
            photos_table.search()
            .where(f"md5 = '{md5}'", prefilter=True)
            .limit(1)
            .to_list()
        )
        if rows:
            rel = rows[0]["path"]
            if photos_dir:
                path_map[md5] = photos_dir / rel
            else:
                path_map[md5] = Path(rel)

    # Collect thumbnails
    thumbs: list[tuple[np.ndarray, str]] = []
    img_cache: dict[str, Image.Image] = {}

    for face in displayed:
        md5 = face["md5"]
        photo_path = path_map.get(md5)
        if photo_path is None or not photo_path.exists():
            continue
        if md5 not in img_cache:
            try:
                img_cache[md5] = Image.open(photo_path).convert("RGB")
            except Exception:
                continue
        img = img_cache[md5]
        thumb = crop_face(img, face["bbox"])
        thumbs.append((np.array(thumb), photo_path.name))

    if not thumbs:
        sys.exit("Could not load any face crops. Check that photos_dir is correct.")

    # Layout grid
    n = len(thumbs)
    cols = math.ceil(math.sqrt(n * 1.5))   # slightly wider than tall
    rows = math.ceil(n / cols)

    fig, axes = plt.subplots(rows, cols,
                             figsize=(cols * 1.4, rows * 1.5),
                             squeeze=False)
    fig.suptitle(f"Cluster {cluster_id}  —  {total} faces", fontsize=12)

    for idx, ax in enumerate(axes.flat):
        if idx < len(thumbs):
            arr, label = thumbs[idx]
            ax.imshow(arr)
            ax.set_title(label, fontsize=5, pad=2)
        ax.axis("off")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Visualise face crops for a cluster.")
    parser.add_argument("cluster_id", type=int, metavar="CLUSTER_ID")
    parser.add_argument("--config", "-c", metavar="PATH",
                        help="Path to faces config file.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    db_path = cfg.database if cfg else Path("~/.local/share/faces/index.db").expanduser()
    photos_dir = cfg.photos_dir if cfg else None

    main(args.cluster_id, db_path, photos_dir)
