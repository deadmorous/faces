"""Shared visualisation helpers for face crop grids."""

import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

THUMB_PX = 112
MAX_DISPLAY = 200
PADDING_FRAC = 0.25


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


def show_cluster(cluster_id: int, clusters_table, photos_table,
                 photos_dir: Path | None, *,
                 block: bool = True,
                 max_display: int = MAX_DISPLAY) -> int:
    """Render a grid of face thumbnails for *cluster_id*.

    Returns the number of thumbnails displayed (0 if none could be loaded).
    When *block* is False the window is shown non-blocking so the caller can
    prompt for input while the grid is visible.
    """
    faces = (
        clusters_table.search()
        .where(f"cluster_id = {cluster_id}", prefilter=True)
        .to_list()
    )
    if not faces:
        return 0

    total = len(faces)
    displayed = faces[:max_display]

    # Build md5 → photo path map.
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
            path_map[md5] = (photos_dir / rel) if photos_dir else Path(rel)

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
        thumb = crop_face(img_cache[md5], face["bbox"])
        thumbs.append((np.array(thumb), photo_path.name))

    if not thumbs:
        return 0

    n = len(thumbs)
    cols = math.ceil(math.sqrt(n * 1.5))
    rows = math.ceil(n / cols)

    fig, axes = plt.subplots(rows, cols,
                             figsize=(cols * 1.4, rows * 1.5),
                             squeeze=False)
    suffix = f" (showing {max_display} of {total})" if total > max_display else ""
    fig.suptitle(f"Cluster {cluster_id}  —  {total} faces{suffix}", fontsize=12)

    for idx, ax in enumerate(axes.flat):
        if idx < len(thumbs):
            arr, label = thumbs[idx]
            ax.imshow(arr)
            ax.set_title(label, fontsize=5, pad=2)
        ax.axis("off")

    plt.tight_layout()
    plt.show(block=block)
    if not block:
        plt.pause(0.1)   # ensure the window renders before returning

    return len(thumbs)
