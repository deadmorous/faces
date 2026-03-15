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

## Open questions / possible paths forward

1. **Change the overflow on `.gallery-thumbs`**: removing `overflow-y: hidden`
   from `.photos-preview-band .gallery-thumbs` would let the flex container
   paint outside its own box. The browser normalises `overflow-x: auto` +
   no `overflow-y` to `overflow-y: auto`, but since content (60 px) is less
   than the container (72 px), no actual scrollbar appears and no visual
   clipping occurs. The `box-shadow` should then only hit the
   `.preview-thumbs-area` overflow boundary (8 px of headroom → fine).
   *Not yet attempted.*

2. **Wrap each thumb in a `<div>`**: style the wrapper div as the selection
   indicator (border/shadow on the div, not on the img). The wrapper can be
   given a larger box (e.g. 64 px tall) without clipping the image itself.

3. **Accept a border-only style**: drop the outer glow entirely; just change
   border colour, border-radius, and perhaps border-width for the active state.
   Matches the classify look partially, avoids all clipping issues.
