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

function initTheme() {
  // Dark is opt-in only: light is the enforced default regardless of the
  // visitor's system preference, so "saved" is the only source of truth
  // for whether dark mode is active -- no system-preference fallback.
  let saved = null;
  try {
    saved = localStorage.getItem("scotus-theme");
  } catch (e) {
    /* private browsing / storage blocked: theme just won't persist */
  }
  applyTheme(saved);

  el("themeToggle").addEventListener("click", () => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
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
  m = path.match(/^\/questions-presented\/(\w+)$/);
  if (m) return { view: "qp", term: m[1] };
  m = path.match(/^\/opinion\/(\d+)\/syllabus$/);
  if (m) return { view: "opinionFullText", id: m[1], kind: "syllabus" };
  m = path.match(/^\/opinion\/(\d+)\/separate\/(\d+)$/);
  if (m) return { view: "opinionFullText", id: m[1], kind: "separate", position: Number(m[2]) };
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
  // timeScope partitions the "quick reference" default (recent) from the
  // "look back further" views (this term / past terms), per the
  // dashboard's actual purpose: glance at what the Court just did,
  // without that being buried by everything it's ever done.
  opinion: { page: 0, pageSize: 20, total: 0, search: "", term: "", justice: "", sort: "date_desc", hasDissent: false, timeScope: "recent" },
  // Orders default to the current term only -- old orders remain fully
  // reachable via the term dropdown, they just aren't mixed in by
  // default the way opinions briefly were.
  order: { page: 0, pageSize: 20, total: 0, search: "", term: "", orderType: "", notableOnly: false, termInitialized: false },
};
listState.type = "opinion"; // which list the current view is showing

let statsCache = null;
let termSummaryCache = null;

async function loadStats(force) {
  if (statsCache && !force) return statsCache;
  statsCache = await api("/api/stats");
  return statsCache;
}

async function loadTermSummary(force) {
  if (termSummaryCache && !force) return termSummaryCache;
  termSummaryCache = await api("/api/term-summary");
  return termSummaryCache;
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

  const recent = await api("/api/opinions?limit=4&scope=recent");
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
          ${current ? `
          <a class="term-hero-value" href="/questions-presented/${current.term}" data-link title="See the questions presented for ${escapeHtml(current.label)}">${current.total_granted}</a>
          ` : `<div class="term-hero-value">&ndash;</div>`}
          <div class="term-hero-caption">cases granted &amp; noted this term</div>
        </div>
        ${next ? `
        <div class="term-hero-stat term-hero-stat-sm">
          <a class="term-hero-value-sm" href="/questions-presented/${next.term}" data-link title="See the questions presented for ${escapeHtml(next.label)}">${next.total_granted}</a>
          <div class="term-hero-caption">granted so far for ${escapeHtml(next.label)}</div>
        </div>` : ""}
      </div>
      <div class="term-hero-hint">Click a number to see its questions presented &rarr;</div>
    </section>

    <div class="home-grid">
      <section class="home-card teal-card">
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
                ${item.kind === "opinion" ? activityMarks(item) : ""}
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

// ---------------------------------------------------- questions presented

async function renderQuestionsPresented(app, term) {
  app.innerHTML = `<a class="back-link" href="/" data-link>&larr; Back to Home</a>` + skeletonCards(4);

  let data;
  try {
    data = await api(`/api/questions-presented?term=${encodeURIComponent(term)}`);
  } catch (err) {
    app.innerHTML = `
      <a class="back-link" href="/" data-link>&larr; Back to Home</a>
      <div class="empty-state">Couldn't load questions presented (${escapeHtml(err.message)}).</div>`;
    return;
  }

  const label = data.label || otLabel(term);
  const totalGranted = data.total_granted;

  app.innerHTML = `
    <a class="back-link" href="/" data-link>&larr; Back to Home</a>
    <div class="qp-header">
      <h1>Questions Presented</h1>
      <div class="qp-subtitle">${escapeHtml(label)}${totalGranted != null ? ` &middot; ${totalGranted} cases granted &amp; noted` : ""}</div>
    </div>
    ${!data.items.length ? `
      <div class="empty-state">No questions presented fetched yet for this term &mdash; they fill in gradually after each refresh. Check back shortly.</div>
    ` : `
      <div class="qp-list">
        ${data.items.map((item) => `
          <article class="qp-card">
            <div class="qp-card-top">
              <span class="qp-docket">No. ${escapeHtml(item.docket)}</span>
              ${item.status_line ? `<span class="qp-status">${escapeHtml(item.status_line)}</span>` : ""}
            </div>
            <h3>${escapeHtml(titleCase(item.case_name || "Untitled case"))}</h3>
            <p>${escapeHtml(item.question_presented || "")}</p>
            ${item.decision_below ? `<div class="qp-meta">Decision below: ${escapeHtml(item.decision_below)}</div>` : ""}
          </article>
        `).join("")}
      </div>
    `}
  `;
}

// -------------------------------------------------------------- list view

function buildQuery(type) {
  const s = listState[type];
  const params = new URLSearchParams();
  params.set("limit", s.pageSize);
  params.set("offset", s.page * s.pageSize);
  if (s.search) params.set("q", s.search);
  if (type === "order") {
    if (s.term) params.set("term", s.term);
    if (s.orderType) params.set("order_type", s.orderType);
    if (s.notableOnly) params.set("notable", "true");
  } else {
    // "recent"/"term" scopes are enforced server-side (so pagination
    // counts stay correct); "past" hands off to the ordinary term filter.
    if (s.timeScope === "past") {
      if (s.term) params.set("term", s.term);
    } else {
      params.set("scope", s.timeScope);
    }
    if (s.justice) params.set("justice", s.justice);
    if (s.sort) params.set("sort", s.sort);
    if (s.hasDissent) params.set("has_dissent", "true");
  }
  return params.toString();
}

function activityMarks(o) {
  const bits = [];
  if (o.has_dissent) bits.push('<span class="badge badge-dissent">D</span>');
  if (o.has_concurrence) bits.push('<span class="badge badge-concur">C</span>');
  if (!bits.length) return "";
  return `<span class="activity-marks">${bits.join("")}</span>`;
}

// Per-Justice breakdown (who dissented/concurred, by name) when the API
// has it (vote_breakdown, from the Granted & Noted List); falls back to
// the coarser has_dissent/has_concurrence flags otherwise.
function voteChips(o) {
  const votes = o.vote_breakdown || [];
  const badges = [];
  if (o.is_revision) badges.push('<span class="badge badge-revision">Revised</span>');
  if (o.extraction_error) badges.push('<span class="badge">Text unavailable</span>');
  const author = o.author_name || o.justice;
  if (author) badges.push(`<span class="badge badge-majority">Maj. ${escapeHtml(author)}</span>`);
  const dissents = votes.filter((v) => v.has_dissent);
  const concurs = votes.filter((v) => v.has_concurrence);
  if (dissents.length) {
    badges.push(`<span class="badge badge-dissent">Dissent: ${escapeHtml(dissents.map((v) => v.author).join(", "))}</span>`);
  } else if (o.has_dissent) {
    badges.push('<span class="badge badge-dissent">Dissent</span>');
  }
  if (concurs.length) {
    badges.push(`<span class="badge badge-concur">Concur: ${escapeHtml(concurs.map((v) => v.author).join(", "))}</span>`);
  } else if (o.has_concurrence) {
    badges.push('<span class="badge badge-concur">Concurrence</span>');
  }
  return badges.join("");
}

// A small 9-pixel "bench" graphic: one square per seat on the Court,
// colored by how that seat voted. Built only from what the workflow
// already fetches (the majority author + the Granted & Noted List's
// concurrence/dissent breakdown) -- there's no roster of sitting
// Justices anywhere in this app to name the remaining seats, so any
// seat not otherwise accounted for is shown as a plain "joined in full"
// square rather than guessing who occupies it.
const BENCH_SIZE = 9;

function voteGraphic(o) {
  const author = o.author_name || o.justice;
  const votes = o.vote_breakdown || [];
  // A concurrence -- even "in the judgment" -- is still a vote for the
  // result, so it counts on the majority side of the split; only an
  // actual dissent counts against it.
  const dissents = votes.filter((v) => v.has_dissent);
  const concurs = votes.filter((v) => v.has_concurrence && !v.has_dissent);
  if (!author && !dissents.length && !concurs.length) return "";

  const majoritySeats = [];
  if (author) majoritySeats.push({ kind: "author", label: `Wrote for the Court: ${author}` });
  concurs.forEach((v) => majoritySeats.push({ kind: "concur", label: `Concurrence: ${v.author} (${v.label})` }));
  for (let i = majoritySeats.length + dissents.length; i < BENCH_SIZE; i++) {
    majoritySeats.push({ kind: "joined", label: "Joined the majority in full" });
  }
  const dissentSeats = dissents.map((v) => ({ kind: "dissent", label: `Dissent: ${v.author} (${v.label})` }));

  const renderPixels = (seats) =>
    seats
      .map((s) => `<span class="vote-pixel vote-pixel-${s.kind}" title="${escapeHtml(s.label)}"></span>`)
      .join("");

  return `
    <div class="vote-graphic" aria-label="Vote split: ${majoritySeats.length} to ${dissentSeats.length}">
      <span class="vote-split">${majoritySeats.length}&ndash;${dissentSeats.length}</span>
      <span class="vote-pixels">
        <span class="vote-pixel-group">${renderPixels(majoritySeats)}</span>${dissentSeats.length ? `<span class="vote-pixel-group vote-pixel-group-dissent">${renderPixels(dissentSeats)}</span>` : ""}
      </span>
    </div>`;
}

function opinionCard(o, index) {
  const snippet = o.summary || o.holding || "Open to read the syllabus.";
  const delay = Math.min(index, 12) * 25;
  return `
    <a class="item-card${o.has_dissent ? " notable-card" : ""}" data-link href="/opinion/${o.id}" style="animation-delay:${delay}ms">
      <div class="item-top">
        <div class="item-title">${escapeHtml(o.case_name)}</div>
        <div class="item-meta">${fmtDate(o.date)} &middot; No. ${escapeHtml(o.docket || "–")}</div>
      </div>
      <div class="item-badges">${voteChips(o)}</div>
      ${voteGraphic(o)}
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
  const [stats, termSummary] = await Promise.all([loadStats(), loadTermSummary()]);
  updateChrome(stats);

  const currentTerm = termSummary.current_term ? termSummary.current_term.term : null;
  const terms = stats.tracked_terms || [];

  if (type === "order" && !s.termInitialized) {
    // Orders default to the current term only -- old order lists don't
    // gain new entries once a term ends, so mixing them into the default
    // view would just be noise. Older terms stay one dropdown away.
    s.term = currentTerm || "";
    s.termInitialized = true;
  }

  const termOptions = '<option value="">All terms</option>' +
    terms.map((t) => `<option value="${t}" ${s.term === t ? "selected" : ""}>${otLabel(t)}</option>`).join("");
  const pastTermOptions = '<option value="">Choose a term&hellip;</option>' +
    terms.filter((t) => t !== currentTerm)
      .map((t) => `<option value="${t}" ${s.term === t ? "selected" : ""}>${otLabel(t)}</option>`).join("");

  app.innerHTML = `
    <nav class="tabs" role="tablist">
      <a class="tab ${type === "opinion" ? "active" : ""}" data-link href="/opinions" role="tab">Opinions</a>
      <a class="tab ${type === "order" ? "active" : ""}" data-link href="/orders" role="tab">Orders</a>
    </nav>

    ${type === "opinion" ? `
    <div class="scope-tabs" role="tablist" aria-label="Time range">
      <button class="scope-tab ${s.timeScope === "recent" ? "active" : ""}" data-scope="recent">Recent</button>
      <button class="scope-tab ${s.timeScope === "term" ? "active" : ""}" data-scope="term">This Term</button>
      <button class="scope-tab ${s.timeScope === "past" ? "active" : ""}" data-scope="past">Past Terms</button>
    </div>
    ` : ""}

    <section class="toolbar">
      <input id="searchInput" type="search" placeholder="Search case name, docket, holding&hellip;" value="${escapeHtml(s.search)}" />
      ${type === "order" ? `
        <select id="termFilter">${termOptions}</select>
        <select id="typeFilter">
          <option value="">All order types</option>
          <option value="Order List" ${s.orderType === "Order List" ? "selected" : ""}>Order List</option>
          <option value="Miscellaneous Order" ${s.orderType === "Miscellaneous Order" ? "selected" : ""}>Miscellaneous Order</option>
        </select>
        <label class="notable-toggle"><input type="checkbox" id="notableOnly" ${s.notableOnly ? "checked" : ""} /> Notable only</label>
      ` : `
        ${s.timeScope === "past" ? `<select id="termFilter">${pastTermOptions}</select>` : ""}
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

  // Present for orders always, but for opinions only in "Past Terms" scope.
  const termFilterEl = document.getElementById("termFilter");
  if (termFilterEl) {
    termFilterEl.addEventListener("change", (e) => {
      s.term = e.target.value;
      s.page = 0;
      loadListItems(type);
    });
  }

  if (type === "opinion") {
    document.querySelectorAll(".scope-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        s.timeScope = btn.dataset.scope;
        s.page = 0;
        renderList(el("app"), "opinion");
      });
    });
  }

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

function separateOpinionsHtml(data) {
  const votes = data.vote_breakdown || [];
  const raw = data.separate_opinions;
  if (!votes.length && !raw) return "";
  const badges = votes.length
    ? votes
        .map((v) => {
          const kind = v.has_dissent ? "badge-dissent" : "badge-concur";
          return `<span class="badge ${kind}">${escapeHtml(v.author)}: ${escapeHtml(v.label)}</span>`;
        })
        .join("")
    : `<span class="badge">${escapeHtml(raw)}</span>`;
  return `
    <h3>Concurrences &amp; Dissents</h3>
    <div class="item-badges">${badges}</div>
    <p class="legend">${DISSENT_CODE_LEGEND}</p>`;
}

// Truncates on a word/line boundary rather than mid-word, so a long
// syllabus or separate opinion shows a readable preview with a "Read
// more" link to its own full-text page instead of the whole thing
// dominating the case detail page.
function truncateText(text, limit) {
  if (!text) return { preview: "", truncated: false };
  if (text.length <= limit) return { preview: text, truncated: false };
  const cut = text.slice(0, limit);
  const breakAt = Math.max(cut.lastIndexOf("\n"), cut.lastIndexOf(" "));
  const preview = breakAt > limit * 0.6 ? cut.slice(0, breakAt) : cut;
  return { preview: preview.trim() + "…", truncated: true };
}

function separateOpinionTextsHtml(entries, opinionId) {
  if (!entries || !entries.length) return "";
  return entries
    .map((entry, position) => {
      const { preview, truncated } = truncateText(entry.text, 700);
      return `
        <div class="separate-opinion-card">
          <h3>${escapeHtml(entry.label)} &mdash; Justice ${escapeHtml(entry.author)}</h3>
          <p class="verbatim-text">${escapeHtml(preview)}</p>
          ${truncated ? `<a class="read-more" href="/opinion/${opinionId}/separate/${position}" data-link>Read full ${escapeHtml(entry.label.toLowerCase())} &rarr;</a>` : ""}
        </div>`;
    })
    .join("");
}

function summaryText(data, generating) {
  if (data.summary) return escapeHtml(data.summary);
  if (generating) {
    return data.type === "opinion"
      ? '<span class="generating">Reading the syllabus from the PDF…</span>'
      : '<span class="generating">Generating summary from the PDF…</span>';
  }
  if (data.extraction_error) {
    return "Could not read this PDF. Use the link below to open the official document.";
  }
  return "No summary available yet.";
}

function summaryHeading(data, generating) {
  if (data.type !== "opinion") return "Summary";
  // Default to "Syllabus" while generating -- almost every opinion has
  // one, and the heading corrects itself once the real data lands.
  return data.summary_is_syllabus || (generating && !data.summary) ? "Syllabus" : "Summary";
}

function renderSummaryPreview(data) {
  const { preview, truncated } = truncateText(data.summary, 900);
  const label = summaryHeading(data, false).toLowerCase();
  return `
    <p class="verbatim-text">${escapeHtml(preview)}</p>
    ${truncated ? `<a class="read-more" href="/opinion/${data.id}/syllabus" data-link>Read full ${label} &rarr;</a>` : ""}`;
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
          <div class="detail-badges">${voteChips(data)}</div>
          ${voteGraphic(data)}
          ${data.holding ? `<h3>Holding, at a glance</h3><p>${escapeHtml(data.holding)}</p>` : ""}
          <h3>${summaryHeading(data, generating)}</h3>
          ${data.summary ? renderSummaryPreview(data) : `<p>${summaryText(data, generating)}</p>`}
          ${data.disposition ? `<h3>Disposition</h3><p>${escapeHtml(data.disposition)}</p>` : ""}
          ${separateOpinionsHtml(data)}
          ${separateOpinionTextsHtml(data.separate_opinion_texts, data.id)}
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

async function renderOpinionFullText(app, id, kind, position) {
  app.innerHTML = detailSkeleton();
  let data;
  try {
    data = await api(`/api/opinions/${id}`);
  } catch (err) {
    app.innerHTML = `
      <a class="back-link" href="/opinion/${id}" data-link>&larr; Back</a>
      <div class="empty-state">Couldn't load this opinion (${escapeHtml(err.message)}).</div>`;
    return;
  }

  let heading, text;
  if (kind === "syllabus") {
    heading = summaryHeading(data, false);
    text = data.summary || "";
  } else {
    const entry = (data.separate_opinion_texts || [])[position];
    if (!entry) {
      app.innerHTML = `
        <a class="back-link" href="/opinion/${id}" data-link>&larr; Back to ${escapeHtml(data.case_name)}</a>
        <div class="empty-state">That opinion excerpt isn't available.</div>`;
      return;
    }
    heading = `${entry.label} — Justice ${entry.author}`;
    text = entry.text;
  }

  app.innerHTML = `
    <a class="back-link" href="/opinion/${id}" data-link>&larr; Back to ${escapeHtml(data.case_name)}</a>
    <article class="detail-page">
      <h1>${escapeHtml(data.case_name)}</h1>
      <div class="detail-meta">${fmtDate(data.date)} &middot; Docket No. ${escapeHtml(data.docket || "–")}</div>
      <h3>${escapeHtml(heading)}</h3>
      <p class="verbatim-text">${escapeHtml(text)}</p>
      <a class="pdf-link" href="${data.pdf_url}" target="_blank" rel="noopener">Read full opinion (PDF) &rarr;</a>
    </article>`;
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
  } else if (route.view === "qp") {
    await renderQuestionsPresented(app, route.term);
  } else if (route.view === "opinionFullText") {
    await renderOpinionFullText(app, route.id, route.kind, route.position);
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
