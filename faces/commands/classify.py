"""Classify unlabeled faces against named centroids."""

import math
from collections import defaultdict

import click
import matplotlib.pyplot as plt
import numpy as np

from ..config import Config
from ..db import (LABEL_FOREIGN, LABEL_NONFACE, SPECIAL_LABELS,
                  load_all_embeddings, open_db, stick_face)

_STOP_WORDS = {"exit", "stop", "quit", "q"}


@click.command()
@click.option("--threshold", "-t", type=float, metavar="FLOAT",
              help="Similarity threshold (0.0–1.0). Overrides the config value.")
@click.option("--min-size", type=int, default=3, show_default=True,
              help="Minimum labeled faces a named centroid must have to be used.")
@click.pass_obj
def classify(cfg: Config, threshold: float | None, min_size: int) -> None:
    """Match unlabeled faces to known people via single-linkage (min-dist) classification.

    Named clusters whose sticky faces number >= MIN_SIZE are used. Each unlabeled
    face is matched to the person whose nearest labeled face is closest (minimum
    distance over all labeled faces for that person). Every unlabeled face closer
    than eps to any person is presented as a candidate for acceptance, renaming,
    or skipping.

    After classifying, run `faces clusterize --reset` to rebuild clusters.
    """
    from ..viz import show_face

    effective_threshold = threshold if threshold is not None else cfg.cluster_threshold
    eps = math.sqrt(2.0 * (1.0 - effective_threshold))

    db = open_db(cfg.database)
    rows, X = load_all_embeddings(db)

    if not rows:
        click.echo("No faces found. Run `faces scan` first.")
        return

    # --- Build named groups ---
    named_groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if row.get("name"):
            named_groups[row["name"]].append(i)

    valid_names = {
        name for name, indices in named_groups.items()
        if len(indices) >= min_size and name not in SPECIAL_LABELS
    }

    if not valid_names:
        click.echo(
            f"No named people with >= {min_size} labeled faces found. "
            "Run `faces label --stick` or `faces stick` first."
        )
        return

    person_names = sorted(valid_names)  # stable order, (P,)

    # --- Collect unlabeled faces (special-label rejects are already named, so excluded) ---
    unlabeled_indices = [i for i, row in enumerate(rows) if not row.get("name")]

    click.echo(
        f"Classifying {len(unlabeled_indices)} unlabeled faces against "
        f"{len(person_names)} named people (min-dist, eps {eps:.4f}) …"
    )
    click.echo()

    if not unlabeled_indices:
        click.echo("All faces are already labeled.")
        return

    # --- Gather ALL labeled faces for valid persons into one matrix ---
    all_labeled_idx = [
        i for i, row in enumerate(rows)
        if row.get("name") in valid_names
    ]
    labeled_X = X[all_labeled_idx]                                  # (L, 512)
    labeled_names_arr = [rows[i]["name"] for i in all_labeled_idx]  # (L,)

    # Which columns in labeled_X belong to each person?
    person_col_map = {
        name: [j for j, n in enumerate(labeled_names_arr) if n == name]
        for name in person_names
    }

    # Full pairwise distances (U, L)
    unlabeled_X = X[unlabeled_indices]                              # (U, 512)
    diff = unlabeled_X[:, None, :] - labeled_X[None, :, :]         # (U, L, 512)
    D = np.sqrt((diff ** 2).sum(axis=2))                            # (U, L)

    # Per-person minimum distance (U, P)
    per_person = np.stack(
        [D[:, person_col_map[name]].min(axis=1) for name in person_names],
        axis=1,
    )

    best_idx = per_person.argmin(axis=1)                                       # (U,)
    best_dist = per_person[np.arange(len(unlabeled_indices)), best_idx]        # (U,)

    candidate_mask = best_dist < eps
    candidate_positions = np.where(candidate_mask)[0]

    # Sort by distance ascending (best matches first)
    order = candidate_positions[np.argsort(best_dist[candidate_positions])]

    total_candidates = len(order)
    click.echo(f"{total_candidates} candidate(s) found within eps {eps:.4f}.\n")

    if total_candidates == 0:
        return

    accepted = 0
    skipped = 0
    rejected = 0

    for rank, pos in enumerate(order, 1):
        face_idx = unlabeled_indices[pos]
        row = rows[face_idx]
        matched_name = person_names[best_idx[pos]]
        dist = float(best_dist[pos])

        click.echo(f"Candidate {rank}/{total_candidates}: {matched_name}  dist {dist:.2f}")

        show_face(
            row["md5"], row["bbox"],
            db.photos, cfg.photos_dir,
            title=f"{matched_name}  (dist {dist:.2f})",
            block=False,
        )

        try:
            response = input(
                f"→ {matched_name} (dist {dist:.2f})? "
                "[Enter=accept / n=skip / x=non-face / f=foreign / <name>=rename]: "
            ).strip()
        except EOFError:
            plt.close("all")
            break

        plt.close("all")

        if response.lower() in _STOP_WORDS:
            break

        if response.lower() == "n":
            skipped += 1
            continue

        if response.lower() == "x":
            stick_face(db, row["md5"], row["bbox"], LABEL_NONFACE)
            rejected += 1
            continue

        if response.lower() == "f":
            stick_face(db, row["md5"], row["bbox"], LABEL_FOREIGN)
            rejected += 1
            continue

        # Accept (empty) or rename (non-empty text that isn't a shortcut)
        final_name = response if response else matched_name
        stick_face(db, row["md5"], row["bbox"], final_name)
        accepted += 1

    click.echo(
        f"\nDone. {accepted} accepted/renamed, {skipped} skipped, {rejected} rejected.\n"
        "Run `faces clusterize --reset` to rebuild clusters with the new labels."
    )
