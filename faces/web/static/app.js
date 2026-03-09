"use strict";

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------
const SPECIAL_LABELS = ["__nonface__", "__foreign__"];
let _cleanup = null;

// Shared sidebar params (persisted across page loads)
const _params = {
  threshold:   parseFloat(localStorage.getItem("sb_threshold")   || "1.0"),
  relSizeMin:  parseFloat(localStorage.getItem("sb_relSizeMin")  || "0.0"),
  dateFrom:    localStorage.getItem("sb_dateFrom")    || "",
  dateTo:      localStorage.getItem("sb_dateTo")      || "",
  refDateFrom: localStorage.getItem("sb_refDateFrom") || "",
  refDateTo:   localStorage.getItem("sb_refDateTo")   || "",
  photoLabels: localStorage.getItem("sb_photoLabels") || "",
  photoSort:   localStorage.getItem("sb_photoSort")   || "date_asc",
  showFaces:   localStorage.getItem("sb_showFaces") === "true",
};
let _currentView     = null;   // "unlabeled" | "classify" | "similar" | ...
let _currentViewArgs = {};     // per-view re-render args
let _algorithms      = null;   // cached from /api/classify/algorithms

// Gallery state
let _photosList = [];
let _galleryKeyHandler = null;
let _galleryResizeHandler = null;
let _galleryResizeTimer = null;
let _injectBboxOverlays = null;
const THUMB_PAGE_SIZE = 50;

function _galleryCleanupListeners() {
  if (_galleryKeyHandler)    { document.removeEventListener("keydown", _galleryKeyHandler); _galleryKeyHandler = null; }
  if (_galleryResizeHandler) { window.removeEventListener("resize", _galleryResizeHandler); _galleryResizeHandler = null; }
  clearTimeout(_galleryResizeTimer);
  _injectBboxOverlays = null;
}

function _findFallbackIdx(photos) {
  const sort = _params.photoSort;
  const date = _currentViewArgs.currentExifDate;
  const path = _currentViewArgs.currentPath;
  if (!photos.length) return 0;
  let best = -1;
  for (let i = 0; i < photos.length; i++) {
    const d = photos[i].exif_date, p = photos[i].path;
    if      (sort === "date_asc" && d != null && d < date) best = i;
    else if (sort === "path_asc" && p != null && p < path) best = i;
  }
  return best >= 0 ? best : 0;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function apiFetch(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  if (res.status === 204) return null;
  return res.json();
}

async function apiPatch(path, body) {
  const res = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function formatDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString();
}

function bboxToQuery(bbox) {
  return bbox.join(",");
}

function bboxToPathParam(bbox) {
  return bbox.join("_");
}

function dateQs() {
  const p = [];
  if (_params.dateFrom) p.push(`since=${_params.dateFrom}`);
  if (_params.dateTo)   p.push(`until=${_params.dateTo}`);
  return p.join("&");
}
function refDateQs() {
  const p = [];
  if (_params.refDateFrom) p.push(`ref_since=${_params.refDateFrom}`);
  if (_params.refDateTo)   p.push(`ref_until=${_params.refDateTo}`);
  return p.join("&");
}
function appendQs(base, qs) {
  return qs ? `${base}&${qs}` : base;
}
function _photosFilterQs() {
  const parts = [dateQs(), `sort=${_params.photoSort}`];
  if (_params.photoLabels.trim())
    parts.push(`labels=${encodeURIComponent(_params.photoLabels.trim())}`);
  return parts.filter(Boolean).join("&");
}

// Attach rubber-band rectangular selection to a face grid.
// onRectSelect(imgElements, mode) is called with all <img>s inside the drawn
// rectangle.  mode is "select" (default), "deselect" (Shift), or "invert" (Ctrl).
// Returns a cleanup function (removes listeners, discards any in-progress rect).
function attachRectSelect(gridEl, onRectSelect) {
  let startX, startY, startMode, dragging = false, rectEl = null;

  function onMouseDown(e) {
    if (e.button !== 0 || e.target.closest("a")) return;
    startX = e.clientX;
    startY = e.clientY;
    startMode = e.shiftKey ? "deselect" : e.ctrlKey ? "invert" : "select";
    dragging = false;
  }

  function onMouseMove(e) {
    if (startX === undefined) return;
    const dx = e.clientX - startX, dy = e.clientY - startY;
    if (!dragging && Math.hypot(dx, dy) < 6) return;
    if (!dragging) {
      dragging = true;
      rectEl = document.createElement("div");
      rectEl.className = "rect-select rect-select--" + startMode;
      document.body.appendChild(rectEl);
      document.body.style.userSelect = "none";
    }
    rectEl.style.left   = Math.min(startX, e.clientX) + "px";
    rectEl.style.top    = Math.min(startY, e.clientY) + "px";
    rectEl.style.width  = Math.abs(dx) + "px";
    rectEl.style.height = Math.abs(dy) + "px";
  }

  function onMouseUp(e) {
    if (startX === undefined) return;
    startX = undefined;
    if (!dragging) return;
    dragging = false;
    document.body.style.userSelect = "";
    const sel = rectEl.getBoundingClientRect();
    rectEl.remove(); rectEl = null;
    // Suppress the click event that fires after mouseup on the same element.
    document.addEventListener("click", e => e.stopPropagation(), { capture: true, once: true });
    const hit = Array.from(gridEl.querySelectorAll("img")).filter(img => {
      const r = img.getBoundingClientRect();
      return r.left < sel.right && r.right > sel.left &&
             r.top  < sel.bottom && r.bottom > sel.top;
    });
    if (hit.length) onRectSelect(hit, startMode);
  }

  gridEl.addEventListener("mousedown", onMouseDown);
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup",   onMouseUp);
  return function cleanup() {
    gridEl.removeEventListener("mousedown", onMouseDown);
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup",   onMouseUp);
    if (rectEl) { rectEl.remove(); rectEl = null; }
    document.body.style.userSelect = "";
  };
}

function showSpinner() {
  document.getElementById("app").innerHTML =
    '<div aria-busy="true" style="text-align:center;padding:3rem;">Loading…</div>';
}

function showError(msg) {
  document.getElementById("app").innerHTML =
    `<article style="color:var(--pico-del-color)"><strong>Error:</strong> ${msg}</article>`;
}

// ---------------------------------------------------------------------------
// Sidebar helpers
// ---------------------------------------------------------------------------
function setSidebarView(view) {
  const showThresh     = ["classify", "similar"].includes(view);
  const showRelSize    = ["unlabeled", "classify", "similar"].includes(view);
  const showAlgo       = view === "classify";
  const showDateRange  = ["unlabeled", "classify", "similar", "photos", "personDetail", "personFaces"].includes(view);
  const showRefRange   = view === "classify";
  const showFaces      = view === "photos";
  const showLabels     = view === "photos";
  const showSort       = view === "photos";
  document.getElementById("sb-group-threshold").classList.toggle("hidden", !showThresh);
  document.getElementById("sb-group-relsize")  .classList.toggle("hidden", !showRelSize);
  document.getElementById("sb-group-algo")     .classList.toggle("hidden", !showAlgo);
  document.getElementById("sb-group-daterange").classList.toggle("hidden", !showDateRange);
  document.getElementById("sb-group-faces")    .classList.toggle("hidden", !showFaces);
  document.getElementById("sb-group-labels")   .classList.toggle("hidden", !showLabels);
  document.getElementById("sb-group-sort")     .classList.toggle("hidden", !showSort);
  document.getElementById("sb-group-refrange") .classList.toggle("hidden", !showRefRange);
}

function rerenderCurrentView() {
  switch (_currentView) {
    case "unlabeled":    renderUnlabeled(_currentViewArgs.page || 1); break;
    case "classify":     renderClassify(); break;
    case "similar":      renderSimilar(
      _currentViewArgs.md5, _currentViewArgs.bboxParam,
      _currentViewArgs.unlabeledOnly); break;
    case "photos":       renderPhotos(); break;
    case "personDetail": renderPersonDetail(_currentViewArgs.name, _currentViewArgs.page || 1); break;
    case "personFaces":  renderPersonFaces(_currentViewArgs.name, _currentViewArgs.page || 1); break;
  }
}

function initSidebar() {
  const sbThresh     = document.getElementById("sb-thresh");
  const sbThreshVal  = document.getElementById("sb-thresh-val");
  const sbRelSize    = document.getElementById("sb-rel-size");
  const sbRelSizeVal = document.getElementById("sb-rel-size-val");

  sbThresh.value           = _params.threshold;
  sbThreshVal.textContent  = _params.threshold.toFixed(2);
  sbRelSize.value          = _params.relSizeMin;
  sbRelSizeVal.textContent = _params.relSizeMin.toFixed(2);

  // Restore date inputs from params
  const sbDateFrom = document.getElementById("sb-date-from");
  const sbDateTo   = document.getElementById("sb-date-to");
  const sbRefFrom  = document.getElementById("sb-ref-from");
  const sbRefTo    = document.getElementById("sb-ref-to");
  if (_params.dateFrom)    sbDateFrom.value = _params.dateFrom;
  if (_params.dateTo)      sbDateTo.value   = _params.dateTo;
  if (_params.refDateFrom) sbRefFrom.value  = _params.refDateFrom;
  if (_params.refDateTo)   sbRefTo.value    = _params.refDateTo;

  let threshTimer, relSizeTimer;
  sbThresh.addEventListener("input", e => {
    _params.threshold = parseFloat(e.target.value);
    sbThreshVal.textContent = _params.threshold.toFixed(2);
    localStorage.setItem("sb_threshold", _params.threshold);
    clearTimeout(threshTimer);
    threshTimer = setTimeout(rerenderCurrentView, 400);
  });
  sbRelSize.addEventListener("input", e => {
    _params.relSizeMin = parseFloat(e.target.value);
    sbRelSizeVal.textContent = _params.relSizeMin.toFixed(2);
    localStorage.setItem("sb_relSizeMin", _params.relSizeMin);
    clearTimeout(relSizeTimer);
    relSizeTimer = setTimeout(rerenderCurrentView, 400);
  });
  document.getElementById("sb-algo").addEventListener("change", e => {
    _classifyAlgo = e.target.value;
    localStorage.setItem("classifyAlgo", _classifyAlgo);
    rerenderCurrentView();
  });

  sbDateFrom.addEventListener("change", e => {
    _params.dateFrom = e.target.value.trim();
    localStorage.setItem("sb_dateFrom", _params.dateFrom);
    rerenderCurrentView();
  });
  sbDateTo.addEventListener("change", e => {
    _params.dateTo = e.target.value.trim();
    localStorage.setItem("sb_dateTo", _params.dateTo);
    rerenderCurrentView();
  });
  sbRefFrom.addEventListener("change", e => {
    _params.refDateFrom = e.target.value.trim();
    localStorage.setItem("sb_refDateFrom", _params.refDateFrom);
    rerenderCurrentView();
  });
  sbRefTo.addEventListener("change", e => {
    _params.refDateTo = e.target.value.trim();
    localStorage.setItem("sb_refDateTo", _params.refDateTo);
    rerenderCurrentView();
  });

  // Show-faces checkbox for photos view
  const sbShowFaces = document.getElementById("sb-show-faces");
  sbShowFaces.checked = _params.showFaces;
  sbShowFaces.addEventListener("change", e => {
    _params.showFaces = e.target.checked;
    localStorage.setItem("sb_showFaces", _params.showFaces);
    // Toggle overlays without re-fetching
    if (_params.showFaces) {
      if (_injectBboxOverlays) _injectBboxOverlays();
    } else {
      document.getElementById("photo-wrap")
        ?.querySelectorAll(".bbox-overlay").forEach(el => el.remove());
    }
  });

  // Labels and sort for photos view
  const sbLabels = document.getElementById("sb-labels");
  const sbSort   = document.getElementById("sb-sort");
  sbLabels.value = _params.photoLabels;
  sbSort.value   = _params.photoSort;

  sbLabels.addEventListener("change", e => {
    _params.photoLabels = e.target.value.trim();
    localStorage.setItem("sb_photoLabels", _params.photoLabels);
    rerenderCurrentView();
  });
  sbSort.addEventListener("change", e => {
    _params.photoSort = e.target.value;
    localStorage.setItem("sb_photoSort", _params.photoSort);
    rerenderCurrentView();
  });

  // Fetch DB date coverage hint
  apiFetch("/api/photos/date_coverage").then(d => {
    const hint = document.getElementById("sb-date-coverage");
    if (d.min_year && d.max_year)
      hint.textContent = `DB: ${d.min_year} – ${d.max_year}`;
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
function route() {
  // Teardown current view
  if (_cleanup) { _cleanup(); _cleanup = null; }

  const hash = location.hash || "#/unlabeled";
  const parts = hash.replace(/^#\//, "").split("/");

  // Update active nav link
  document.querySelectorAll("[data-nav]").forEach(el => {
    el.classList.toggle("active", parts[0] === el.dataset.nav);
  });

  switch (parts[0]) {
    case "unlabeled":
      _currentView = "unlabeled";
      _currentViewArgs = { page: parts[1] === "page" ? parseInt(parts[2], 10) || 1 : 1 };
      setSidebarView("unlabeled");
      renderUnlabeled(_currentViewArgs.page);
      break;
    case "classify":
      _currentView = "classify";
      _currentViewArgs = {};
      setSidebarView("classify");
      renderClassify();
      break;
    case "photos":
      _currentView = "photos";
      setSidebarView("photos");
      if (parts[1] && parts[1] !== "page") {
        renderPhotos(parts[1]);   // md5 specified
      } else {
        renderPhotos();           // auto-select from state or first
      }
      break;
    case "people":
      if (parts[1] && parts[2] === "faces") {
        const pg = parts[3] === "page" ? parseInt(parts[4], 10) || 1 : 1;
        _currentView = "personFaces"; _currentViewArgs = { name: decodeURIComponent(parts[1]), page: pg };
        setSidebarView("personFaces");
        renderPersonFaces(_currentViewArgs.name, pg);
      } else if (parts[1] && parts[2] === "page") {
        _currentView = "personDetail"; _currentViewArgs = { name: decodeURIComponent(parts[1]), page: parseInt(parts[3], 10) || 1 };
        setSidebarView("personDetail");
        renderPersonDetail(_currentViewArgs.name, _currentViewArgs.page);
      } else if (parts[1]) {
        _currentView = "personDetail"; _currentViewArgs = { name: decodeURIComponent(parts[1]), page: 1 };
        setSidebarView("personDetail");
        renderPersonDetail(_currentViewArgs.name, 1);
      } else {
        _currentView = null; _currentViewArgs = {};   // people list — not date-filtered
        setSidebarView("people");
        renderPeople();
      }
      break;
    case "similar":
      _currentView = "similar";
      _currentViewArgs = { md5: parts[1], bboxParam: parts[2], unlabeledOnly: true };
      setSidebarView("similar");
      renderSimilar(parts[1], parts[2]);
      break;
    default:
      _currentView = "unlabeled";
      _currentViewArgs = { page: 1 };
      setSidebarView("unlabeled");
      renderUnlabeled(1);
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => { initSidebar(); route(); });

// ---------------------------------------------------------------------------
// View: Unlabeled faces
// ---------------------------------------------------------------------------
async function renderUnlabeled(page = 1) {
  showSpinner();
  let data;
  try {
    data = await apiFetch(appendQs(`/api/faces/unlabeled?page=${page}&page_size=100&rel_size_min=${_params.relSizeMin}`, dateQs()));
  } catch (e) { showError(e.message); return; }

  const app = document.getElementById("app");
  const totalPages = Math.ceil(data.total / 100);

  let html = `<h2>Unlabeled faces <span class="badge">${data.total}</span></h2>`;

  if (data.faces.length === 0) {
    html += `<p>No unlabeled faces.</p>`;
    app.innerHTML = html;
    return;
  }

  html += `<div class="face-grid">`;
  data.faces.forEach(f => {
    html += `
      <div class="face-cell">
        <img src="${f.img_url}" loading="lazy" title="${f.md5} (rel_size ${f.rel_size ?? "?"})">
        <a href="#/photos/${f.md5}" target="_blank" class="face-link-btn" title="Open photo">↗</a>
        <a href="#/similar/${f.md5}/${bboxToPathParam(f.bbox)}" class="similar-link-btn" title="Find similar">≈</a>
      </div>`;
  });
  html += `</div>`;

  if (totalPages > 1) {
    html += `<nav class="pagination">`;
    if (page > 1) html += `<a href="#/unlabeled/page/${page - 1}">← Prev</a>`;
    html += `<span>Page ${page} / ${totalPages}</span>`;
    if (page < totalPages) html += `<a href="#/unlabeled/page/${page + 1}">Next →</a>`;
    html += `</nav>`;
  }

  app.innerHTML = html;
}


// ---------------------------------------------------------------------------
// View: Classify
// ---------------------------------------------------------------------------
let _classifyAlgo   = localStorage.getItem("classifyAlgo")   || "centroid";
let _classifyPerson = localStorage.getItem("classifyPerson")  || null;

async function renderClassify(person = null) {
  if (person !== null) { _classifyPerson = person; localStorage.setItem("classifyPerson", person); }
  showSpinner();

  let algorithms;
  try {
    algorithms = await apiFetch("/api/classify/algorithms");
  } catch (e) { showError(e.message); return; }

  // Validate algo — reset to first available if stored value no longer exists
  if (!algorithms.find(a => a.name === _classifyAlgo)) {
    _classifyAlgo = algorithms[0]?.name ?? "min_dist";
    localStorage.setItem("classifyAlgo", _classifyAlgo);
  }

  // Populate sidebar algo select on first classify render
  if (!_algorithms) {
    _algorithms = algorithms;
    const sbAlgo = document.getElementById("sb-algo");
    sbAlgo.innerHTML = algorithms.map(a =>
      `<option value="${a.name}">${escHtml(a.label)}</option>`).join("");
  }
  document.getElementById("sb-algo").value = _classifyAlgo;

  // effectiveThreshold is the Euclidean eps; API expects cosine threshold = 1 - eps²/2
  const threshParam = `&threshold=${1 - _params.threshold * _params.threshold / 2}`;
  const dqs = dateQs(), rqs = refDateQs();
  const baseParams  = appendQs(appendQs(`algo=${encodeURIComponent(_classifyAlgo)}&min_size=3${threshParam}&rel_size_min=${_params.relSizeMin}`, dqs), rqs);

  let peopleList;
  try {
    peopleList = await apiFetch(`/api/classify/people?${baseParams}`);
  } catch (e) { showError(e.message); return; }

  // Validate / default selected person
  if (!_classifyPerson || !peopleList.find(p => p.name === _classifyPerson)) {
    _classifyPerson = peopleList[0]?.name ?? null;
    if (_classifyPerson) localStorage.setItem("classifyPerson", _classifyPerson);
  }

  const sortedPeople = [...peopleList].sort((a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: "base"}));
  const personOptions = sortedPeople.map(p =>
    `<option value="${escHtml(p.name)}"${p.name === _classifyPerson ? " selected" : ""}>${escHtml(p.name)} (${p.face_count})</option>`
  ).join("");

  const app = document.getElementById("app");

  if (!_classifyPerson) {
    app.innerHTML = `
      <h2>Classify</h2>
      <p>No classify candidates found. Run <code>scan</code> first, then label some faces.</p>`;
    return;
  }

  // Fetch candidates for the selected person
  let data;
  try {
    data = await apiFetch(`/api/classify/candidates?person=${encodeURIComponent(_classifyPerson)}&${baseParams}`);
  } catch (e) { showError(e.message); return; }

  const faces   = data.groups[0]?.faces    ?? [];
  const avgDist = data.groups[0]?.avg_dist ?? null;

  // Selection state: selected set (initially empty = none selected)
  const selected = new Set();

  let html = `
    <h2>Classify</h2>
    <div style="display:flex;align-items:center;gap:0.75rem;margin:0 0 0.75rem;">
      <label style="white-space:nowrap;margin:0;">Person:</label>
      <select id="person-select" style="flex:1;margin:0;">${personOptions}</select>
    </div>`;

  if (faces.length === 0) {
    html += `<p>No candidates for <strong>${escHtml(_classifyPerson)}</strong>.</p>`;
  } else {
    html += `<div style="display:flex;align-items:center;gap:0.75rem;margin:0.5rem 0;">
      <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;margin:0;">
        <input type="checkbox" id="select-all-classify"> Select all
      </label>`;
    if (avgDist !== null)
      html += `<span class="dist-tag">avg dist: ${avgDist.toFixed(3)}</span>`;
    html += `<span class="dist-tag">${faces.length} candidate${faces.length !== 1 ? "s" : ""}</span>
    </div>`;
    html += `<div class="face-grid" id="classify-grid">`;
    faces.forEach((f, fi) => {
      html += `
        <div class="face-cell">
          <img src="${f.img_url}" data-face="${fi}"
               class="deselected" title="${escHtml(f.photo_path)} (dist ${f.dist.toFixed(3)})"
               loading="lazy">
          <a href="#/photos/${f.md5}" target="_blank" class="face-link-btn" title="Open photo">↗</a>
          <a href="#/similar/${f.md5}/${bboxToPathParam(f.bbox)}" class="similar-link-btn" title="Find similar">≈</a>
        </div>`;
    });
    html += `</div>`;
  }

  html += `
    <div class="action-row">
      <input type="text" id="label-input" value="${escHtml(_classifyPerson)}"
             placeholder="Label to assign" style="flex:1;min-width:150px;margin:0;">
      <button id="submit-labels">Submit selected</button>
      <button id="mark-nonface" class="secondary outline">Not a face</button>
      <button id="mark-foreign"  class="secondary outline">Foreign</button>
    </div>`;
  app.innerHTML = html;

  // Person selector
  document.getElementById("person-select").addEventListener("change", e => {
    renderClassify(e.target.value);
  });

  function _updateSelectAllCheckbox() {
    const cb = document.getElementById("select-all-classify");
    if (!cb) return;
    if (selected.size === 0)             { cb.checked = false; cb.indeterminate = false; }
    else if (selected.size === faces.length) { cb.checked = true;  cb.indeterminate = false; }
    else                                 { cb.checked = false; cb.indeterminate = true;  }
  }

  // Select-all checkbox
  const cbAll = document.getElementById("select-all-classify");
  if (cbAll) {
    cbAll.addEventListener("change", e => {
      const imgs = app.querySelectorAll(".face-grid img");
      if (e.target.checked) {
        faces.forEach(f => selected.add(`${f.md5}:${bboxToQuery(f.bbox)}`));
        imgs.forEach(img => { img.className = "selected"; });
      } else {
        selected.clear();
        imgs.forEach(img => { img.className = "deselected"; });
      }
    });
  }

  // Face thumbnail click → toggle selection
  app.querySelectorAll(".face-grid img").forEach(img => {
    img.addEventListener("click", () => {
      const fi  = parseInt(img.dataset.face, 10);
      const key = `${faces[fi].md5}:${bboxToQuery(faces[fi].bbox)}`;
      if (selected.has(key)) { selected.delete(key); img.className = "deselected"; }
      else                   { selected.add(key);    img.className = "selected"; }
      _updateSelectAllCheckbox();
    });
  });

  // Submit helper — labels all selected faces with the given name
  async function submitWith(name) {
    const items = faces
      .filter(f => selected.has(`${f.md5}:${bboxToQuery(f.bbox)}`))
      .map(f => ({ md5: f.md5, bbox: f.bbox, name }));
    if (items.length === 0) { alert("No faces selected."); return; }
    const btn   = document.getElementById("submit-labels");
    const btnNF = document.getElementById("mark-nonface");
    const btnFR = document.getElementById("mark-foreign");
    btn.disabled = btnNF.disabled = btnFR.disabled = true;
    btn.textContent = "Submitting…";
    try {
      const resp = await apiPost("/api/classify/labels", items);
      btn.textContent = `Done — ${resp.labeled} labeled`;
      setTimeout(() => renderClassify(), 1500);
    } catch (e) {
      btn.disabled = btnNF.disabled = btnFR.disabled = false;
      btn.textContent = "Submit selected";
      showError(e.message);
    }
  }

  document.getElementById("submit-labels").addEventListener("click", () => {
    const label = document.getElementById("label-input").value.trim();
    if (!label) { alert("Enter a label to assign."); return; }
    submitWith(label);
  });
  document.getElementById("mark-nonface").addEventListener("click", () => submitWith("__nonface__"));
  document.getElementById("mark-foreign" ).addEventListener("click", () => submitWith("__foreign__"));

  // Rect-select
  const grid = document.getElementById("classify-grid");
  if (grid) {
    _cleanup = attachRectSelect(grid, (imgs, mode) => {
      imgs.forEach(img => {
        const fi  = parseInt(img.dataset.face, 10);
        if (isNaN(fi)) return;
        const key = `${faces[fi].md5}:${bboxToQuery(faces[fi].bbox)}`;
        if (mode === "deselect") {
          selected.delete(key); img.className = "deselected";
        } else if (mode === "invert") {
          if (selected.has(key)) { selected.delete(key); img.className = "deselected"; }
          else                   { selected.add(key);    img.className = "selected"; }
        } else {
          selected.add(key); img.className = "selected";
        }
      });
      _updateSelectAllCheckbox();
    });
  }
}


// ---------------------------------------------------------------------------
// View: Photos (gallery)
// ---------------------------------------------------------------------------
async function renderPhotos(currentMd5 = null) {
  if (currentMd5) {
    // Navigated here from a face ↗ link — auto-show faces
    _params.showFaces = true;
    localStorage.setItem("sb_showFaces", "true");
    document.getElementById("sb-show-faces").checked = true;
  }
  showSpinner();
  _galleryCleanupListeners();
  let data;
  try {
    data = await apiFetch(`/api/photos?page=1&page_size=100000&${_photosFilterQs()}`);
  } catch (e) { showError(e.message); return; }

  _photosList = data.photos;

  if (_photosList.length === 0) {
    document.getElementById("app").innerHTML = `<h2>Photos</h2><p>No photos match the current filter.</p>`;
    return;
  }

  let idx = 0;
  if (currentMd5) {
    let found = _photosList.findIndex(p => p.md5 === currentMd5);
    if (found < 0 && _params.photoLabels) {
      // Target photo doesn't pass label filter — clear it and refetch
      _params.photoLabels = "";
      localStorage.setItem("sb_photoLabels", "");
      document.getElementById("sb-labels").value = "";
      try {
        data = await apiFetch(`/api/photos?page=1&page_size=100000&${_photosFilterQs()}`);
      } catch (e) { showError(e.message); return; }
      _photosList = data.photos;
      found = _photosList.findIndex(p => p.md5 === currentMd5);
    }
    idx = found >= 0 ? found : _findFallbackIdx(_photosList);
  } else if (_currentViewArgs.currentMd5) {
    const found = _photosList.findIndex(p => p.md5 === _currentViewArgs.currentMd5);
    idx = found >= 0 ? found : _findFallbackIdx(_photosList);
  }

  await _loadPhotoAtIdx(idx);
}

async function _loadPhotoAtIdx(idx) {
  if (idx < 0) idx = 0;
  if (idx >= _photosList.length) idx = _photosList.length - 1;
  const photo = _photosList[idx];
  _currentViewArgs.currentMd5      = photo.md5;
  _currentViewArgs.currentExifDate = photo.exif_date;
  _currentViewArgs.currentPath     = photo.path;
  _currentViewArgs.currentIdx      = idx;
  history.replaceState(null, "", `#/photos/${photo.md5}`);
  let detail;
  try {
    detail = await apiFetch(`/api/photos/${photo.md5}`);
  } catch (e) { showError(e.message); return; }
  _renderPhotosGallery(idx, detail);
}

function _renderPhotosGallery(currentIdx, detail) {
  _galleryCleanupListeners();
  const n = _photosList.length;
  const thumbPage      = Math.floor(currentIdx / THUMB_PAGE_SIZE);
  const thumbStart     = thumbPage * THUMB_PAGE_SIZE;
  const thumbEnd       = Math.min(thumbStart + THUMB_PAGE_SIZE, n);
  const totalThumbPages = Math.ceil(n / THUMB_PAGE_SIZE);

  const uniqueLabels = [...new Set(
    detail.faces
      .map(f => f.sticky_name)
      .filter(n => n && !["__nonface__", "__foreign__"].includes(n))
  )];
  const labelsStr = uniqueLabels.join(", ");

  let html = `<h2>Photos <span class="badge">${n}</span></h2>
  <div class="gallery-main">
    <button class="photo-nav-btn" id="gallery-prev"${currentIdx === 0 ? " disabled" : ""}>←</button>
    <div class="gallery-photo-col">
      <div class="photo-overlay-wrap" id="photo-wrap">
        <img id="main-photo" class="main-photo" src="${detail.photo_url}" alt="${escHtml(detail.path)}">
      </div>
      <p class="gallery-info">${escHtml(detail.path)} · ${formatDate(detail.exif_date)} · ${currentIdx + 1}/${n}${labelsStr ? " · " + escHtml(labelsStr) : ""}</p>
    </div>
    <button class="photo-nav-btn" id="gallery-next"${currentIdx === n - 1 ? " disabled" : ""}>→</button>
  </div>`;

  html += `<div class="gallery-thumbs" id="gallery-thumbs">`;
  for (let i = thumbStart; i < thumbEnd; i++) {
    const p = _photosList[i];
    html += `<img src="${p.photo_url}" class="gallery-thumb${i === currentIdx ? " active" : ""}"
      data-idx="${i}" loading="lazy" title="${escHtml(p.path)}" width="80" height="60">`;
  }
  html += `</div>`;

  if (totalThumbPages > 1) {
    html += `<nav class="pagination" style="margin-top:0.5rem;">`;
    if (thumbPage > 0)
      html += `<button class="secondary outline" id="thumb-prev-page">← Prev</button>`;
    html += `<span>Page ${thumbPage + 1} / ${totalThumbPages}</span>`;
    if (thumbPage < totalThumbPages - 1)
      html += `<button class="secondary outline" id="thumb-next-page">Next →</button>`;
    html += `</nav>`;
  }

  if (detail.faces.length > 0) {
    html += `<h3 style="margin-top:1.5rem;">Faces</h3><div class="face-grid">`;
    detail.faces.forEach(f => {
      html += `<div class="face-cell">
        <img src="${f.img_url}" loading="lazy" title="${escHtml(f.sticky_name || "")}">
        <a href="#/similar/${f.md5}/${bboxToPathParam(f.bbox)}" class="similar-link-btn" title="Find similar faces">≈</a>
      </div>`;
    });
    html += `</div>`;
  }

  document.getElementById("app").innerHTML = html;

  // Bbox overlays
  const imgEl  = document.getElementById("main-photo");
  const wrapEl = document.getElementById("photo-wrap");

  _injectBboxOverlays = function injectBboxOverlays() {
    wrapEl.querySelectorAll(".bbox-overlay").forEach(el => el.remove());
    const nw = imgEl.naturalWidth, nh = imgEl.naturalHeight;
    if (!nw || !nh) return;
    const sx = imgEl.clientWidth / nw, sy = imgEl.clientHeight / nh;
    detail.faces.forEach(face => {
      const [x1, y1, x2, y2] = transformBboxForDisplay(face.bbox, detail.exif_orientation, nw, nh);
      const div = document.createElement("div");
      div.className = "bbox-overlay";
      div.style.left   = x1 * sx + "px";
      div.style.top    = y1 * sy + "px";
      div.style.width  = (x2 - x1) * sx + "px";
      div.style.height = (y2 - y1) * sy + "px";
      if (face.sticky_name && !["__nonface__", "__foreign__"].includes(face.sticky_name)) {
        const lbl = document.createElement("div");
        lbl.className = "bbox-label";
        lbl.textContent = face.sticky_name;
        div.appendChild(lbl);
      }
      wrapEl.appendChild(div);
    });
  }

  if (_params.showFaces) {
    imgEl.addEventListener("load", _injectBboxOverlays);
    if (imgEl.complete && imgEl.naturalWidth) _injectBboxOverlays();
  }

  // Nav buttons
  document.getElementById("gallery-prev")?.addEventListener("click", () => {
    if (currentIdx > 0) _loadPhotoAtIdx(currentIdx - 1);
  });
  document.getElementById("gallery-next")?.addEventListener("click", () => {
    if (currentIdx < n - 1) _loadPhotoAtIdx(currentIdx + 1);
  });

  // Thumbnail clicks
  document.getElementById("gallery-thumbs").querySelectorAll(".gallery-thumb").forEach(img => {
    img.addEventListener("click", () => _loadPhotoAtIdx(parseInt(img.dataset.idx, 10)));
  });

  // Thumb page nav
  document.getElementById("thumb-prev-page")?.addEventListener("click", () => {
    _loadPhotoAtIdx((thumbPage - 1) * THUMB_PAGE_SIZE);
  });
  document.getElementById("thumb-next-page")?.addEventListener("click", () => {
    _loadPhotoAtIdx((thumbPage + 1) * THUMB_PAGE_SIZE);
  });

  // Keyboard nav
  _galleryKeyHandler = e => {
    if (document.activeElement && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if (e.key === "ArrowLeft"  && currentIdx > 0)     _loadPhotoAtIdx(currentIdx - 1);
    if (e.key === "ArrowRight" && currentIdx < n - 1) _loadPhotoAtIdx(currentIdx + 1);
  };
  document.addEventListener("keydown", _galleryKeyHandler);

  // Resize handler
  _galleryResizeHandler = () => {
    if (!_params.showFaces) return;
    clearTimeout(_galleryResizeTimer);
    _galleryResizeTimer = setTimeout(_injectBboxOverlays, 100);
  };
  window.addEventListener("resize", _galleryResizeHandler);

  _cleanup = _galleryCleanupListeners;
}

// ---------------------------------------------------------------------------
// View: People
// ---------------------------------------------------------------------------
async function renderPeople() {
  showSpinner();
  let data;
  try {
    data = await apiFetch("/api/people");
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  if (!data.length) {
    app.innerHTML = `<h2>People</h2><p>No labeled people yet. Use <a href="#/classify">Classify</a> to add labels.</p>`;
    return;
  }

  let html = `<h2>People <span class="badge">${data.length}</span></h2><ul class="people-list">`;
  data.forEach(p => {
    html += `
      <li>
        <a href="#/people/${encodeURIComponent(p.name)}">${escHtml(p.name)}</a>
        <span class="person-meta"> — ${p.face_count} face${p.face_count !== 1 ? "s" : ""}, ${p.photo_count} photo${p.photo_count !== 1 ? "s" : ""}</span>
        <a href="#/people/${encodeURIComponent(p.name)}/faces" class="manage-link">manage</a>
      </li>`;
  });
  html += `</ul>`;
  app.innerHTML = html;
}

// ---------------------------------------------------------------------------
// View: Person Detail
// ---------------------------------------------------------------------------
async function renderPersonDetail(name, page = 1) {
  showSpinner();
  let data;
  try {
    data = await apiFetch(appendQs(`/api/people/${encodeURIComponent(name)}?page=${page}&page_size=50`, dateQs()));
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  const totalPages = Math.ceil(data.total / data.page_size);
  const base = `#/people/${encodeURIComponent(name)}`;

  function pageNav() {
    if (totalPages <= 1) return "";
    let nav = `<nav class="pagination">`;
    if (page > 1) nav += `<a href="${base}/page/${page - 1}">← Prev</a>`;
    nav += `<span>Page ${page} / ${totalPages}</span>`;
    if (page < totalPages) nav += `<a href="${base}/page/${page + 1}">Next →</a>`;
    nav += `</nav>`;
    return nav;
  }

  let html = `
    <p class="breadcrumb"><a href="#/people">← People</a></p>
    <h2>${escHtml(data.name)} <span class="badge">${data.total} photo${data.total !== 1 ? "s" : ""}</span></h2>
    ${pageNav()}
    <ul class="photo-list">`;
  data.photos.forEach(p => {
    html += `
      <li class="photo-list-item" data-md5="${p.md5}">
        <img src="${p.photo_url}" loading="lazy" alt="" width="80" height="60">
        <div class="photo-meta">
          <div class="photo-path">${escHtml(p.path)}</div>
          <div class="photo-info">${formatDate(p.exif_date)}</div>
        </div>
      </li>`;
  });
  html += `</ul>${pageNav()}`;
  app.innerHTML = html;

  app.querySelectorAll(".photo-list-item").forEach(li => {
    li.addEventListener("click", () => { location.hash = `#/photos/${li.dataset.md5}`; });
  });
}

// ---------------------------------------------------------------------------
// View: Person Faces (label management)
// ---------------------------------------------------------------------------
const PERSON_FACES_PAGE_SIZE = 200;

async function renderPersonFaces(name, page = 1) {
  showSpinner();
  let data, people;
  try {
    [data, people] = await Promise.all([
      apiFetch(appendQs(`/api/people/${encodeURIComponent(name)}/faces?page=${page}&page_size=${PERSON_FACES_PAGE_SIZE}`, dateQs())),
      apiFetch("/api/people"),
    ]);
  } catch (e) {
    showError(e.message);
    return;
  }
  const knownNames = people.map(p => p.name).filter(n => !SPECIAL_LABELS.includes(n));

  const selected = new Set(data.faces.map(f => `${f.md5}:${bboxToQuery(f.bbox)}`));
  const totalPages = Math.ceil(data.total / PERSON_FACES_PAGE_SIZE);
  const app = document.getElementById("app");

  function pageNav() {
    if (totalPages <= 1) return "";
    const base = `#/people/${encodeURIComponent(name)}/faces`;
    let nav = `<nav class="pagination">`;
    if (page > 1) nav += `<a href="${base}/page/${page - 1}">← Prev</a>`;
    nav += `<span>Page ${page} / ${totalPages}</span>`;
    if (page < totalPages) nav += `<a href="${base}/page/${page + 1}">Next →</a>`;
    nav += `</nav>`;
    return nav;
  }

  let html = `
    <p class="breadcrumb"><a href="#/people">← People</a></p>
    <h2>${escHtml(name)} <span class="badge">${data.total} faces</span></h2>
    <div style="display:flex;align-items:center;gap:0.75rem;margin:0.5rem 0;">
      <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;margin:0;">
        <input type="checkbox" id="select-all-pf" checked> Select all
      </label>
    </div>
    ${pageNav()}
    <div class="face-grid">
      ${data.faces.map((f, fi) => `
        <div class="face-cell">
          <img src="${f.img_url}" data-fi="${fi}" class="selected" loading="lazy"
               title="${escHtml(f.photo_path)}">
          <a href="#/photos/${f.md5}" target="_blank" class="face-link-btn" title="Open photo">↗</a>
          <a href="#/similar/${f.md5}/${bboxToPathParam(f.bbox)}" class="similar-link-btn" title="Find similar">≈</a>
        </div>
      `).join("")}
    </div>
    ${pageNav()}
    <div class="action-row">
      <button id="pf-clear">Clear label</button>
      <button id="pf-nonface" class="secondary outline">Not a face</button>
      <button id="pf-foreign"  class="secondary outline">Foreign</button>
    </div>
    <div style="margin-top:1.5rem;border-top:1px solid var(--pico-muted-border-color);padding-top:1rem;">
      <h3 style="margin-top:0;">Rename person</h3>
      <div class="action-row">
        <input type="text" id="pf-rename-input" list="pf-rename-datalist"
               placeholder="New name — empty to remove label"
               style="flex:1;min-width:200px;margin:0;">
        <datalist id="pf-rename-datalist">
          ${knownNames.filter(n => n !== name).map(n => `<option value="${escHtml(n)}">`).join("")}
        </datalist>
        <button id="pf-rename-btn">Rename</button>
        <span id="pf-rename-status" style="font-size:0.85rem;color:var(--pico-muted-color);"></span>
      </div>
    </div>`;

  app.innerHTML = html;

  function _updateSelectAll() {
    const cb = document.getElementById("select-all-pf");
    if (!cb) return;
    if (selected.size === 0) { cb.checked = false; cb.indeterminate = false; }
    else if (selected.size === data.faces.length) { cb.checked = true; cb.indeterminate = false; }
    else { cb.checked = false; cb.indeterminate = true; }
  }

  document.getElementById("select-all-pf").addEventListener("change", e => {
    const imgs = app.querySelectorAll(".face-grid img");
    if (e.target.checked) {
      data.faces.forEach(f => selected.add(`${f.md5}:${bboxToQuery(f.bbox)}`));
      imgs.forEach(img => { img.className = "selected"; });
    } else {
      selected.clear();
      imgs.forEach(img => { img.className = "deselected"; });
    }
  });

  app.querySelectorAll(".face-grid img").forEach(img => {
    img.addEventListener("click", () => {
      const fi = parseInt(img.dataset.fi, 10);
      const f = data.faces[fi];
      const key = `${f.md5}:${bboxToQuery(f.bbox)}`;
      if (selected.has(key)) {
        selected.delete(key);
        img.className = "deselected";
      } else {
        selected.add(key);
        img.className = "selected";
      }
      _updateSelectAll();
    });
  });

  async function applyLabel(labelName) {
    const items = data.faces
      .filter(f => selected.has(`${f.md5}:${bboxToQuery(f.bbox)}`))
      .map(f => ({ md5: f.md5, bbox: f.bbox, name: labelName }));
    if (items.length === 0) { alert("Select at least one face first."); return; }
    ["pf-clear", "pf-nonface", "pf-foreign"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = true;
    });
    try {
      await apiPost("/api/classify/labels", items);
      setTimeout(() => renderPersonFaces(name, page), 1500);
    } catch (e) {
      ["pf-clear", "pf-nonface", "pf-foreign"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = false;
      });
      showError(e.message);
    }
  }

  document.getElementById("pf-clear"  ).addEventListener("click", () => applyLabel(null));
  document.getElementById("pf-nonface").addEventListener("click", () => applyLabel("__nonface__"));
  document.getElementById("pf-foreign" ).addEventListener("click", () => applyLabel("__foreign__"));

  _cleanup = attachRectSelect(app.querySelector(".face-grid"), (imgs, mode) => {
    imgs.forEach(img => {
      const fi = parseInt(img.dataset.fi, 10);
      if (isNaN(fi)) return;
      const f = data.faces[fi];
      const key = `${f.md5}:${bboxToQuery(f.bbox)}`;
      if (mode === "deselect") {
        selected.delete(key); img.className = "deselected";
      } else if (mode === "invert") {
        if (selected.has(key)) { selected.delete(key); img.className = "deselected"; }
        else                   { selected.add(key);    img.className = "selected"; }
      } else {
        selected.add(key); img.className = "selected";
      }
    });
    _updateSelectAll();
  });

  document.getElementById("pf-rename-btn").addEventListener("click", async () => {
    const newName = document.getElementById("pf-rename-input").value.trim() || null;
    const status = document.getElementById("pf-rename-status");

    if (newName === name) return;

    if (!newName) {
      if (!confirm(`Remove label "${name}" from all ${data.total} face(s)? They will become unlabeled.`)) return;
    } else if (knownNames.includes(newName)) {
      const target = people.find(p => p.name === newName);
      const targetCount = target ? target.face_count : "?";
      if (!confirm(`"${newName}" already exists (${targetCount} face(s)). Merge "${name}" into "${newName}"?`)) return;
    }

    const btn = document.getElementById("pf-rename-btn");
    btn.disabled = true;
    status.textContent = "Renaming…";
    try {
      const resp = await apiPatch(`/api/people/${encodeURIComponent(name)}`, { new_name: newName });
      if (newName) {
        location.hash = `#/people/${encodeURIComponent(newName)}/faces`;
      } else {
        location.hash = `#/people`;
      }
    } catch (e) {
      btn.disabled = false;
      status.textContent = `Error: ${e.message}`;
    }
  });
}

// ---------------------------------------------------------------------------
// View: Similar faces
// ---------------------------------------------------------------------------
async function renderSimilar(md5, bboxParam, unlabeledOnly = true) {
  _currentViewArgs = { md5, bboxParam, unlabeledOnly };
  showSpinner();
  const bboxQuery = bboxParam.replace(/_/g, ",");
  let data, people;
  try {
    [data, people] = await Promise.all([
      apiFetch(appendQs(`/api/faces/similar?md5=${md5}&bbox=${bboxQuery}&limit=100&unlabeled_only=${unlabeledOnly}`, dateQs())),
      apiFetch("/api/people"),
    ]);
  } catch (e) {
    showError(e.message);
    return;
  }

  const knownNames = people
    .map(p => p.name)
    .filter(n => !SPECIAL_LABELS.includes(n))
    .sort((a, b) => a.localeCompare(b));

  const allFaces = data.faces;
  const effectiveMaxDist = _params.threshold;
  const relSizeMin = _params.relSizeMin;
  const visibleFaces = allFaces.filter(f => f.dist <= effectiveMaxDist && f.rel_size >= relSizeMin);

  const selected = new Set();
  const app = document.getElementById("app");

  const seedName = data.seed.name
    ? `<span class="dist-tag">Labeled: ${escHtml(data.seed.name)}</span>`
    : `<span class="dist-tag">Unlabeled</span>`;

  let html = `
    <p class="breadcrumb"><a href="#" onclick="history.back();return false;">← Back</a></p>
    <h2>Similar faces</h2>
    <div class="similar-seed">
      <img src="${data.seed.img_url}" class="seed-thumb" alt="">
      <div>
        <div>${escHtml(data.seed.photo_path)} <a href="#/photos/${data.seed.md5}" title="Open photo">↗</a></div>
        ${seedName}
        <label style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem;cursor:pointer;">
          <input type="checkbox" id="unlabeled-only"${unlabeledOnly ? " checked" : ""}> Unlabeled only
        </label>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:0.75rem;margin:0.5rem 0;">
      <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;margin:0;">
        <input type="checkbox" id="select-all-similar"> Select all
      </label>
      <span class="dist-tag">${visibleFaces.length} result${visibleFaces.length !== 1 ? "s" : ""}</span>
    </div>
    <div class="face-grid">
      ${visibleFaces.map((f, fi) => `
        <div class="face-cell">
          <img src="${f.img_url}" data-fi="${fi}" class="deselected" loading="lazy"
               title="${escHtml(f.photo_path)}${f.name ? " · " + escHtml(f.name) : ""} (dist ${f.dist.toFixed(3)})">
          <a href="#/photos/${f.md5}" target="_blank" class="face-link-btn" title="Open photo">↗</a>
          <a href="#/similar/${f.md5}/${bboxToPathParam(f.bbox)}" class="similar-link-btn" title="Find similar faces">≈</a>
        </div>
      `).join("")}
    </div>
    <div class="similar-label-row">
      <input type="text" id="similar-label" list="similar-people-datalist"
             placeholder="Label — empty to clear"
             value="${data.seed.name ? escHtml(data.seed.name) : ""}">
      <datalist id="similar-people-datalist">
        ${knownNames.map(n => `<option value="${escHtml(n)}">`).join("")}
      </datalist>
      <button id="similar-submit">Apply to selected</button>
      <button id="mark-nonface" class="secondary outline">Not a face</button>
      <button id="mark-foreign"  class="secondary outline">Foreign</button>
    </div>`;

  app.innerHTML = html;

  function _updateSelectAllCheckbox() {
    const cb = document.getElementById("select-all-similar");
    if (!cb) return;
    if (selected.size === 0) {
      cb.checked = false;
      cb.indeterminate = false;
    } else if (selected.size === visibleFaces.length) {
      cb.checked = true;
      cb.indeterminate = false;
    } else {
      cb.checked = false;
      cb.indeterminate = true;
    }
  }

  document.getElementById("select-all-similar").addEventListener("change", e => {
    const imgs = app.querySelectorAll(".face-grid img");
    if (e.target.checked) {
      visibleFaces.forEach(f => selected.add(`${f.md5}:${bboxToQuery(f.bbox)}`));
      imgs.forEach(img => { img.className = "selected"; });
    } else {
      selected.clear();
      imgs.forEach(img => { img.className = "deselected"; });
    }
  });

  document.getElementById("unlabeled-only").addEventListener("change", e => {
    _currentViewArgs.unlabeledOnly = e.target.checked;
    renderSimilar(md5, bboxParam, e.target.checked);
  });

  app.querySelectorAll(".face-grid img").forEach(img => {
    img.addEventListener("click", () => {
      const fi = parseInt(img.dataset.fi, 10);
      const f = visibleFaces[fi];
      const key = `${f.md5}:${bboxToQuery(f.bbox)}`;
      if (selected.has(key)) {
        selected.delete(key);
        img.className = "deselected";
      } else {
        selected.add(key);
        img.className = "selected";
      }
      _updateSelectAllCheckbox();
    });
  });

  document.getElementById("similar-submit").addEventListener("click", async () => {
    const label = document.getElementById("similar-label").value.trim() || null;
    const items = visibleFaces
      .filter(f => selected.has(`${f.md5}:${bboxToQuery(f.bbox)}`))
      .map(f => ({ md5: f.md5, bbox: f.bbox, name: label }));

    if (data.seed.name !== label) {
      const seedBbox = bboxParam.split("_").map(Number);
      items.push({ md5: data.seed.md5, bbox: seedBbox, name: label });
    }

    if (items.length === 0) {
      alert("Select at least one face first.");
      return;
    }

    const btn = document.getElementById("similar-submit");
    btn.disabled = true;
    btn.textContent = "Applying…";
    try {
      const resp = await apiPost("/api/classify/labels", items);
      btn.textContent = `Done — ${resp.labeled} labeled`;
      if (label && !SPECIAL_LABELS.includes(label)) {
        _classifyPerson = label;
        localStorage.setItem("classifyPerson", label);
      }
      setTimeout(() => renderSimilar(md5, bboxParam, unlabeledOnly), 1500);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Apply to selected";
      showError(e.message);
    }
  });

  // Special-label buttons (similar view)
  async function applySpecialLabelSimilar(name) {
    const items = visibleFaces
      .filter(f => selected.has(`${f.md5}:${bboxToQuery(f.bbox)}`))
      .map(f => ({ md5: f.md5, bbox: f.bbox, name }));
    if (data.seed.name !== name) {
      const seedBbox = bboxParam.split("_").map(Number);
      items.push({ md5: data.seed.md5, bbox: seedBbox, name });
    }

    if (items.length === 0) { alert("Select at least one face first."); return; }
    const btnNF = document.getElementById("mark-nonface");
    const btnFR = document.getElementById("mark-foreign");
    btnNF.disabled = true;
    btnFR.disabled = true;
    try {
      await apiPost("/api/classify/labels", items);
      setTimeout(() => renderSimilar(md5, bboxParam, unlabeledOnly), 1500);
    } catch (e) {
      btnNF.disabled = false;
      btnFR.disabled = false;
      showError(e.message);
    }
  }
  document.getElementById("mark-nonface").addEventListener("click", () => applySpecialLabelSimilar("__nonface__"));
  document.getElementById("mark-foreign" ).addEventListener("click", () => applySpecialLabelSimilar("__foreign__"));

  _cleanup = attachRectSelect(app.querySelector(".face-grid"), (imgs, mode) => {
    imgs.forEach(img => {
      const fi = parseInt(img.dataset.fi, 10);
      if (isNaN(fi)) return;
      const f = visibleFaces[fi];
      const key = `${f.md5}:${bboxToQuery(f.bbox)}`;
      if (mode === "deselect") {
        selected.delete(key); img.className = "deselected";
      } else if (mode === "invert") {
        if (selected.has(key)) { selected.delete(key); img.className = "deselected"; }
        else                   { selected.add(key);    img.className = "selected"; }
      } else {
        selected.add(key); img.className = "selected";
      }
    });
    _updateSelectAllCheckbox();
  });
}

// ---------------------------------------------------------------------------
// EXIF bbox transform
// ---------------------------------------------------------------------------
// Browsers report naturalWidth/naturalHeight in display (EXIF-corrected) space.
// Our bboxes are stored in raw pixel space. Map them before placing overlays.
// nw/nh are imgEl.naturalWidth/naturalHeight (display dimensions).
function transformBboxForDisplay(bbox, orientation, nw, nh) {
  const [x1, y1, x2, y2] = bbox;
  switch (orientation) {
    case 2: return [nw - x2, y1,      nw - x1, y2     ];
    case 3: return [nw - x2, nh - y2, nw - x1, nh - y1];
    case 4: return [x1,      nh - y2, x2,      nh - y1];
    case 5: return [y1, x1, y2, x2];
    case 6: return [nw - y2, x1,      nw - y1, x2     ]; // 90° CW
    case 7: return [nw - y2, nh - x2, nw - y1, nh - x1];
    case 8: return [y1,      nh - x2, y2,      nh - x1]; // 90° CCW
    default: return bbox; // orientation 1: no transform
  }
}

// ---------------------------------------------------------------------------
// Escape helper
// ---------------------------------------------------------------------------
function escHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
