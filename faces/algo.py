"""Shared algorithmic functions for classify and clusterize, reused by CLI and web."""

import math
from collections import defaultdict

import numpy as np

from .db import (
    SPECIAL_LABELS, Database,
    load_all_embeddings, load_photo_dates, parse_date,
)
from .timing import timed


def classify_candidates(
    db: Database,
    threshold: float,
    min_size: int = 3,
    since: str | None = None,
    until: str | None = None,
    rows: list[dict] | None = None,
    X: np.ndarray | None = None,
) -> dict:
    """Run single-linkage classify logic and return grouped candidates.

    Returns a dict:
      {
        "eps": float,
        "groups": [
          {
            "person": str,
            "avg_dist": float,
            "faces": [{"md5": str, "bbox": list[int], "dist": float}]
          }
        ],
        "unmatched": [{"md5": str, "bbox": list[int]}]
      }

    Groups are sorted by avg_dist ascending (most confident first).
    Within each group, faces are sorted by dist ascending.
    """
    eps = math.sqrt(2.0 * (1.0 - threshold))

    try:
        since_ts = parse_date(since) if since else None
        until_ts = parse_date(until, end_of_period=True) if until else None
    except ValueError as e:
        raise ValueError(str(e))

    if rows is None or X is None:
        with timed("classify_candidates: load_all_embeddings"):
            rows, X = load_all_embeddings(db)

    photo_mtimes: dict[str, float] | None = None
    if since_ts is not None or until_ts is not None:
        photo_mtimes = load_photo_dates(db)

    if not rows:
        return {"eps": eps, "groups": [], "unmatched": []}

    # Build named groups
    named_groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if row.get("name"):
            named_groups[row["name"]].append(i)

    valid_names = {
        name for name, indices in named_groups.items()
        if len(indices) >= min_size and name not in SPECIAL_LABELS
    }

    def _in_time_range(row: dict) -> bool:
        if photo_mtimes is None:
            return True
        mt = photo_mtimes.get(row["md5"])
        if mt is None:
            return False
        if since_ts is not None and mt < since_ts:
            return False
        if until_ts is not None and mt >= until_ts:
            return False
        return True

    unlabeled_indices = [
        i for i, row in enumerate(rows)
        if not row.get("name") and _in_time_range(row)
    ]

    if not valid_names or not unlabeled_indices:
        unmatched = [
            {"md5": rows[i]["md5"], "bbox": rows[i]["bbox"]}
            for i in unlabeled_indices
        ]
        return {"eps": eps, "groups": [], "unmatched": unmatched}

    person_names = sorted(valid_names)

    all_labeled_idx = [
        i for i, row in enumerate(rows)
        if row.get("name") in valid_names
    ]
    labeled_X = X[all_labeled_idx]
    labeled_names_arr = [rows[i]["name"] for i in all_labeled_idx]

    person_col_map = {
        name: [j for j, n in enumerate(labeled_names_arr) if n == name]
        for name in person_names
    }

    from scipy.spatial.distance import cdist

    unlabeled_X = X[unlabeled_indices]
    n_unlabeled = len(unlabeled_indices)
    n_labeled = len(all_labeled_idx)
    n_persons = len(person_names)
    with timed(f"classify_candidates: cdist ({n_unlabeled} unlabeled × {n_labeled} labeled, {n_persons} persons)"):
        D = cdist(unlabeled_X, labeled_X, metric="euclidean")

        per_person = np.stack(
            [D[:, person_col_map[name]].min(axis=1) for name in person_names],
            axis=1,
        )

        best_idx = per_person.argmin(axis=1)
        best_dist = per_person[np.arange(n_unlabeled), best_idx]

    candidate_mask = best_dist < eps

    # Group candidates by person
    person_groups: dict[str, list[dict]] = defaultdict(list)
    for pos in range(len(unlabeled_indices)):
        if candidate_mask[pos]:
            face_idx = unlabeled_indices[pos]
            row = rows[face_idx]
            matched_name = person_names[best_idx[pos]]
            dist = float(best_dist[pos])
            person_groups[matched_name].append({
                "md5": row["md5"],
                "bbox": row["bbox"],
                "dist": dist,
            })

    # Sort faces within each group, compute avg_dist
    groups = []
    for person in person_names:
        if person not in person_groups:
            continue
        faces = sorted(person_groups[person], key=lambda f: f["dist"])[:100]
        avg_dist = sum(f["dist"] for f in faces) / len(faces)
        groups.append({
            "person": person,
            "avg_dist": avg_dist,
            "faces": faces,
        })
    groups.sort(key=lambda g: g["avg_dist"])

    unmatched = [
        {"md5": rows[unlabeled_indices[pos]]["md5"], "bbox": rows[unlabeled_indices[pos]]["bbox"]}
        for pos in range(len(unlabeled_indices))
        if not candidate_mask[pos]
    ]

    return {"eps": eps, "groups": groups, "unmatched": unmatched}


