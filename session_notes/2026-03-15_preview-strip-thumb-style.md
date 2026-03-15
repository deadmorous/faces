# Preview-strip thumbnail styling — attempts log

**Goal**: make active/inactive thumbnails in the preview band look the same as
selected/unselected faces in the Classify view.

**Target style** (Classify, `.face-grid img.selected`):
```css
border: 2px solid var(--pico-primary);
border-radius: 8px;
box-shadow: 0 0 0 2px var(--pico-primary-hover);  /* outer glow */
transition: border-color 0.15s, border-radius 0.15s, box-shadow 0.15s;
```

---

## Root cause of the difficulty

The preview strip container chain clips any decoration that extends outside the
thumbnail's 60 px border-box:

```
.preview-thumbs-area        overflow: hidden; height: 100%
  └─ .gallery-thumbs        overflow-x: auto; overflow-y: hidden   ← key clipper
       └─ img.gallery-thumb  height: 60px (border-box)
```

`.photos-preview-band .gallery-thumbs` sets `overflow-y: hidden`. The
`.gallery-thumbs` flex container auto-sizes to its content (60 px). Any paint
that escapes that 60 px box — box-shadow, outline, drop-shadow filter — is
clipped there.

The band itself is only 72 px tall (with `align-items: center`), giving 6 px of
headroom above and below the image box, but the clipper acts before that
matters.

---

## Attempts made (all reverted)

### Attempt 1 — `box-shadow: 0 0 0 2px` + band height 72→76 px
- Same `box-shadow` as the Classify style.
- Shadow still visually clipped at top/bottom of the strip.

### Attempt 2 — `outline: 2px solid` + `outline-offset: 0`
- CSS spec says `outline` is not clipped by `overflow`.
- In practice (Chrome / the browser under test) the outline was still clipped
  vertically.  Possibly a browser bug, or the spec exclusion does not apply when
  both `overflow-x: auto` and `overflow-y: hidden` are set on the same element.

### Attempt 3 — `filter: drop-shadow(0 0 3px …)`
- `filter` creates a compositing layer; the spec says it is not clipped by
  ancestor `overflow`.
- Visually: rendered the border thinner (CSS border interacted with the filter)
  and the shadow was still clipped.  Also diverges from the Classify style
  which uses `box-shadow`, not `filter`.

---

## Solution — `<span>` wrapper with padding (commit 81e8ba3)

Each `<img class="gallery-thumb">` is wrapped in
`<span class="gallery-thumb-wrap [active]" data-idx="…">`.  The span has
`padding: 3px`, making it 66 px tall (60 px image + 3 px × 2).  The
`.gallery-thumbs` flex container now sizes to the spans (66 px), so
`overflow-y: hidden` clips at 66 px.  The box-shadow (2 px spread) extends at
most 2 px outside the image — still within the 3 px span padding — and is
therefore never clipped.

```
.preview-thumbs-area        overflow: hidden; height: 100% (74px)
  └─ .gallery-thumbs        overflow-x: auto; overflow-y: hidden (clips at 66px)
       └─ span.gallery-thumb-wrap  padding: 3px  → 66px tall  ← new wrapper
            └─ img.gallery-thumb   60px + box-shadow (2px) fits inside span
```

The active class and `data-idx` live on the span; `.gallery-thumb` retains
only the visual image styles.  Active state:

```css
.gallery-thumb-wrap.active .gallery-thumb {
  border-color: var(--pico-primary);
  border-radius: 8px;
  box-shadow: 0 0 0 2px var(--pico-primary-hover);
}
```

Band height bumped 72 → 74 px for a little breathing room around the 66 px
wrapper row.
