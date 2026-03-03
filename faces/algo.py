"""Shared algorithmic functions for classify and clusterize, reused by CLI and web."""

import math
from collections import Counter, defaultdict

import numpy as np

from .db import (
    SPECIAL_LABELS, Database,
    load_all_embeddings, load_photo_dates, parse_date,
    reset_clusters, store_clusters,
)


def classify_candidates(
    db: Database,
    threshold: float,
    min_size: int = 3,
    since: str | None = None,
    until: str | None = None,
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

    unlabeled_X = X[unlabeled_indices]
    diff = unlabeled_X[:, None, :] - labeled_X[None, :, :]
    D = np.sqrt((diff ** 2).sum(axis=2))

    per_person = np.stack(
        [D[:, person_col_map[name]].min(axis=1) for name in person_names],
        axis=1,
    )

    best_idx = per_person.argmin(axis=1)
    best_dist = per_person[np.arange(len(unlabeled_indices)), best_idx]

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
        faces = sorted(person_groups[person], key=lambda f: f["dist"])
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


def run_clusterize(db: Database, threshold: float, reset: bool) -> dict:
    """Run agglomerative clustering and store results.

    Returns:
      {
        "clusters_created": int,
        "auto_named": int,
        "must_link_pairs": int,
        "cannot_link_pairs": int,
      }

    Raises ValueError("clusters_exist") if clusters exist and reset is False.
    """
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import pairwise_distances

    eps = math.sqrt(2.0 * (1.0 - threshold))

    existing = db.clusters.count_rows()
    if existing > 0 and not reset:
        raise ValueError("clusters_exist")

    if reset and existing > 0:
        reset_clusters(db)

    rows, X = load_all_embeddings(db)
    if len(rows) == 0:
        return {
            "clusters_created": 0,
            "auto_named": 0,
            "must_link_pairs": 0,
            "cannot_link_pairs": 0,
        }

    names = [row["name"] for row in rows]
    real_names = [n if (n and n not in SPECIAL_LABELS) else None for n in names]

    must_link = 0
    cannot_link = 0
    if any(real_names):
        D = pairwise_distances(X, metric="euclidean")
        for i in range(len(rows)):
            if not real_names[i]:
                continue
            for j in range(i + 1, len(rows)):
                if not real_names[j]:
                    continue
                if real_names[i] == real_names[j]:
                    D[i, j] = D[j, i] = 0.0
                    must_link += 1
                else:
                    D[i, j] = D[j, i] = 2.0
                    cannot_link += 1
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=eps,
            metric="precomputed",
            linkage="complete",
        ).fit_predict(D)
    else:
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=eps,
            metric="euclidean",
            linkage="complete",
        ).fit_predict(X)

    auto_named = store_clusters(db, rows, labels)
    n_clusters = len(Counter(labels))

    return {
        "clusters_created": n_clusters,
        "auto_named": auto_named,
        "must_link_pairs": must_link,
        "cannot_link_pairs": cannot_link,
    }
