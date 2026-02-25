#!/usr/bin/env python3
"""Visualise all face crops belonging to a cluster.

Usage:
    python view_cluster.py [--config CONFIG] CLUSTER_ID

Photos directory and database path are resolved from the config file.
"""

import argparse
import sys
from pathlib import Path

import lancedb


def load_config(config_file=None):
    try:
        from faces.config import load
        return load(config_file)
    except Exception:
        return None


def main(cluster_id: int, db_path: Path, photos_dir) -> None:
    from faces.viz import show_cluster

    conn = lancedb.connect(db_path)

    try:
        clusters_table = conn.open_table("clusters")
    except Exception:
        sys.exit(f"No clusters table in {db_path}. Run `faces clusterize` first.")

    try:
        photos_table = conn.open_table("photos")
    except Exception:
        sys.exit(f"No photos table in {db_path}.")

    n = show_cluster(cluster_id, clusters_table, photos_table, photos_dir)
    if n == 0:
        sys.exit(f"Cluster {cluster_id} not found or no photos could be loaded.")


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
