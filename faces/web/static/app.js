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
  return bbox.join("-");
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
    case "clusters":
      if (parts[1]) renderClusterDetail(parseInt(parts[1], 10));
      else renderClusters();
      break;
    case "photos":
      if (parts[1] === "page") renderPhotos(parseInt(parts[2], 10) || 1);
      else if (parts[1]) renderPhotoDetail(parts[1]);
      else renderPhotos(1);
      break;
    case "people":
      if (parts[1]) renderPersonDetail(decodeURIComponent(parts[1]));
      else renderPeople();
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
async function renderClassify() {
  showSpinner();
  let data, people;
  try {
    [data, people] = await Promise.all([
      apiFetch("/api/classify/candidates?min_size=3"),
      apiFetch("/api/people"),
    ]);
  } catch (e) {
    showError(e.message);
    return;
  }

  // Known people names, sorted, excluding special labels
  const knownNames = people
    .map(p => p.name)
    .filter(n => !SPECIAL_LABELS.includes(n))
    .sort((a, b) => a.localeCompare(b));

  // JS state
  const groups = data.groups.map(g => ({
    ...g,
    deselected: new Set(),
    nameEl: null,
  }));
  const unmatched = data.unmatched.map(f => ({ ...f, label: "" }));

  const app = document.getElementById("app");

  // Build HTML
  let html = `<h2>Classify</h2>`;

  if (groups.length === 0 && unmatched.length === 0) {
    html += `<p>No classify candidates found. Run <code>scan</code> and <code>clusterize</code> first.</p>`;
    app.innerHTML = html;
    return;
  }

  html += `<div id="classify-groups">`;
  groups.forEach((g, gi) => {
    // Build options; ensure the predicted person is always present
    const optionNames = knownNames.includes(g.person)
      ? knownNames
      : [g.person, ...knownNames];
    const options = [
      `<option value="">— skip group —</option>`,
      ...optionNames.map(n =>
        `<option value="${escHtml(n)}"${n === g.person ? " selected" : ""}>${escHtml(n)}</option>`
      ),
    ].join("");

    html += `
      <div class="classify-group" data-group="${gi}">
        <div class="classify-group-header">
          <input type="checkbox" id="chk-all-${gi}" checked title="Select all">
          <select id="name-${gi}">${options}</select>
          <span class="dist-tag">avg dist: ${g.avg_dist.toFixed(3)}</span>
        </div>
        <div class="face-grid" id="grid-${gi}">
          ${g.faces.map((f, fi) => `
            <div class="face-cell">
              <img src="${f.img_url}" data-group="${gi}" data-face="${fi}"
                   class="selected" title="${escHtml(f.photo_path)} (dist ${f.dist.toFixed(3)})"
                   loading="lazy">
              <a href="#/photos/${f.md5}" target="_blank" class="face-link-btn" title="Open photo">↗</a>
            </div>
          `).join("")}
        </div>
      </div>`;
  });
  html += `</div>`;

  if (unmatched.length > 0) {
    html += `
      <details>
        <summary>Unmatched faces (${unmatched.length})</summary>
        <div id="unmatched-wrap">
          ${unmatched.map((f, ui) => `
            <span class="unmatched-face">
              <img src="${f.img_url}" loading="lazy" title="${f.md5}">
              <select data-unmatched="${ui}">
                <option value="">— skip —</option>
                <option value="__nonface__">Not a face</option>
                <option value="__foreign__">Foreign</option>
              </select>
            </span>
          `).join("")}
        </div>
      </details>`;
  }

  html += `<button id="submit-labels" style="margin-top:1rem;">Submit labels</button>`;
  app.innerHTML = html;

  // Store name input back-refs
  groups.forEach((g, gi) => { g.nameEl = document.getElementById(`name-${gi}`); });

  // Checkbox/thumbnail logic
  function refreshGroupCheckbox(gi) {
    const g = groups[gi];
    const chk = document.getElementById(`chk-all-${gi}`);
    const total = g.faces.length;
    const deselCount = g.deselected.size;
    if (deselCount === 0) {
      chk.checked = true;
      chk.indeterminate = false;
    } else if (deselCount === total) {
      chk.checked = false;
      chk.indeterminate = false;
    } else {
      chk.checked = false;
      chk.indeterminate = true;
    }
  }

  // Face thumbnail click → toggle selection
  app.querySelectorAll(".face-grid img").forEach(img => {
    img.addEventListener("click", () => {
      const gi = parseInt(img.dataset.group, 10);
      const fi = parseInt(img.dataset.face, 10);
      const g = groups[gi];
      const key = `${g.faces[fi].md5}:${bboxToQuery(g.faces[fi].bbox)}`;
      if (g.deselected.has(key)) {
        g.deselected.delete(key);
        img.className = "selected";
      } else {
        g.deselected.add(key);
        img.className = "deselected";
      }
      refreshGroupCheckbox(gi);
    });
  });

  // Select-all checkbox
  app.querySelectorAll("[id^='chk-all-']").forEach(chk => {
    chk.addEventListener("change", () => {
      const gi = parseInt(chk.id.replace("chk-all-", ""), 10);
      const g = groups[gi];
      const grid = document.getElementById(`grid-${gi}`);
      if (chk.checked) {
        g.deselected.clear();
        grid.querySelectorAll("img").forEach(img => img.className = "selected");
      } else {
        g.faces.forEach((f, fi) => {
          const key = `${f.md5}:${bboxToQuery(f.bbox)}`;
          g.deselected.add(key);
          grid.querySelectorAll("img")[fi].className = "deselected";
        });
      }
    });
  });

  // Unmatched selects
  app.querySelectorAll("[data-unmatched]").forEach(sel => {
    sel.addEventListener("change", () => {
      const ui = parseInt(sel.dataset.unmatched, 10);
      unmatched[ui].label = sel.value;
    });
  });

  // Submit
  document.getElementById("submit-labels").addEventListener("click", async () => {
    const items = [];
    groups.forEach(g => {
      const name = g.nameEl.value.trim();
      if (!name) return;
      g.faces.forEach(f => {
        const key = `${f.md5}:${bboxToQuery(f.bbox)}`;
        if (!g.deselected.has(key)) {
          items.push({ md5: f.md5, bbox: f.bbox, name });
        }
      });
    });
    unmatched.forEach(f => {
      if (f.label) items.push({ md5: f.md5, bbox: f.bbox, name: f.label });
    });

    if (items.length === 0) {
      alert("Nothing to submit. Enter a name for at least one group.");
      return;
    }

    const btn = document.getElementById("submit-labels");
    btn.disabled = true;
    btn.textContent = "Submitting…";
    try {
      const resp = await apiPost("/api/classify/labels", items);
      btn.textContent = `Done — ${resp.labeled} labeled`;
      setTimeout(() => renderClassify(), 1500);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Submit labels";
      showError(e.message);
    }
  });
}

// ---------------------------------------------------------------------------
// View: Clusters
// ---------------------------------------------------------------------------
async function renderClusters() {
  showSpinner();
  let data;
  try {
    data = await apiFetch("/api/clusters?min_size=1");
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  if (!data.length) {
    app.innerHTML = `<h2>Clusters</h2><p>No clusters yet. Use the <a href="#/clusters">clusterize panel</a> or run <code>python -m faces clusterize</code>.</p>`;
    return;
  }

  let html = `<h2>Clusters <span class="badge">${data.length}</span></h2><div class="cluster-grid">`;
  data.forEach(c => {
    const name = c.name ? escHtml(c.name) : `<em>Unnamed #${c.id}</em>`;
    const thumbs = c.sample_faces.slice(0, 4).map(f =>
      `<img src="${f.img_url}" loading="lazy" alt="">`
    ).join("");
    html += `
      <article class="cluster-card" data-cid="${c.id}">
        <div class="sample-faces">${thumbs}</div>
        <p class="cluster-name">${name}</p>
        <span class="cluster-size badge">${c.size} faces</span>
      </article>`;
  });
  html += `</div>`;

  // Clusterize panel at bottom
  html += clusterizePanelHtml();
  app.innerHTML = html;

  app.querySelectorAll(".cluster-card").forEach(card => {
    card.addEventListener("click", () => {
      location.hash = `#/clusters/${card.dataset.cid}`;
    });
  });

  attachClusterizePanel(app);
}

// ---------------------------------------------------------------------------
// View: Cluster Detail
// ---------------------------------------------------------------------------
async function renderClusterDetail(id) {
  showSpinner();
  let data;
  try {
    data = await apiFetch(`/api/clusters/${id}`);
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  const name = data.name || "";

  let html = `
    <p class="breadcrumb"><a href="#/clusters">← Clusters</a></p>
    <h2>${name ? escHtml(name) : `Cluster #${id}`} <span class="badge">${data.size} faces</span></h2>
    <form id="rename-form" style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem;">
      <input type="text" id="cluster-name-input" value="${escHtml(name)}" placeholder="Name this cluster" style="flex:1;min-width:200px;">
      <label style="display:flex;align-items:center;gap:0.4rem;margin:0;">
        <input type="checkbox" id="stick-chk" role="switch"> Stick
      </label>
      <button type="submit">Save</button>
      <span id="rename-status" style="font-size:0.85rem;color:var(--pico-muted-color);"></span>
    </form>
    <div class="face-grid">
      ${data.faces.map(f => `
        <a href="#/photos/${f.md5}" title="${escHtml(f.photo_path)} (score ${f.score.toFixed(2)})">
          <img src="${f.img_url}" loading="lazy" alt="">
        </a>
      `).join("")}
    </div>
    ${clusterizePanelHtml()}
  `;

  app.innerHTML = html;

  document.getElementById("rename-form").addEventListener("submit", async e => {
    e.preventDefault();
    const nameVal = document.getElementById("cluster-name-input").value.trim();
    const stick = document.getElementById("stick-chk").checked;
    const status = document.getElementById("rename-status");
    status.textContent = "Saving…";
    try {
      const resp = await apiPatch(`/api/clusters/${id}`, { name: nameVal, stick });
      status.textContent = `Saved — ${resp.faces_updated} faces updated`;
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  });

  attachClusterizePanel(app);
}

// ---------------------------------------------------------------------------
// Clusterize panel (shared HTML + wiring)
// ---------------------------------------------------------------------------
function clusterizePanelHtml() {
  return `
    <div class="clusterize-panel">
      <h3>Run clusterize</h3>
      <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
        <input type="checkbox" id="clusterize-reset" role="switch"> Reset existing clusters
      </label>
      <button id="clusterize-btn">Run clusterize</button>
      <span id="clusterize-status" style="margin-left:0.75rem;font-size:0.85rem;color:var(--pico-muted-color);"></span>
    </div>`;
}

function attachClusterizePanel(app) {
  document.getElementById("clusterize-btn").addEventListener("click", async () => {
    const reset = document.getElementById("clusterize-reset").checked;
    const btn = document.getElementById("clusterize-btn");
    const status = document.getElementById("clusterize-status");
    btn.disabled = true;
    status.textContent = "Running…";
    try {
      const resp = await apiPost("/api/clusterize", { reset });
      status.textContent = `Done — ${resp.clusters_created} clusters created`;
      btn.disabled = false;
    } catch (err) {
      btn.disabled = false;
      if (err.message.includes("409")) {
        status.textContent = "Clusters already exist — enable Reset to overwrite.";
      } else {
        status.textContent = `Error: ${err.message}`;
      }
    }
  });
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
      const link = f.cluster_id != null ? `#/clusters/${f.cluster_id}` : "#/clusters";
      html += `<a href="${link}"><img src="${f.img_url}" loading="lazy" title="${f.sticky_name || ""}"></a>`;
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
      </li>`;
  });
  html += `</ul>`;
  app.innerHTML = html;
}

// ---------------------------------------------------------------------------
// View: Person Detail
// ---------------------------------------------------------------------------
async function renderPersonDetail(name) {
  showSpinner();
  let data;
  try {
    data = await apiFetch(`/api/people/${encodeURIComponent(name)}`);
  } catch (e) {
    showError(e.message);
    return;
  }

  const app = document.getElementById("app");
  let html = `
    <p class="breadcrumb"><a href="#/people">← People</a></p>
    <h2>${escHtml(data.name)}</h2>
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
  html += `</ul>`;
  app.innerHTML = html;

  app.querySelectorAll(".photo-list-item").forEach(li => {
    li.addEventListener("click", () => { location.hash = `#/photos/${li.dataset.md5}`; });
  });
}

// ---------------------------------------------------------------------------
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
