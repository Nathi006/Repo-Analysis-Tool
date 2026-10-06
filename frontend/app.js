/* RAT dashboard frontend — vanilla JS, no framework. */
"use strict";

const state = {
  repoId: null,
  kind: "repo",          // repo | dir | file
  path: "",
  from: null,            // unix ts (inclusive)
  to: null,              // unix ts (exclusive)
  authors: [],           // selected author ids
  commits: [],           // manually selected commit hashes
  detail: null,          // repo detail (authors, bounds)
  tree: [],              // paths list
  charts: { ts: null, own: null },
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtNum(n) {
  if (n === null || n === undefined) return "0";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}
function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString(undefined,
    { year: "numeric", month: "short", day: "numeric" });
}
function fmtPct(x) { return (x * 100).toFixed(1) + "%"; }

let toastTimer = null;
function toast(msg, isError) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* noop */ }
    throw new Error(msg);
  }
  return res.json();
}

function filterParams() {
  const p = new URLSearchParams();
  if (state.from) p.set("from", state.from);
  if (state.to) p.set("to", state.to);
  if (state.authors.length) p.set("authors", state.authors.join(","));
  if (state.commits.length) p.set("commits", state.commits.join(","));
  return p;
}

/* ---------------- repositories ---------------- */

async function loadRepos() {
  const repos = await api("/api/repos");
  state.repos = repos;
  renderRepoList();
  const busy = repos.some((r) => ["pending", "cloning", "extracting"].includes(r.status));
  if (busy) setTimeout(loadRepos, 2000);
}

function renderRepoList() {
  const box = $("repo-list");
  if (!state.repos.length) {
    box.innerHTML = `<div style="color:#94a3b8;font-size:12.5px">No repositories yet.</div>`;
    return;
  }
  box.innerHTML = state.repos.map((r) => {
    const active = r.id === state.repoId ? " active" : "";
    const busy = ["pending", "cloning", "extracting"].includes(r.status);
    const pct = r.total ? Math.round((r.done / r.total) * 100) : 0;
    return `<div class="repo-item${active}" data-id="${r.id}">
      <div class="name">${esc(r.name)}</div>
      <div class="meta">${esc(r.kind)} · <span class="commits">${fmtNum(r.commit_count)} commits</span>
        · <span class="badge ${esc(r.status)}">${esc(r.status)}</span></div>
      ${busy ? `<div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>` : ""}
      ${r.error ? `<div class="meta" style="color:#fca5a5">${esc(r.error)}</div>` : ""}
      <div class="actions">
        <button class="btn danger del" data-id="${r.id}">Remove</button>
      </div>
    </div>`;
  }).join("");
  box.querySelectorAll(".repo-item").forEach((el) =>
    el.addEventListener("click", (e) => {
      if (e.target.closest(".del")) return;
      selectRepo(parseInt(el.dataset.id));
    }));
  box.querySelectorAll(".del").forEach((el) =>
    el.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Remove this repository and its metrics?")) return;
      await api(`/api/repos/${el.dataset.id}`, { method: "DELETE" });
      if (state.repoId === parseInt(el.dataset.id)) {
        state.repoId = null;
        $("dashboard").classList.add("hidden");
        $("empty-state").classList.remove("hidden");
      }
      loadRepos();
    }));
}

async function selectRepo(id) {
  state.repoId = id;
  state.kind = "repo";
  state.path = "";
  state.from = state.to = null;
  state.authors = [];
  state.commits = [];
  $("date-from").value = "";
  $("date-to").value = "";
  await Promise.all([loadDetail(), loadTree()]);
  $("empty-state").classList.add("hidden");
  $("dashboard").classList.remove("hidden");
  renderRepoList();
  renderAuthorPanel();
  refreshAll();
}

async function loadDetail() {
  state.detail = await api(`/api/repos/${state.repoId}`);
}

async function loadTree() {
  state.tree = await api(`/api/repos/${state.repoId}/tree`);
  renderPathTree();
}

/* ---------------- filters ---------------- */

function renderAuthorPanel() {
  const opts = $("author-options");
  if (!state.detail) return;
  opts.innerHTML = state.detail.authors.map((a) => {
    const checked = state.authors.includes(a.id) ? " checked" : "";
    const merged = a.canonical_id ? " <span style='color:#94a3b8'>(merged)</span>" : "";
    return `<div class="author-opt"><input type="checkbox" value="${a.id}"${checked}>
      <label>${esc(a.name)} &lt;${esc(a.email)}&gt;${merged}</label></div>`;
  }).join("");
  opts.querySelectorAll("input").forEach((cb) =>
    cb.addEventListener("change", () => {
      state.authors = [...opts.querySelectorAll("input:checked")].map((i) => parseInt(i.value));
      renderAuthorPanel();
      refreshAll();
    }));
}

function buildPathTree(paths, filter) {
  const q = (filter || "").toLowerCase();
  const nodes = new Map();
  nodes.set("", { path: "", kind: "dir", children: new Map() });
  for (const p of paths) {
    const parts = p.path.split("/");
    let cur = nodes.get("");
    for (let i = 0; i < parts.length; i++) {
      const full = parts.slice(0, i + 1).join("/");
      if (!cur.children.has(full)) {
        const isFile = i === parts.length - 1 && p.kind === "file";
        cur.children.set(full, {
          path: full, kind: isFile ? "file" : "dir", children: new Map(),
        });
      }
      cur = cur.children.get(full);
    }
  }
  function render(node, depth) {
    let html = "";
    for (const child of node.children.values()) {
      const name = child.path.split("/").pop();
      const match = !q || child.path.toLowerCase().includes(q);
      const childHtml = child.children.size ? render(child, depth + 1) : "";
      if (!match && !childHtml) continue;
      const icon = child.kind === "file" ? "📄" : "📁";
      const active = state.path === child.path && state.kind === child.kind ? " active" : "";
      html += `<div class="node ${child.kind}${active}" data-path="${esc(child.path)}"
        data-kind="${child.kind}" style="padding-left:${6 + depth * 16}px">
        ${icon} ${esc(name)}</div>${childHtml}`;
    }
    return html;
  }
  return render(nodes.get(""), 0) || `<div style="color:#94a3b8;padding:8px">No matches</div>`;
}

function renderPathTree(filter) {
  const box = $("path-tree");
  box.innerHTML = `<div class="node dir${state.kind === "repo" ? " active" : ""}"
    data-path="" data-kind="repo" style="padding-left:6px">🏠 Repository</div>` +
    buildPathTree(state.tree, filter);
  box.querySelectorAll(".node").forEach((n) =>
    n.addEventListener("click", () => {
      state.kind = n.dataset.kind;
      state.path = n.dataset.path;
      updatePathLabel();
      $("path-panel").classList.add("hidden");
      renderPathTree();
      refreshAll();
    }));
}

function updatePathLabel() {
  $("path-label").textContent =
    state.kind === "repo" ? "Repository" : state.path;
  $("path-btn").classList.toggle("active", state.kind !== "repo");
}

function refreshAll() {
  if (!state.repoId) return;
  renderSetSummary();
  loadOverview();
  loadLeaders("files");
  loadLeaders("dirs");
  loadAuthorsTab();
  loadCommitsTab();
}

async function loadOverview() {
  try {
    const p = filterParams();
    const data = await api(`/api/repos/${state.repoId}/metrics?kind=${state.kind}` +
      `&path=${encodeURIComponent(state.path)}&${p}`);
    renderMetricCards(data);
    renderObjectChip(data);
    renderAuthorBreakdown(data);
    loadTimeseries(p);
  } catch (e) { toast(e.message, true); }
}

function renderObjectChip(data) {
  const chip = $("object-chip");
  if (state.kind === "repo") { chip.innerHTML = ""; return; }
  chip.innerHTML = `${state.kind === "file" ? "📄" : "📁"} <span class="mono">${esc(state.path)}</span>
    <button id="chip-clear" title="Clear path filter">✕</button>`;
  $("chip-clear").addEventListener("click", () => {
    state.kind = "repo";
    state.path = "";
    updatePathLabel();
    renderPathTree();
    refreshAll();
  });
}

function renderMetricCards(data) {
  const m = data.metric;
  const cards = [
    ["Added lines", fmtNum(m.added), "pos"],
    ["Removed lines", fmtNum(m.removed), ""],
    ["Growth", (m.growth >= 0 ? "+" : "") + fmtNum(m.growth), m.growth < 0 ? "neg" : "pos"],
    ["Churn", fmtNum(m.churn), ""],
    ["Modifications", fmtNum(m.modifications), ""],
    ["Modification frequency", m.frequency.toFixed(3), ""],
    ["Churn rate", m.churn_rate.toFixed(3), ""],
  ];
  $("metric-cards").innerHTML = cards.map(([label, value, cls]) =>
    `<div class="card"><div class="label">${label}</div>
     <div class="value ${cls}">${value}</div></div>`).join("");
  $("set-summary").textContent =
    `${fmtNum(data.set.count)} commits · ${fmtDate(data.set.from)} → ${fmtDate(data.set.to)}`;
}

function renderAuthorBreakdown(data) {
  const rows = data.authors.map((a) => `
    <tr><td>${esc(a.name)}</td><td class="mono">${esc(a.email)}</td>
    <td class="num">${fmtNum(a.modifications)}</td>
    <td class="num">${fmtNum(a.churn)}</td>
    <td class="num">${fmtPct(a.ownership)}</td></tr>`).join("");
  $("author-table-wrap").innerHTML = `<table>
    <thead><tr><th>Author</th><th>Email</th><th>Modifications</th><th>Churn</th><th>Ownership</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5" class="empty-row">No commits in the selected set.</td></tr>`}
    </tbody></table>`;
  renderOwnershipChart(data.authors);
}

async function loadTimeseries(p) {
  try {
    const data = await api(`/api/repos/${state.repoId}/timeseries?kind=${state.kind}` +
      `&path=${encodeURIComponent(state.path)}&bucket=week&${p}`);
    renderTimeseriesChart(data);
  } catch (e) { /* charts are non-critical */ }
}

/* ---------------- charts ---------------- */

function renderTimeseriesChart(data) {
  if (typeof Chart === "undefined") return;
  if (state.charts.ts) state.charts.ts.destroy();
  const ctx = $("chart-timeseries");
  state.charts.ts = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.map((d) => fmtDate(d.t)),
      datasets: [
        { label: "Added", data: data.map((d) => d.added), backgroundColor: "#16a34a" },
        { label: "Removed", data: data.map((d) => -d.removed), backgroundColor: "#dc2626" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { stacked: true }, y: { stacked: true } },
      plugins: { legend: { display: false } },
    },
  });
}

function renderOwnershipChart(authors) {
  if (typeof Chart === "undefined") return;
  if (state.charts.own) state.charts.own.destroy();
  const top = authors.slice(0, 8);
  state.charts.own = new Chart($("chart-ownership"), {
    type: "doughnut",
    data: {
      labels: top.map((a) => a.name),
      datasets: [{ data: top.map((a) => a.churn) }],
    },
    options: { responsive: true, maintainAspectRatio: false, cutout: "55%" },
  });
}

/* ---------------- tables ---------------- */

function statTable(rows, kind, onPick) {
  return `<table><thead><tr>
    <th data-sort="path">Path</th>
    <th data-sort="added">Added</th>
    <th data-sort="removed">Removed</th>
    <th data-sort="growth">Growth</th>
    <th data-sort="churn">Churn</th>
    <th data-sort="mods">Mods</th>
    <th>Owner</th></tr></thead><tbody>
    ${rows.map((r) => {
      const churn = r.added + r.removed;
      return `<tr><td class="path"><span class="path-link" data-path="${esc(r.path)}"
        data-kind="${kind}">${esc(r.path)}</span></td>
      <td class="num">${fmtNum(r.added)}</td>
      <td class="num">${fmtNum(r.removed)}</td>
      <td class="num">${(r.added - r.removed >= 0 ? "+" : "")}${fmtNum(r.added - r.removed)}</td>
      <td class="num">${fmtNum(churn)}</td>
      <td class="num">${fmtNum(r.mods)}</td>
      <td class="owner-cell" id="owner-${kind}-${btoa(unescape(encodeURIComponent(r.path)))}">…</td>
      </tr>`;
    }).join("") || `<tr><td colspan="7" class="empty-row">Nothing changed in this set.</td></tr>`}
    </tbody></table>`;
}

async function loadLeaders(tab) {
  if (!state.repoId) return;
  const kind = tab === "files" ? "file" : "dir";
  const p = filterParams();
  try {
    const rows = await api(`/api/repos/${state.repoId}/leaders?kind=${kind}&limit=200&${p}`);
    const box = $(`${tab}-table`);
    box.innerHTML = statTable(rows, kind);
    box.querySelectorAll(".path-link").forEach((el) =>
      el.addEventListener("click", () => {
        state.kind = el.dataset.kind;
        state.path = el.dataset.path;
        updatePathLabel();
        renderPathTree();
        refreshAll();
      }));
    // attach sorting on headers
    attachSort(box, rows, kind);
    // fill owner column lazily
    fillOwners(rows, kind);
  } catch (e) { toast(e.message, true); }
}

function attachSort(box, rows, kind) {
  box.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      const dir = th.dataset.dir === "asc" ? -1 : 1;
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      const sorted = [...rows].sort((a, b) => {
        const va = key === "path" ? a.path : key === "growth" ? a.added - a.removed
          : key === "churn" ? a.added + a.removed : key === "mods" ? a.mods : a[key];
        const vb = key === "path" ? b.path : key === "growth" ? b.added - b.removed
          : key === "churn" ? b.added + b.removed : key === "mods" ? b.mods : b[key];
        return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
      });
      box.innerHTML = statTable(sorted, kind);
      box.querySelectorAll(".path-link").forEach((el) =>
        el.addEventListener("click", () => {
          state.kind = el.dataset.kind;
          state.path = el.dataset.path;
          updatePathLabel();
          renderPathTree();
          refreshAll();
        }));
      fillOwners(sorted, kind);
    });
  });
}

async function fillOwners(rows, kind) {
  const p = filterParams();
  const top = rows.slice(0, 30);
  await Promise.all(top.map(async (r) => {
    const cell = $(`owner-${kind}-${btoa(unescape(encodeURIComponent(r.path)))}`);
    if (!cell) return;
    try {
      const data = await api(`/api/repos/${state.repoId}/metrics?kind=${kind}` +
        `&path=${encodeURIComponent(r.path)}&${p}`);
      const owner = data.authors[0];
      cell.innerHTML = owner
        ? `<span class="owner-bar" style="width:${Math.max(6, owner.ownership * 60)}px"></span>
           ${esc(owner.name)} ${fmtPct(owner.ownership)}`
        : "";
    } catch (e) { cell.textContent = ""; }
  }));
}

async function loadAuthorsTab() {
  if (!state.repoId) return;
  const p = filterParams();
  const rows = await api(`/api/repos/${state.repoId}/authors?limit=300&${p}`);
  const merged = new Set((state.detail?.authors || [])
    .filter((a) => a.canonical_id).map((a) => a.id));
  $("authors-table").innerHTML = `<table><thead><tr>
    <th></th><th>Author</th><th>Email</th><th>Commits</th><th>Mods</th><th>Churn</th>
    <th>Ownership</th></tr></thead><tbody>
    ${rows.filter((r) => !merged.has(r.id)).map((r) => `
      <tr><td><input type="checkbox" class="merge-cb" value="${r.id}"></td>
      <td>${esc(r.name)}</td><td class="mono">${esc(r.email)}</td>
      <td class="num">${fmtNum(r.commits)}</td><td class="num">${fmtNum(r.mods)}</td>
      <td class="num">${fmtNum(r.churn)}</td>
      <td class="num">${fmtPct(r.ownership)}</td></tr>`).join("")
      || `<tr><td colspan="7" class="empty-row">No authors.</td></tr>`}</tbody></table>`;
}

async function mergeSelected() {
  const ids = [...document.querySelectorAll(".merge-cb:checked")].map((c) => parseInt(c.value));
  if (ids.length < 2) { toast("Select at least two authors to merge.", true); return; }
  try {
    await api(`/api/repos/${state.repoId}/authors/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ids),
    });
    toast("Authors merged.");
    await Promise.all([loadDetail(), loadTree()]);
    renderAuthorPanel();
    refreshAll();
  } catch (e) { toast(e.message, true); }
}

async function loadCommitsTab() {
  if (!state.repoId) return;
  const data = await api(`/api/repos/${state.repoId}/commits?limit=500`);
  const selected = new Set(state.commits);
  $("commit-sel-count").textContent = state.commits.length;
  $("commits-table").innerHTML = `<table><thead><tr>
    <th></th><th>Hash</th><th>Date</th><th>Author</th><th>Subject</th></tr></thead><tbody>
    ${data.map((c) => `<tr>
      <td><input type="checkbox" class="commit-cb" value="${c.hash}"${selected.has(c.hash) ? " checked" : ""}></td>
      <td class="mono">${c.hash.slice(0, 10)}</td>
      <td>${fmtDate(c.committer_ts)}</td>
      <td>${esc(c.name)}</td><td>${esc(c.subject)}</td></tr>`).join("")}
    </tbody></table>`;
  document.querySelectorAll(".commit-cb").forEach((cb) =>
    cb.addEventListener("change", () => {
      state.commits = [...document.querySelectorAll(".commit-cb:checked")]
        .map((c) => c.value);
      $("commit-sel-count").textContent = state.commits.length;
      renderSetSummary();
      refreshAll();
    }));
}

function renderSetSummary() {
  $("set-summary").textContent = "loading…";
}

/* ---------------- tab switching ---------------- */

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    document.querySelectorAll(".tab-body").forEach((x) => x.classList.add("hidden"));
    $("tab-" + t.dataset.tab).classList.remove("hidden");
    if (t.dataset.tab === "commits") loadCommitsTab();
  }));

/* ---------------- panel toggles ---------------- */

$("path-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("path-panel").classList.toggle("hidden");
  $("author-panel").classList.add("hidden");
});
$("author-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("author-panel").classList.toggle("hidden");
  $("path-panel").classList.add("hidden");
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".filter-group")) {
    $("path-panel").classList.add("hidden");
    $("author-panel").classList.add("hidden");
  }
});
$("path-search").addEventListener("input", (e) => renderPathTree(e.target.value));

/* ---------------- date filters ---------------- */

function dateToTs(dateStr, endOfDay) {
  if (!dateStr) return null;
  const d = new Date(dateStr + "T00:00:00Z");
  if (isNaN(d)) return null;
  return Math.floor(d.getTime() / 1000) + (endOfDay ? 86400 : 0);
}
$("date-from").addEventListener("change", (e) => {
  state.from = dateToTs(e.target.value, false);
  refreshAll();
});
$("date-to").addEventListener("change", (e) => {
  state.to = dateToTs(e.target.value, true);   // exclusive end: day + 1
  refreshAll();
});

/* ---------------- add repos ---------------- */

$("btn-clone").addEventListener("click", async () => {
  const url = $("clone-url").value.trim();
  if (!url) { toast("Enter a repository URL.", true); return; }
  try {
    await api("/api/repos/clone?url=" + encodeURIComponent(url) +
      "&ref=" + encodeURIComponent($("clone-ref").value.trim() || "HEAD"),
      { method: "POST" });
    $("clone-url").value = "";
    toast("Clone started — this can take a while for large repositories.");
    loadRepos();
  } catch (e) { toast(e.message, true); }
});

$("zip-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api("/api/repos/upload", { method: "POST", body: fd });
    toast("Zip upload started.");
    loadRepos();
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});

$("btn-merge").addEventListener("click", mergeSelected);
$("btn-reset").addEventListener("click", () => {
  state.kind = "repo";
  state.path = "";
  state.from = state.to = null;
  state.authors = [];
  state.commits = [];
  $("date-from").value = "";
  $("date-to").value = "";
  $("commit-sel-count").textContent = "0";
  updatePathLabel();
  renderPathTree();
  renderAuthorPanel();
  refreshAll();
});
$("btn-commit-clear").addEventListener("click", () => {
  state.commits = [];
  $("commit-sel-count").textContent = "0";
  loadCommitsTab();
  refreshAll();
});
$("commits-search").addEventListener("input", () => {
  const q = $("commits-search").value.toLowerCase();
  document.querySelectorAll("#commits-table tbody tr").forEach((tr) => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});
$("files-search").addEventListener("input", () => {
  const q = $("files-search").value.toLowerCase();
  document.querySelectorAll("#files-table tbody tr").forEach((tr) => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});
$("dirs-search").addEventListener("input", () => {
  const q = $("dirs-search").value.toLowerCase();
  document.querySelectorAll("#dirs-table tbody tr").forEach((tr) => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});

/* ---------------- boot ---------------- */

loadRepos().catch((e) => toast("Cannot reach API: " + e.message, true));
