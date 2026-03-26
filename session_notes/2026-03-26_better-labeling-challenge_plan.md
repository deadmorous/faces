# Face labeling improvements: follow mode + size filters

## Context

As the unlabeled face pool depletes, the Similar Faces view becomes noisy because
it searches across all dates with no regard for temporal proximity. Separately, both
Similar Faces and Classify views surface tiny background faces that clutter results and
slow labeling. This plan adds:

1. **Follow mode** — a symmetric time-window filter centered on the seed photo's date,
   selectable via a sidebar dropdown.
2. **Size filters** — `rel_size_min` (relative) and `min_face_px` (absolute) filters on
   the Similar Faces endpoint, plus `min_face_px` added to Classify. Both exposed as
   per-view sidebar controls persisted in `localStorage`.

Crowd-batching (point 3 from the brainstorm) is deferred.

---

## Files to modify

| File | Change |
|------|--------|
| `faces/web/routers/faces.py` | Add `time_window`, `rel_size_min`, `min_face_px` params to `get_similar_faces` |
| `faces/algo.py` | Add `min_face_px` param to `classify_candidates` |
| `faces/web/routers/classify.py` | Pass `min_face_px` through to `classify_candidates` |
| `faces/web/static/app.js` | Sidebar controls, localStorage, URL params for both views |

---

## Feature 1: Follow mode

### Backend — `faces/web/routers/faces.py`

Add to `get_similar_faces`:
```python
time_window: Optional[str] = Query(None,
    description="Symmetric window around seed photo date: day, 3days, week, month")
```

Half-day offsets mapping:
```python
_TW_HALF_DAYS = {"day": 0.5, "3days": 1.5, "week": 3.5, "month": 15.0}
```

After looking up the seed face, compute override timestamps:
```python
if time_window and time_window in _TW_HALF_DAYS:
    photo_rows = (db.photos.search()
                  .where(f"md5 = '{md5}'", prefilter=True)
                  .limit(1).to_list())
    seed_exif = photo_rows[0].get("exif_date") if photo_rows else None
    if seed_exif:
        half = _TW_HALF_DAYS[time_window] * 86400
        tw_since_ts = seed_exif - half
        tw_until_ts = seed_exif + half
```

In the per-candidate filter loop, intersect with any explicit `since_ts`/`until_ts`
already computed from the `since`/`until` string params:
```python
effective_since = max(since_ts, tw_since_ts) if (since_ts and tw_since_ts) else (since_ts or tw_since_ts)
effective_until = min(until_ts, tw_until_ts) if (until_ts and tw_until_ts) else (until_ts or tw_until_ts)
```

### Frontend — `app.js`

Similar faces sidebar: add **"Time window"** `<select>` below "Unlabeled only":
- Options: "All time" → `""`, "Same day" → `"day"`, "±3 days" → `"3days"`,
  "±1 week" → `"week"`, "±1 month" → `"month"`
- Default: `""` (all time)
- Persist: `localStorage["sb_timeWindow"]`
- URL param: append `&time_window=day` etc. (skip if empty)

---

## Feature 2: Size filters

### Backend — `faces/web/routers/faces.py`

Add to `get_similar_faces`:
```python
rel_size_min: float = Query(0.0, ge=0.0, le=1.0)
min_face_px: int    = Query(0,   ge=0)
```

In the Python-side filter loop:
```python
# rel_size filter (uses embeddings_cache rows)
if rel_size_min > 0 and cache["rows"][row_idx]["rel_size"] < rel_size_min:
    continue
# absolute size filter: min(face_width, face_height)
if min_face_px > 0:
    b = row["bbox"]  # [x1, y1, x2, y2]
    if min(b[2] - b[0], b[3] - b[1]) < min_face_px:
        continue
```

### Backend — `faces/algo.py`

Add `min_face_px: int = 0` to `classify_candidates` signature. In the unlabeled-face
loop (where `rel_size_min` is already applied), add:
```python
if min_face_px > 0:
    b = face["bbox"]
    if min(b[2] - b[0], b[3] - b[1]) < min_face_px:
        continue
```

### Backend — `faces/web/routers/classify.py`

Add `min_face_px: int = Query(0, ge=0)` to both `get_classify_people` and
`get_classify_candidates`, pass through to `classify_candidates(...)`.

### Frontend — `app.js`

**Similar Faces sidebar** — add two controls below time-window:
- "Min rel size" — `<input type="range" min=0 max=0.5 step=0.05>` with numeric display
- "Min face px" — `<input type="number" min=0 max=500 step=10>`
- Persist: `localStorage["sb_simRelSizeMin"]`, `localStorage["sb_simMinFacePx"]`
- Include in API URL: `&rel_size_min=0.1&min_face_px=40`

**Classify sidebar** — add "Min face px" input (same style as existing rel_size_min row):
- Persist: `localStorage["sb_clsMinFacePx"]`
- Include in API URL

---

## Sidebar layout (Similar Faces — after changes)

```
│ Threshold      [0.50   ]
│ Unlabeled only [ ]
│ Time window    [All time ▼]
│ Min rel size   ──●──────  0.00
│ Min face px    [  0    ]
│ [Refresh]
```

---

## Verification

```bash
uvicorn faces.web.main:app --reload
```

1. Similar Faces view: set time window to "Same day" → results are from same date as seed.
   Verify with a seed photo that has a known exif_date; neighboring-day photos should
   disappear from results.
2. Set time window on a photo with no EXIF date → no filtering, same results as "All time".
3. Set Min rel size = 0.3 → no tiny background faces in results.
4. Set Min face px = 60 → very small bbox faces filtered out; verify by comparing bbox
   dimensions of returned faces.
5. Classify view: set Min face px = 60 → same effect on candidate faces.
6. Refresh browser, reload page → sidebar values restored from localStorage.
