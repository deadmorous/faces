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



def show_face(md5: str, bbox, photos_table, photos_dir: Path | None,
              title: str = "", block: bool = False) -> bool:
    """Show a single face crop. Returns True if image loaded successfully."""
    rows = (
        photos_table.search()
        .where(f"md5 = '{md5}'", prefilter=True)
        .limit(1)
        .to_list()
    )
    if not rows:
        return False
    rel = rows[0]["path"]
    photo_path = (photos_dir / rel) if photos_dir else Path(rel)
    if not photo_path.exists():
        return False
    try:
        img = Image.open(photo_path).convert("RGB")
    except Exception:
        return False

    thumb = crop_face(img, bbox)
    fig, ax = plt.subplots(1, 1, figsize=(2.5, 2.5))
    ax.imshow(np.array(thumb))
    ax.axis("off")
    if title:
        fig.suptitle(title, fontsize=10)
    plt.tight_layout()
    plt.show(block=block)
    if not block:
        plt.pause(0.1)
    return True
