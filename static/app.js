const state = {
  tab: "opinions",
  page: 0,
  pageSize: 20,
  total: 0,
  search: "",
  term: "",
  orderType: "",
  justice: "",
  notableOnly: false,
};

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
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

async function loadStats() {
  const stats = await api("/api/stats");
  el("statOpinions").textContent = stats.total_opinions;
  el("statOrders").textContent = stats.total_orders;
  el("statNotable").textContent = stats.notable_orders;
  el("statPending").textContent = stats.pending_opinions + stats.pending_orders;

  const latest = [stats.latest_opinion_date, stats.latest_order_date]
    .filter(Boolean)
    .sort()
    .pop();
  el("statLatest").textContent = latest ? fmtDate(latest) : "–";

  const termSelect = el("termFilter");
  const currentValue = termSelect.value;
  const terms = stats.tracked_terms || [];
  termSelect.innerHTML = '<option value="">All terms</option>' +
    terms.map((t) => `<option value="${t}">OT ${2000 + parseInt(t, 10)}</option>`).join("");
  termSelect.value = currentValue;

  const justiceSelect = el("justiceFilter");
  const currentJustice = justiceSelect.value;
  const justices = stats.justices || [];
  justiceSelect.innerHTML = '<option value="">All authors</option>' +
    justices.map((j) => `<option value="${j}">${j}</option>`).join("");
  justiceSelect.value = currentJustice;

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
  if (stats.refresh_running) el("refreshBtn").textContent = "Refreshing…";
  else el("refreshBtn").textContent = "Refresh now";

  return stats;
}

function buildQuery() {
  const params = new URLSearchParams();
  params.set("limit", state.pageSize);
  params.set("offset", state.page * state.pageSize);
  if (state.search) params.set("q", state.search);
  if (state.term) params.set("term", state.term);
  if (state.tab === "orders") {
    if (state.orderType) params.set("order_type", state.orderType);
    if (state.notableOnly) params.set("notable", "true");
  } else {
    if (state.justice) params.set("justice", state.justice);
  }
  return params.toString();
}

function opinionCard(o, index) {
  const badges = [];
  if (o.is_revision) badges.push('<span class="badge badge-revision">Revised</span>');
  if (o.extraction_error) badges.push('<span class="badge">Text unavailable</span>');

  // The Court's own holding comes free from the listing page, so an
  // unsummarized opinion still reads well; the AI summary is the upgrade
  // you get on opening it.
  const snippet = o.summary || o.holding || "Open to generate a summary.";
  const delay = Math.min(index, 12) * 25;
  return `
    <article class="item-card" data-type="opinion" data-id="${o.id}" style="animation-delay:${delay}ms">
      <div class="item-top">
        <div class="item-title">${escapeHtml(o.case_name)}</div>
        <div class="item-meta">${fmtDate(o.date)} &middot; No. ${escapeHtml(o.docket || "–")}${o.citation ? " &middot; " + escapeHtml(o.citation) + " U.S." : ""}</div>
      </div>
      <div class="item-badges">${badges.join("")}</div>
      <div class="item-snippet">${escapeHtml(snippet).slice(0, 320)}${snippet.length > 320 ? "…" : ""}</div>
    </article>`;
}

function orderCard(o, index) {
  const badges = [`<span class="badge">${escapeHtml(o.order_type)}</span>`];
  if (o.notable) badges.push('<span class="badge badge-notable">Notable</span>');
  if (o.extraction_error) badges.push('<span class="badge">Text unavailable</span>');

  const snippet = o.summary || "Open to generate a summary.";
  const delay = Math.min(index, 12) * 25;
  return `
    <article class="item-card${o.notable ? " notable-card" : ""}" data-type="order" data-id="${o.id}" style="animation-delay:${delay}ms">
      <div class="item-top">
        <div class="item-title">${fmtDate(o.date)}</div>
      </div>
      <div class="item-badges">${badges.join("")}</div>
      <div class="item-snippet">${escapeHtml(snippet).slice(0, 320)}${snippet.length > 320 ? "…" : ""}</div>
    </article>`;
}

async function loadList() {
  const listContainer = el("listContainer");
  const endpoint = state.tab === "orders" ? "/api/orders" : "/api/opinions";
  const requestId = ++loadList._requestId;
  listContainer.innerHTML = skeletonCards(6);
  try {
    const data = await api(`${endpoint}?${buildQuery()}`);
    if (requestId !== loadList._requestId) return; // a newer request has since started
    state.total = data.total;
    if (!data.items.length) {
      listContainer.innerHTML = '<div class="empty-state">No results.</div>';
    } else {
      listContainer.innerHTML = data.items
        .map((item, i) => (state.tab === "orders" ? orderCard(item, i) : opinionCard(item, i)))
        .join("");
    }
    updatePager();
  } catch (err) {
    if (requestId !== loadList._requestId) return;
    listContainer.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}
loadList._requestId = 0;

function updatePager() {
  const start = state.total === 0 ? 0 : state.page * state.pageSize + 1;
  const end = Math.min(state.total, (state.page + 1) * state.pageSize);
  el("pageInfo").textContent = `${start}–${end} of ${state.total}`;
  el("prevPage").disabled = state.page === 0;
  el("nextPage").disabled = end >= state.total;
}

function detailSkeleton() {
  return `
    <div class="skeleton-line w-40" style="height:20px;margin-bottom:14px;"></div>
    <div class="skeleton-line w-25" style="margin-bottom:22px;"></div>
    <div class="skeleton-line w-100"></div>
    <div class="skeleton-line w-100"></div>
    <div class="skeleton-line w-70"></div>`;
}

async function openDetail(type, id) {
  const overlay = el("detailOverlay");
  const content = el("detailContent");
  overlay.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  content.innerHTML = detailSkeleton();

  const base = `/api/${type === "order" ? "orders" : "opinions"}/${id}`;
  let data = await api(base);

  // Summaries are generated lazily to keep memory use low, so the first
  // time anyone opens an older document we produce it now.
  if (!data.summary && !data.extraction_error) {
    render(data, true);
    try {
      const res = await fetch(`${base}/summarize`, { method: "POST" });
      if (res.ok) data = await res.json();
    } catch (err) {
      /* fall through and render whatever we have */
    }
  }
  render(data, false);

  function render(data, generating) {
  if (type === "opinion") {
    content.innerHTML = `
      <div class="detail-content">
        <h2>${escapeHtml(data.case_name)}</h2>
        <div class="detail-meta">
          ${fmtDate(data.date)} &middot; Docket No. ${escapeHtml(data.docket || "–")}
          ${data.justice ? " &middot; Author: " + escapeHtml(data.justice) : ""}
          ${data.citation ? " &middot; " + escapeHtml(data.citation) + " U.S." : ""}
        </div>
        ${data.holding ? `<h3>Holding (Court syllabus)</h3><p>${escapeHtml(data.holding)}</p>` : ""}
        <h3>Summary</h3>
        <p>${summaryText(data, generating)}</p>
        <a class="pdf-link" href="${data.pdf_url}" target="_blank" rel="noopener">Read full opinion (PDF) &rarr;</a>
      </div>`;
  } else {
    content.innerHTML = `
      <div class="detail-content">
        <h2>${escapeHtml(data.order_type)}</h2>
        <div class="detail-meta">${fmtDate(data.date)}${data.notable ? " &middot; Flagged notable" : ""}</div>
        <h3>Summary</h3>
        <p>${summaryText(data, generating)}</p>
        <a class="pdf-link" href="${data.pdf_url}" target="_blank" rel="noopener">Read full order (PDF) &rarr;</a>
      </div>`;
  }
  }
}

function summaryText(data, generating) {
  if (data.summary) return escapeHtml(data.summary);
  if (generating) return '<span class="generating">Generating summary from the PDF…</span>';
  if (data.extraction_error) {
    return "Could not read this PDF. Use the link below to open the official document.";
  }
  return "No summary available yet.";
}

function closeDetail() {
  el("detailOverlay").classList.add("hidden");
  document.body.style.overflow = "";
}

function setTab(tab) {
  state.tab = tab;
  state.page = 0;
  document.querySelectorAll(".tab").forEach((btn) => {
    const active = btn.dataset.tab === tab;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".hidden-tab-orders").forEach((elm) => elm.classList.toggle("hidden", tab === "orders"));
  document.querySelectorAll(".hidden-tab-opinions").forEach((elm) => elm.classList.toggle("hidden", tab === "opinions"));
  loadList();
}

let searchDebounce;
function wireEvents() {
  document.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.tab)));

  el("searchInput").addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      state.search = e.target.value.trim();
      state.page = 0;
      loadList();
    }, 300);
  });

  el("termFilter").addEventListener("change", (e) => {
    state.term = e.target.value;
    state.page = 0;
    loadList();
  });

  el("typeFilter").addEventListener("change", (e) => {
    state.orderType = e.target.value;
    state.page = 0;
    loadList();
  });

  el("justiceFilter").addEventListener("change", (e) => {
    state.justice = e.target.value;
    state.page = 0;
    loadList();
  });

  el("notableOnly").addEventListener("change", (e) => {
    state.notableOnly = e.target.checked;
    state.page = 0;
    loadList();
  });

  el("prevPage").addEventListener("click", () => {
    if (state.page > 0) {
      state.page -= 1;
      loadList();
    }
  });
  el("nextPage").addEventListener("click", () => {
    state.page += 1;
    loadList();
  });

  el("listContainer").addEventListener("click", (e) => {
    const card = e.target.closest(".item-card");
    if (!card) return;
    openDetail(card.dataset.type, card.dataset.id);
  });

  el("closeDetail").addEventListener("click", closeDetail);
  el("detailOverlay").addEventListener("click", (e) => {
    if (e.target.id === "detailOverlay") closeDetail();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDetail();
  });

  el("refreshBtn").addEventListener("click", async () => {
    el("refreshBtn").disabled = true;
    el("refreshBtn").textContent = "Refreshing…";
    await fetch("/api/refresh", { method: "POST" });
    pollUntilIdle();
  });
}

async function pollUntilIdle() {
  const stats = await loadStats();
  if (stats.refresh_running) {
    setTimeout(pollUntilIdle, 4000);
  } else {
    loadList();
  }
}

async function init() {
  initTheme();
  wireEvents();
  // setTab applies the per-tab filter visibility, so call it on load rather
  // than waiting for the first click -- otherwise every filter shows at once.
  setTab(state.tab);
  await loadStats();
  setInterval(loadStats, 30000);
}

init();
