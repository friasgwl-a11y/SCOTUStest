const el = (id) => document.getElementById(id);

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fmtDate(iso) {
  if (!iso) return "Undated";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function fmtDateLong(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

function timeAgo(iso) {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function escapeHtml(s) {
  if (!s) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function otLabel(term) {
  return `OT ${2000 + parseInt(term, 10)}`;
}

function skeletonCards(n) {
  let html = "";
  for (let i = 0; i < n; i++) {
    html += `
      <div class="skeleton-card" style="animation-delay:${i * 35}ms">
        <div class="skeleton-line w-40"></div>
        <div class="skeleton-line w-25"></div>
        <div class="skeleton-line w-100"></div>
        <div class="skeleton-line w-70"></div>
      </div>`;
  }
  return html;
}

// ---------------------------------------------------------------- theme --

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

function systemPrefersDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function initTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem("scotus-theme");
  } catch (e) {
    /* private browsing / storage blocked: fall back to system preference */
  }
  applyTheme(saved);

  el("themeToggle").addEventListener("click", () => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark"
      || (!document.documentElement.getAttribute("data-theme") && systemPrefersDark());
    const next = isDark ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem("scotus-theme", next);
    } catch (e) {
      /* theme still applies for this page view, just won't persist */
    }
  });
}

// --------------------------------------------------------------- router --

function parseRoute(pathname) {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/" || path === "") return { view: "home" };
  if (path === "/opinions") return { view: "list", type: "opinion" };
  if (path === "/orders") return { view: "list", type: "order" };
  let m = path.match(/^\/opinion\/(\d+)$/);
  if (m) return { view: "detail", type: "opinion", id: m[1] };
  m = path.match(/^\/order\/(\d+)$/);
  if (m) return { view: "detail", type: "order", id: m[1] };
  return { view: "notfound" };
}

function navigate(path) {
  if (location.pathname === path) return;
  history.pushState({}, "", path);
  render();
}

function wireLinkInterception() {
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-link]");
    if (!a) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // let modified clicks behave normally
    e.preventDefault();
    navigate(a.getAttribute("href"));
  });
  window.addEventListener("popstate", render);
}

function setActiveNav(view) {
  document.querySelectorAll(".main-nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === (view === "list" ? listState.type + "s" : view));
  });
}

// ----------------------------------------------------------- list state --

const listState = {
  opinion: { page: 0, pageSize: 20, total: 0, search: "", term: "", justice: "", sort: "date_desc", hasDissent: false },
  order: { page: 0, pageSize: 20, total: 0, search: "", term: "", orderType: "", notableOnly: false },
};
listState.type = "opinion"; // which list the current view is showing

let statsCache = null;

async function loadStats(force) {
  if (statsCache && !force) return statsCache;
  statsCache = await api("/api/stats");
  return statsCache;
}

function updateChrome(stats) {
  const banner = el("errorBanner");
  if (stats.last_fetch_run) {
    const run = stats.last_fetch_run;
    el("lastRun").textContent = `Last fetch: ${timeAgo(run.finished_at || run.started_at)} (${run.status}, +${run.new_opinions}/+${run.new_orders})`;
    if (run.status === "error" && run.error) {
      banner.textContent = `Last fetch reported an error: ${run.error}`;
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  } else {
    el("lastRun").textContent = "No fetch yet";
    banner.classList.add("hidden");
  }
  el("refreshBtn").disabled = !!stats.refresh_running;
  el("refreshBtn").textContent = stats.refresh_running ? "Refreshing…" : "Refresh now";
}

// -------------------------------------------------------------- home view

async function renderHome(app) {
  app.innerHTML = `<div class="empty-state">${skeletonCards(3)}</div>`;

  const [stats, termSummary, argCal] = await Promise.all([
    loadStats(true),
    api("/api/term-summary"),
    api("/api/argument-calendar?days=1"),
  ]);
  updateChrome(stats);

  const current = termSummary.current_term;
  const next = termSummary.next_term;
  const upcoming = argCal.upcoming[0];

  const recent = await api("/api/opinions?limit=4");
  const recentOrders = await api("/api/orders?limit=3");
  const feed = [
    ...recent.items.map((o) => ({ ...o, kind: "opinion" })),
    ...recentOrders.items.map((o) => ({ ...o, kind: "order" })),
  ]
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
    .slice(0, 6);

  app.innerHTML = `
    <section class="term-hero">
      <div class="term-hero-label">${current ? escapeHtml(current.label) : "Current Term"}${current ? "" : " — unavailable"}</div>
      <div class="term-hero-grid">
        <div class="term-hero-stat">
          <div class="term-hero-value">${current ? current.total_granted : "–"}</div>
          <div class="term-hero-caption">cases granted &amp; noted this term</div>
        </div>
        ${next ? `
        <div class="term-hero-stat term-hero-stat-sm">
          <div class="term-hero-value-sm">${next.total_granted}</div>
          <div class="term-hero-caption">granted so far for ${escapeHtml(next.label)}</div>
        </div>` : ""}
      </div>
    </section>

    <div class="home-grid">
      <section class="home-card">
        <h2>Next Argument Day</h2>
        ${upcoming ? `
          <div class="arg-day-date">${fmtDateLong(upcoming.date)}</div>
          <ul class="arg-day-cases">
            ${upcoming.cases.map((c) => `<li><span class="arg-docket">No. ${escapeHtml(c.docket)}</span> ${escapeHtml(titleCase(c.case_name))}</li>`).join("")}
          </ul>
        ` : `<p class="muted">No upcoming argument date found yet.</p>`}
      </section>

      <section class="home-card">
        <h2>Recent Activity</h2>
        <ul class="activity-feed">
          ${feed.map((item) => `
            <li>
              <a href="${item.kind === "opinion" ? "/opinion/" : "/order/"}${item.id}" data-link>
                <span class="activity-date">${fmtDate(item.date)}</span>
                <span class="activity-title">${item.kind === "opinion" ? escapeHtml(item.case_name) : escapeHtml(item.order_type)}</span>
              </a>
            </li>`).join("")}
        </ul>
      </section>
    </div>

    <div class="home-nav-cards">
      <a class="home-nav-card" href="/opinions" data-link>
        <div class="home-nav-card-title">Browse Opinions</div>
        <div class="home-nav-card-count">${stats.total_opinions} tracked</div>
      </a>
      <a class="home-nav-card" href="/orders" data-link>
        <div class="home-nav-card-title">Browse Orders</div>
        <div class="home-nav-card-count">${stats.total_orders} tracked (${stats.notable_orders} notable)</div>
      </a>
    </div>
  `;
}

function titleCase(s) {
  // Granted-list/argument-calendar case names are scraped in ALL CAPS;
  // title-case them for readability on the home page (the list views show
  // the original-case names scraped from the opinions page instead).
  return s.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

// -------------------------------------------------------------- list view

function buildQuery(type) {
  const s = listState[type];
  const params = new URLSearchParams();
  params.set("limit", s.pageSize);
  params.set("offset", s.page * s.pageSize);
  if (s.search) params.set("q", s.search);
  if (s.term) params.set("term", s.term);
  if (type === "order") {
    if (s.orderType) params.set("order_type", s.orderType);
    if (s.notableOnly) params.set("notable", "true");
  } else {
    if (s.justice) params.set("justice", s.justice);
    if (s.sort) params.set("sort", s.sort);
    if (s.hasDissent) params.set("has_dissent", "true");
  }
  return params.toString();
}

function opinionCard(o, index) {
  const badges = [];
  if (o.is_revision) badges.push('<span class="badge badge-revision">Revised</span>');
  if (o.has_dissent) badges.push('<span class="badge badge-notable">Dissent</span>');
  if (o.extraction_error) badges.push('<span class="badge">Text unavailable</span>');

  const snippet = o.summary || o.holding || "Open to generate a summary.";
  const delay = Math.min(index, 12) * 25;
  const author = o.author_name || o.justice;
  return `
    <a class="item-card${o.has_dissent ? " notable-card" : ""}" data-link href="/opinion/${o.id}" style="animation-delay:${delay}ms">
      <div class="item-top">
        <div class="item-title">${escapeHtml(o.case_name)}</div>
        <div class="item-meta">${fmtDate(o.date)} &middot; No. ${escapeHtml(o.docket || "–")}${author ? " &middot; " + escapeHtml(author) : ""}</div>
      </div>
      <div class="item-badges">${badges.join("")}</div>
      <div class="item-snippet">${escapeHtml(snippet).slice(0, 320)}${snippet.length > 320 ? "…" : ""}</div>
    </a>`;
}

function orderCard(o, index) {
  const badges = [`<span class="badge">${escapeHtml(o.order_type)}</span>`];
  if (o.notable) badges.push('<span class="badge badge-notable">Notable</span>');
  if (o.extraction_error) badges.push('<span class="badge">Text unavailable</span>');

  const snippet = o.summary || "Open to generate a summary.";
  const delay = Math.min(index, 12) * 25;
  return `
    <a class="item-card${o.notable ? " notable-card" : ""}" data-link href="/order/${o.id}" style="animation-delay:${delay}ms">
      <div class="item-top">
        <div class="item-title">${fmtDate(o.date)}</div>
      </div>
      <div class="item-badges">${badges.join("")}</div>
      <div class="item-snippet">${escapeHtml(snippet).slice(0, 320)}${snippet.length > 320 ? "…" : ""}</div>
    </a>`;
}

async function renderList(app, type) {
  listState.type = type;
  const s = listState[type];
  const stats = await loadStats();
  updateChrome(stats);

  const terms = stats.tracked_terms || [];
  const termOptions = '<option value="">All terms</option>' +
    terms.map((t) => `<option value="${t}" ${s.term === t ? "selected" : ""}>${otLabel(t)}</option>`).join("");

  app.innerHTML = `
    <nav class="tabs" role="tablist">
      <a class="tab ${type === "opinion" ? "active" : ""}" data-link href="/opinions" role="tab">Opinions</a>
      <a class="tab ${type === "order" ? "active" : ""}" data-link href="/orders" role="tab">Orders</a>
    </nav>

    <section class="toolbar">
      <input id="searchInput" type="search" placeholder="Search case name, docket, holding&hellip;" value="${escapeHtml(s.search)}" />
      <select id="termFilter">${termOptions}</select>
      ${type === "order" ? `
        <select id="typeFilter">
          <option value="">All order types</option>
          <option value="Order List" ${s.orderType === "Order List" ? "selected" : ""}>Order List</option>
          <option value="Miscellaneous Order" ${s.orderType === "Miscellaneous Order" ? "selected" : ""}>Miscellaneous Order</option>
        </select>
        <label class="notable-toggle"><input type="checkbox" id="notableOnly" ${s.notableOnly ? "checked" : ""} /> Notable only</label>
      ` : `
        <select id="justiceFilter">
          <option value="">All authors</option>
          ${(stats.justices || []).map((j) => `<option value="${j}" ${s.justice === j ? "selected" : ""}>${j}</option>`).join("")}
        </select>
        <select id="sortSelect">
          <option value="date_desc" ${s.sort === "date_desc" ? "selected" : ""}>Newest first</option>
          <option value="date_asc" ${s.sort === "date_asc" ? "selected" : ""}>Oldest first</option>
          <option value="author" ${s.sort === "author" ? "selected" : ""}>By author</option>
          <option value="docket" ${s.sort === "docket" ? "selected" : ""}>By docket No.</option>
        </select>
        <label class="notable-toggle"><input type="checkbox" id="dissentOnly" ${s.hasDissent ? "checked" : ""} /> Has dissent</label>
      `}
    </section>

    <section id="listContainer" class="list" aria-live="polite">${skeletonCards(6)}</section>

    <div class="pager">
      <button id="prevPage" class="btn">&larr; Newer</button>
      <span id="pageInfo"></span>
      <button id="nextPage" class="btn">Older &rarr;</button>
    </div>
  `;

  wireListControls(type);
  await loadListItems(type);
}

let listRequestId = 0;

async function loadListItems(type) {
  const listContainer = el("listContainer");
  const requestId = ++listRequestId;
  const endpoint = type === "order" ? "/api/orders" : "/api/opinions";
  try {
    const data = await api(`${endpoint}?${buildQuery(type)}`);
    if (requestId !== listRequestId) return;
    listState[type].total = data.total;
    if (!data.items.length) {
      listContainer.innerHTML = '<div class="empty-state">No results.</div>';
    } else {
      listContainer.innerHTML = data.items
        .map((item, i) => (type === "order" ? orderCard(item, i) : opinionCard(item, i)))
        .join("");
    }
    updatePager(type);
  } catch (err) {
    if (requestId !== listRequestId) return;
    listContainer.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function updatePager(type) {
  const s = listState[type];
  const start = s.total === 0 ? 0 : s.page * s.pageSize + 1;
  const end = Math.min(s.total, (s.page + 1) * s.pageSize);
  el("pageInfo").textContent = `${start}–${end} of ${s.total}`;
  el("prevPage").disabled = s.page === 0;
  el("nextPage").disabled = end >= s.total;
}

let searchDebounce;
function wireListControls(type) {
  const s = listState[type];

  el("searchInput").addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      s.search = e.target.value.trim();
      s.page = 0;
      loadListItems(type);
    }, 300);
  });

  el("termFilter").addEventListener("change", (e) => {
    s.term = e.target.value;
    s.page = 0;
    loadListItems(type);
  });

  if (type === "order") {
    el("typeFilter").addEventListener("change", (e) => {
      s.orderType = e.target.value;
      s.page = 0;
      loadListItems(type);
    });
    el("notableOnly").addEventListener("change", (e) => {
      s.notableOnly = e.target.checked;
      s.page = 0;
      loadListItems(type);
    });
  } else {
    el("justiceFilter").addEventListener("change", (e) => {
      s.justice = e.target.value;
      s.page = 0;
      loadListItems(type);
    });
    el("sortSelect").addEventListener("change", (e) => {
      s.sort = e.target.value;
      s.page = 0;
      loadListItems(type);
    });
    el("dissentOnly").addEventListener("change", (e) => {
      s.hasDissent = e.target.checked;
      s.page = 0;
      loadListItems(type);
    });
  }

  el("prevPage").addEventListener("click", () => {
    if (s.page > 0) {
      s.page -= 1;
      loadListItems(type);
    }
  });
  el("nextPage").addEventListener("click", () => {
    s.page += 1;
    loadListItems(type);
  });
}

// ------------------------------------------------------------ detail view

function detailSkeleton() {
  return `
    <a class="back-link" href="${listState.type === "order" ? "/orders" : "/opinions"}" data-link>&larr; Back</a>
    <div class="skeleton-line w-40" style="height:22px;margin:16px 0 14px;"></div>
    <div class="skeleton-line w-25" style="margin-bottom:22px;"></div>
    <div class="skeleton-line w-100"></div>
    <div class="skeleton-line w-100"></div>
    <div class="skeleton-line w-70"></div>`;
}

const DISSENT_CODE_LEGEND = "C = concurring · D = dissenting · C/J = concurring in the judgment · /P = in part";

function separateOpinionsHtml(text) {
  if (!text) return "";
  return `
    <h3>Concurrences &amp; Dissents</h3>
    <p>${escapeHtml(text)}</p>
    <p class="legend">${DISSENT_CODE_LEGEND}</p>`;
}

function summaryText(data, generating) {
  if (data.summary) return escapeHtml(data.summary);
  if (generating) return '<span class="generating">Generating summary from the PDF…</span>';
  if (data.extraction_error) {
    return "Could not read this PDF. Use the link below to open the official document.";
  }
  return "No summary available yet.";
}

async function renderDetail(app, type, id) {
  app.innerHTML = detailSkeleton();

  const base = `/api/${type === "order" ? "orders" : "opinions"}/${id}`;
  let data;
  try {
    data = await api(base);
  } catch (err) {
    app.innerHTML = `
      <a class="back-link" href="${type === "order" ? "/orders" : "/opinions"}" data-link>&larr; Back</a>
      <div class="empty-state">Couldn't load this ${type} (${escapeHtml(err.message)}).</div>`;
    return;
  }

  const paint = (data, generating) => {
    const backHref = type === "order" ? "/orders" : "/opinions";
    if (type === "opinion") {
      app.innerHTML = `
        <a class="back-link" href="${backHref}" data-link>&larr; Back to Opinions</a>
        <article class="detail-page">
          <h1>${escapeHtml(data.case_name)}</h1>
          <div class="detail-meta">
            ${fmtDate(data.date)} &middot; Docket No. ${escapeHtml(data.docket || "–")}
            ${data.author_name ? " &middot; Author: " + escapeHtml(data.author_name) : (data.justice ? " &middot; Author: " + escapeHtml(data.justice) : "")}
            ${data.citation ? " &middot; " + escapeHtml(data.citation) + " U.S." : ""}
          </div>
          <div class="detail-badges">
            ${data.is_revision ? '<span class="badge badge-revision">Revised opinion</span>' : ""}
            ${data.has_dissent ? '<span class="badge badge-notable">Has dissent</span>' : ""}
          </div>
          ${data.holding ? `<h3>Holding (Court syllabus)</h3><p>${escapeHtml(data.holding)}</p>` : ""}
          <h3>Summary</h3>
          <p>${summaryText(data, generating)}</p>
          ${data.disposition ? `<h3>Disposition</h3><p>${escapeHtml(data.disposition)}</p>` : ""}
          ${separateOpinionsHtml(data.separate_opinions)}
          ${data.argument_date || data.granted_date ? `
            <h3>Case Timeline</h3>
            <p>${data.granted_date ? "Granted " + fmtDate(data.granted_date) : ""}${data.granted_date && data.argument_date ? " &middot; " : ""}${data.argument_date ? "Argued " + fmtDate(data.argument_date) : ""}${" &middot; Decided " + fmtDate(data.date)}</p>
          ` : ""}
          <a class="pdf-link" href="${data.pdf_url}" target="_blank" rel="noopener">Read full opinion (PDF) &rarr;</a>
        </article>`;
    } else {
      app.innerHTML = `
        <a class="back-link" href="${backHref}" data-link>&larr; Back to Orders</a>
        <article class="detail-page">
          <h1>${escapeHtml(data.order_type)}</h1>
          <div class="detail-meta">${fmtDate(data.date)}${data.notable ? " &middot; Flagged notable" : ""}</div>
          <h3>Summary</h3>
          <p>${summaryText(data, generating)}</p>
          <a class="pdf-link" href="${data.pdf_url}" target="_blank" rel="noopener">Read full order (PDF) &rarr;</a>
        </article>`;
    }
  };

  if (!data.summary && !data.extraction_error) {
    paint(data, true);
    try {
      const res = await fetch(`${base}/summarize`, { method: "POST" });
      if (res.ok) data = await res.json();
    } catch (err) {
      /* fall through and render whatever we have */
    }
  }
  paint(data, false);
}

// ------------------------------------------------------------------ main --

async function render() {
  const route = parseRoute(location.pathname);
  const app = el("app");
  setActiveNav(route.view === "list" ? route.type + "s" : route.view);
  window.scrollTo({ top: 0 });

  if (route.view === "home") {
    await renderHome(app);
  } else if (route.view === "list") {
    await renderList(app, route.type);
  } else if (route.view === "detail") {
    await renderDetail(app, route.type, route.id);
  } else {
    app.innerHTML = `<div class="empty-state">Page not found. <a href="/" data-link>Go home</a>.</div>`;
  }
}

async function pollUntilIdle() {
  const stats = await loadStats(true);
  updateChrome(stats);
  if (stats.refresh_running) {
    setTimeout(pollUntilIdle, 4000);
  } else if (parseRoute(location.pathname).view !== "detail") {
    render();
  }
}

function wireGlobalActions() {
  el("refreshBtn").addEventListener("click", async () => {
    el("refreshBtn").disabled = true;
    el("refreshBtn").textContent = "Refreshing…";
    await fetch("/api/refresh", { method: "POST" });
    pollUntilIdle();
  });
}

async function init() {
  initTheme();
  wireLinkInterception();
  wireGlobalActions();
  await render();
  setInterval(() => loadStats(true).then(updateChrome), 30000);
}

init();
