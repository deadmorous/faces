# Performance Improvement Plan

## Measured baseline (24 783 faces, 56 persons, ~12 k labeled / ~12 k unlabeled)

| Operation | Time |
|---|---|
| `build_people_cache` DB scan | ~3.0 s |
| `load_all_embeddings` DB scan | ~3.3 s |
| `load_all_embeddings` numpy build | ~0.44 s |
| `classify_candidates: load_all_embeddings` | ~3.8 s |
| `classify_candidates: cdist` (12 351 × 12 376, 56 persons) | ~22 s |
| Full classify request (cache miss) | ~26 s |

---

## Easy win 1 — Incremental `people_cache` (no more full DB scans)

### Problem
Every label change triggers a full faces-table scan (~3 s) to rebuild the people list.

### Solution
Extend the in-memory cache to store the **set of photo md5s** per person alongside
`face_count`. This lets every mutation be handled without touching the DB:

```
cache entry: {name → {face_count: int, photo_md5s: set[str]}}
photo_count is always len(photo_md5s)
```

**`POST /api/classify/labels` (submit_labels) — labeling previously-unlabeled faces:**
- For each group keyed by `name`:
  - If `name is None`: no-op — faces were unlabeled before, still unlabeled.
  - If `name` is known: `face_count += len(items)`, `photo_md5s |= {item.md5}`.
  - If `name` is new: create entry.

**`PATCH /api/people/{name}` (rename_person):**
- `new_name is None` (clear all labels): remove person from cache. No DB scan needed —
  face_count is already in cache, and since ALL faces are cleared, the person disappears
  entirely.
- `new_name` is a brand-new name: rename the key in cache.
- `new_name` already exists (merge): sum `face_count`, union `photo_md5s`, keep one entry.

**Result:** zero DB scans for any cache maintenance path.

### Implementation notes
- `build_people_cache` still does a full scan once at startup (and never again unless
  the server restarts).
- The existing `list[Person]` response shape is unchanged; derive it from the dict at
  serve time.

---

## Easy win 2 — Cache `(rows, X)` from `load_all_embeddings`

### Problem
`classify_candidates` calls `load_all_embeddings` every time the cache is invalidated
(~3.8 s). The embedding matrix never changes between scans — only the `name` field on
rows changes.

### Solution
Store `(rows, X)` in `app.state.embeddings_cache` at startup. The matrix `X` is
immutable. When `submit_labels` fires, update `rows[i]["name"]` in-place for the
affected rows (identified by md5 + bbox match).

**Cache invalidation:** never expires. Restart the server after a new scan.

**Result:** `classify_candidates` no longer pays the 3.8 s load cost after the first
call on a fresh server start (the classify cache already covers repeated page navigation,
but now even the first call after a label submit is faster).

---

## Main bottleneck — classify_candidates cdist (~22 s)

### Root cause
`cdist(12 351 × 512, 12 376 × 512)` computes ~150 M euclidean distances.
56 persons × ~221 labeled faces/person on average.

### Options

#### Option A — Per-person centroids (recommended starting point)
Replace min-distance-to-any-labeled-face with distance-to-centroid:

```
current:  dist(face, person) = min(euclidean(face, lf) for lf in labeled_faces[person])
centroid: dist(face, person) = euclidean(face, mean(labeled_faces[person]))
```

Matrix shrinks from (12 351, 12 376) to (12 351, 56) → milliseconds.

**Trade-off:** centroid distance is less sensitive to edge cases (people who appear very
differently in different photos). With ~221 labeled samples per person, centroids are
likely stable. The eps threshold means something slightly different (distance to centroid
vs. nearest sample), so the value may need tuning.

**Speedup estimate:** ~200× for the cdist step → total classify < 1 s.

#### Option B — Subsample per person (min-dist approximation)
Keep min-dist semantics but limit to at most N labeled faces per person (e.g. random
sample of 50). 56 × 50 = 2 800 labeled faces → matrix (12 351, 2 800) → ~2 s.

**Trade-off:** random subsample may miss the closest sample. Could pick a better
subsample (spread across embedding space), but adds complexity.

**Speedup estimate:** ~8× for cdist step.

#### Option C — Lazy per-page computation
Only compute candidates for persons on the current page, not all 56 at once. Combined
with the embeddings cache this means first-page latency is 22 s/56 × 10 ≈ 4 s (if
persons are processed independently), and later pages are fast because classify cache
already covers them.

**Trade-off:** complicates the algorithm (need page-stable ordering before computing);
total work is unchanged; only latency for first page improves.

#### Option D — LanceDB ANN vector search
Use `db.faces.search(query_vector).limit(k)` for each unlabeled face to find its nearest
labeled neighbors directly in the DB without loading everything into memory.

**Trade-off:** major algorithm rewrite; scales to millions of faces; requires building
an ANN index on the faces table; latency per query vs. batch cdist unclear at this scale.

### Recommendation pending decision
Options A and B are the easiest to implement. A is likely accurate enough given the
volume of labeled data and gives the largest speedup. B preserves exact semantics at
the cost of some approximation.

---

## Implementation order (once options are decided)

1. Embeddings cache in `app.state` (easy win 2) — unblocks faster classify regardless
   of which cdist option is chosen.
2. Incremental people cache (easy win 1).
3. Chosen cdist option (A or B recommended).
