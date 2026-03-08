"use strict";

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------
const SPECIAL_LABELS = ["__nonface__", "__foreign__"];
let _cleanup = null;

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
// Router
// ---------------------------------------------------------------------------
function route() {
  // Teardown current view
  if (_cleanup) { _cleanup(); _cleanup = null; }

  const hash = location.hash || "#/classify";
  const parts = hash.replace(/^#\//, "").split("/");

  // Update active nav link
  document.querySelectorAll("[data-nav]").forEach(el => {
    el.classList.toggle("active", parts[0] === el.dataset.nav);
  });

  switch (parts[0]) {
    case "classify":
      renderClassify();
      break;
    case "photos":
      if (parts[1] === "page") renderPhotos(parseInt(parts[2], 10) || 1);
      else if (parts[1]) renderPhotoDetail(parts[1]);
      else renderPhotos(1);
      break;
    case "people":
      if (parts[1] && parts[2] === "faces") {
        const pg = parts[3] === "page" ? parseInt(parts[4], 10) || 1 : 1;
        renderPersonFaces(decodeURIComponent(parts[1]), pg);
      } else if (parts[1] && parts[2] === "page") {
        renderPersonDetail(decodeURIComponent(parts[1]), parseInt(parts[3], 10) || 1);
      } else if (parts[1]) {
        renderPersonDetail(decodeURIComponent(parts[1]), 1);
      } else {
        renderPeople();
      }
      break;
    case "similar":
      renderSimilar(parts[1], parts[2]);
      break;
    default:
      renderClassify();
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);

// ---------------------------------------------------------------------------
// View: Classify
// ---------------------------------------------------------------------------
let _classifyAlgo   = localStorage.getItem("classifyAlgo")   || "min_dist";
let _classifyPerson = localStorage.getItem("classifyPerson")  || null;

async function renderClassify(threshold = null, algo = null, person = null) {
  if (algo   !== null) { _classifyAlgo   = algo;   localStorage.setItem("classifyAlgo",   algo); }
  if (person !== null) { _classifyPerson = person; localStorage.setItem("classifyPerson", person); }
  const currentAlgo = _classifyAlgo;

  showSpinner();

  // effectiveThreshold is the Euclidean eps; API expects cosine threshold = 1 - eps²/2
  const threshParam = threshold !== null ? `&threshold=${1 - threshold * threshold / 2}` : "";
  const baseParams  = `algo=${encodeURIComponent(currentAlgo)}&min_size=3${threshParam}`;

  let peopleList, algorithms;
  try {
    [peopleList, algorithms] = await Promise.all([
      apiFetch(`/api/classify/people?${baseParams}`),
      apiFetch("/api/classify/algorithms"),
    ]);
  } catch (e) { showError(e.message); return; }

  // Validate / default selected person
  if (!_classifyPerson || !peopleList.find(p => p.name === _classifyPerson)) {
    _classifyPerson = peopleList[0]?.name ?? null;
    if (_classifyPerson) localStorage.setItem("classifyPerson", _classifyPerson);
  }

  const algoOptions = algorithms.map(a =>
    `<option value="${a.name}"${a.name === currentAlgo ? " selected" : ""}>${escHtml(a.label)}</option>`
  ).join("");
  const personOptions = peopleList.map(p =>
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

  const effectiveThreshold = threshold !== null ? threshold : data.eps;
  const faces   = data.groups[0]?.faces    ?? [];
  const avgDist = data.groups[0]?.avg_dist ?? null;

  // Selection state: selected set (initially empty = none selected)
  const selected = new Set();

  let html = `
    <h2>Classify</h2>
    <div class="threshold-row">
      <label>Person:</label>
      <select id="person-select">${personOptions}</select>
      <label>Algorithm:</label>
      <select id="algo-select">${algoOptions}</select>
      <label>Threshold: <strong id="thresh-val">${effectiveThreshold.toFixed(2)}</strong></label>
      <input type="range" id="thresh-slider" min="0.1" max="2.0" step="0.01" value="${effectiveThreshold}">
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
    renderClassify(effectiveThreshold, null, e.target.value);
  });

  // Algorithm selector
  document.getElementById("algo-select").addEventListener("change", e => {
    renderClassify(effectiveThreshold, e.target.value);
  });

  // Threshold slider
  let threshTimer;
  document.getElementById("thresh-slider").addEventListener("input", e => {
    document.getElementById("thresh-val").textContent = parseFloat(e.target.value).toFixed(2);
    clearTimeout(threshTimer);
    threshTimer = setTimeout(() => renderClassify(parseFloat(e.target.value)), 400);
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
      setTimeout(() => renderClassify(effectiveThreshold), 1500);
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
// View: Photos (paginated)
// ---------------------------------------------------------------------------
const PAGE_SIZE = 50;

async function renderPhotos(page) {
  showSpinner();
  let data;
  try {
    data = await apiFetch(`/api/photos?page=${page}&page_size=${PAGE_SIZE}`);
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  const totalPages = Math.ceil(data.total / PAGE_SIZE);

  let html = `<h2>Photos <span class="badge">${data.total}</span></h2>`;
  html += `<ul class="photo-list">`;
  data.photos.forEach(p => {
    html += `
      <li class="photo-list-item" data-md5="${p.md5}">
        <img src="${p.photo_url}" loading="lazy" alt="" width="80" height="60">
        <div class="photo-meta">
          <div class="photo-path">${escHtml(p.path)}</div>
          <div class="photo-info">${formatDate(p.exif_date)} · ${p.face_count} face${p.face_count !== 1 ? "s" : ""}</div>
        </div>
      </li>`;
  });
  html += `</ul>`;

  if (totalPages > 1) {
    html += `<nav class="pagination">`;
    if (page > 1) html += `<a href="#/photos/page/${page - 1}">← Prev</a>`;
    html += `<span>Page ${page} / ${totalPages}</span>`;
    if (page < totalPages) html += `<a href="#/photos/page/${page + 1}">Next →</a>`;
    html += `</nav>`;
  }

  app.innerHTML = html;

  app.querySelectorAll(".photo-list-item").forEach(li => {
    li.addEventListener("click", () => { location.hash = `#/photos/${li.dataset.md5}`; });
  });
}

// ---------------------------------------------------------------------------
// View: Photo Detail
// ---------------------------------------------------------------------------
async function renderPhotoDetail(md5) {
  showSpinner();
  let data;
  try {
    data = await apiFetch(`/api/photos/${md5}`);
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  let html = `
    <p class="breadcrumb"><a href="#/photos">← Photos</a></p>
    <h2>${escHtml(data.path)}</h2>
    <p style="font-size:0.85rem;color:var(--pico-muted-color);">${formatDate(data.exif_date)}</p>
    <div class="photo-overlay-wrap" id="photo-wrap">
      <img id="main-photo" class="main-photo" src="${data.photo_url}" alt="${escHtml(data.path)}">
    </div>`;

  if (data.faces.length > 0) {
    html += `<h3 style="margin-top:1.5rem;">Faces</h3><div class="face-grid">`;
    data.faces.forEach(f => {
      html += `
        <div class="face-cell">
          <img src="${f.img_url}" loading="lazy" title="${escHtml(f.sticky_name || "")}">
          <a href="#/similar/${f.md5}/${bboxToPathParam(f.bbox)}" class="similar-link-btn" title="Find similar faces">≈</a>
        </div>`;
    });
    html += `</div>`;
  }

  app.innerHTML = html;

  const imgEl = document.getElementById("main-photo");
  const wrapEl = document.getElementById("photo-wrap");

  function injectBboxOverlays() {
    wrapEl.querySelectorAll(".bbox-overlay").forEach(el => el.remove());
    const nw = imgEl.naturalWidth;
    const nh = imgEl.naturalHeight;
    const sx = imgEl.clientWidth  / nw;
    const sy = imgEl.clientHeight / nh;
    data.faces.forEach(face => {
      const [x1, y1, x2, y2] = transformBboxForDisplay(
        face.bbox, data.exif_orientation, nw, nh
      );
      const div = document.createElement("div");
      div.className = "bbox-overlay";
      div.style.left   = x1 * sx + "px";
      div.style.top    = y1 * sy + "px";
      div.style.width  = (x2 - x1) * sx + "px";
      div.style.height = (y2 - y1) * sy + "px";
      if (face.sticky_name) {
        const lbl = document.createElement("div");
        lbl.className = "bbox-label";
        lbl.textContent = face.sticky_name;
        div.appendChild(lbl);
      }
      wrapEl.appendChild(div);
    });
  }

  imgEl.addEventListener("load", injectBboxOverlays);
  if (imgEl.complete && imgEl.naturalWidth) injectBboxOverlays();

  let resizeTimer = null;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(injectBboxOverlays, 100);
  }
  window.addEventListener("resize", onResize);

  _cleanup = () => {
    window.removeEventListener("resize", onResize);
    clearTimeout(resizeTimer);
  };
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
    data = await apiFetch(`/api/people/${encodeURIComponent(name)}?page=${page}&page_size=50`);
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
      apiFetch(`/api/people/${encodeURIComponent(name)}/faces?page=${page}&page_size=${PERSON_FACES_PAGE_SIZE}`),
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
// ---------------------------------------------------------------------------
// View: Similar faces
// ---------------------------------------------------------------------------
async function renderSimilar(md5, bboxParam, unlabeledOnly = true, maxDist = null) {
  showSpinner();
  const bboxQuery = bboxParam.replace(/_/g, ",");
  let data, people;
  try {
    [data, people] = await Promise.all([
      apiFetch(`/api/faces/similar?md5=${md5}&bbox=${bboxQuery}&limit=100&unlabeled_only=${unlabeledOnly}`),
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
  const maxResultDist = allFaces.length > 0 ? Math.max(...allFaces.map(f => f.dist)) : 1.0;
  const sliderMax = Math.max(maxResultDist * 1.1, 0.5);
  const effectiveMaxDist = maxDist !== null ? maxDist : maxResultDist;
  const visibleFaces = allFaces.filter(f => f.dist <= effectiveMaxDist);

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
    <div class="threshold-row">
      <label>Max dist: <strong id="thresh-val">${effectiveMaxDist.toFixed(2)}</strong></label>
      <input type="range" id="thresh-slider" min="0.0" max="${sliderMax.toFixed(2)}" step="0.01" value="${effectiveMaxDist}">
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

  let threshTimer;
  document.getElementById("thresh-slider").addEventListener("input", e => {
    document.getElementById("thresh-val").textContent = parseFloat(e.target.value).toFixed(2);
    clearTimeout(threshTimer);
    threshTimer = setTimeout(() => renderSimilar(md5, bboxParam, unlabeledOnly, parseFloat(e.target.value)), 300);
  });

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
    renderSimilar(md5, bboxParam, e.target.checked, effectiveMaxDist);
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
      setTimeout(() => renderSimilar(md5, bboxParam, unlabeledOnly, effectiveMaxDist), 1500);
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
      setTimeout(() => renderSimilar(md5, bboxParam, unlabeledOnly, effectiveMaxDist), 1500);
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
