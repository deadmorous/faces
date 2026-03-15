# Preview strip auto-scroll problem

## Goal

When the user navigates with `<` / `>` buttons (or keyboard arrows), the active
thumbnail in the preview band should scroll into view automatically. Clicking a
thumbnail that is already visible should **not** cause any scroll.

## Attempted approach

In `_renderPhotosGallery`, after `app.innerHTML = html`:

1. **Save** the old strip's `scrollLeft` before replacing the DOM.
2. **Restore** it on the newly-rendered strip immediately after.
3. **Conditionally scroll** the active thumb into view only when it is outside
   the visible area.

The save/restore step ensures that clicking a visible thumbnail sees the same
scroll position as before the re-render, so step 3 should be a no-op for that
case.

## Why it doesn't work reliably

Several visibility-check strategies were tried; all showed the same two symptoms:

- **Pressing `<` from leftmost visible photo**: sometimes scrolls, sometimes not.
- **Pressing `>`**: scrolling triggers ~4–5 thumbs before the actual edge of the
  visible area (as if the computed visible window is too narrow).

Theories investigated:

| Theory | Verdict |
|---|---|
| `_strip.getBoundingClientRect()` returns full scroll-content width | Unlikely — for a constrained flex item it should return the layout box |
| `_strip.clientWidth` is reduced by scrollbar gutter (Windows) | ~15 px off, not enough to explain 4-5 thumbs |
| `scrollIntoView` scrolls non-strip ancestors (window, body) | `body.photos-active` has `overflow:hidden`; body shouldn't scroll, but viewport offset might still confuse `scrollIntoView`'s visibility check |
| Thumb scrolled off left but still in positive viewport x (clipped by sidebar) | Plausible for the "may or may not" left-navigation symptom |
| `innerHTML` DOM rebuild + `scrollLeft` assignment before first paint | Unlikely — both `scrollLeft` write and `getBoundingClientRect` force reflow |

## What more info would help

- Actual values of `_strip.scrollLeft`, `_strip.clientWidth`,
  `_activeThumb.getBoundingClientRect()`, and `_strip.getBoundingClientRect()`
  logged to console at the moment of the check.
- Whether the bug reproduces on macOS (overlay scrollbars, no gutter) vs Windows.
- Whether it reproduces with a very small number of thumbnails (all visible
  without scrolling at all).

## Code location

`faces/web/static/app.js`, function `_renderPhotosGallery`, around the
`_prevStripScroll` block (search for that variable name).
