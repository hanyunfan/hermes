// app.js — render the WC 2026 daily preview with filters
// Pure ES2022, no build step, no dependencies. Caches the JSON in
// sessionStorage; filter state persists in localStorage and URL hash.

(() => {
  "use strict";

  const JSON_URL = "data/matches.json";
  const CACHE_KEY = "wc2026.matches.v2";
  const FILTER_KEY = "wc2026.filters.v3";
  const TZ_KEY = "wc2026.tz.v1";
  const REFRESH_INTERVAL_MS = 5 * 60 * 1000;   // 5 min between cron hits
  const REFRESH_LIVE_MS    = 30 * 1000;       // 30 s while any match is LIVE
  const RERENDER_TICK_MS   = 60 * 1000;       // re-render countdowns every 1 min

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ────────────────────────────────────────────────────────────
  // Data loading
  // ────────────────────────────────────────────────────────────
  async function loadMatches(force = false) {
    if (!force) {
      const cached = readCache();
      if (cached) return cached;
    }
    const res = await fetch(`${JSON_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    writeCache(data);
    return data;
  }

  function readCache() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const { at, data } = JSON.parse(raw);
      if (Date.now() - at > 60 * 1000) return null; // 1 min soft TTL
      return data;
    } catch {
      return null;
    }
  }

  function writeCache(data) {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), data }));
    } catch {
      /* private mode / quota — fine */
    }
  }

  // ────────────────────────────────────────────────────────────
  // Time helpers
  // ────────────────────────────────────────────────────────────
  function localTimezone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "local"; }
    catch { return "local"; }
  }
  function formatRelative(target, now) {
    const diffMs = target.getTime() - now.getTime();
    const abs = Math.abs(diffMs);
    const past = diffMs < 0;
    const minute = 60_000, hour = 3_600_000, day = 86_400_000;
    let label;
    if (abs < minute) label = "less than a minute";
    else if (abs < hour) label = `${Math.round(abs / minute)}m`;
    else if (abs < day) label = `${Math.round(abs / hour)}h`;
    else label = `${Math.round(abs / day)}d`;
    return past ? `${label} ago` : `in ${label}`;
  }
  function nowInZone(tzName) {
    if (!tzName) return new Date();
    try {
      const localStr = new Date().toLocaleString("en-US", { timeZone: tzName });
      return new Date(localStr);
    } catch { return new Date(); }
  }

  // ────────────────────────────────────────────────────────────
  // Display-timezone state (user override; falls back to local)
  // ────────────────────────────────────────────────────────────
  // Curated list shown in the picker. Empty string = "Local (auto)".
  const TZ_OPTIONS = [
    { value: "",                       label: "Local (auto)",       group: "Auto" },
    { value: "America/Los_Angeles",    label: "Los Angeles · PT",    group: "Tournament venues" },
    { value: "America/Denver",         label: "Denver · MT",         group: "Tournament venues" },
    { value: "America/Chicago",        label: "Chicago · CT",        group: "Tournament venues" },
    { value: "America/New_York",       label: "New York · ET",       group: "Tournament venues" },
    { value: "America/Toronto",        label: "Toronto · ET",        group: "Tournament venues" },
    { value: "America/Mexico_City",    label: "Mexico City · CT (MX)", group: "Tournament venues" },
    { value: "Europe/London",          label: "London · GMT/BST",    group: "International" },
    { value: "Europe/Berlin",          label: "Berlin · CET/CEST",   group: "International" },
    { value: "Asia/Shanghai",          label: "Shanghai · CST",      group: "International" },
    { value: "Asia/Tokyo",             label: "Tokyo · JST",         group: "International" },
    { value: "Australia/Sydney",       label: "Sydney · AEST/AEDT",  group: "International" },
  ];

  let selectedTz = null;     // null = use local (auto)
  let allTimezones = null;   // Intl.supportedValuesOf("timeZone") if available

  function loadTz() {
    try {
      const raw = localStorage.getItem(TZ_KEY);
      if (!raw) return null;
      const tz = JSON.parse(raw);
      return typeof tz === "string" ? tz : null;
    } catch { return null; }
  }
  function saveTz(tz) {
    try { localStorage.setItem(TZ_KEY, JSON.stringify(tz || "")); } catch { /* ignore */ }
  }
  function currentTz() {
    // User override wins; otherwise the data's TZ (always America/Chicago
    // from the cron) for consistency with the data's pre-baked fields.
    // We still let "Local" through when the user hasn't picked anything,
    // which is the default UX.
    return selectedTz || localTimezone();
  }
  function isLocalTz() { return !selectedTz; }

  // Format a Date as "YYYY-MM-DD" in the given IANA zone (or local if null/empty).
  function dateInTz(date, tz) {
    if (!tz) return date.toISOString().slice(0, 10);
    try {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
      }).formatToParts(date);
      const get = (t) => parts.find((p) => p.type === t)?.value;
      return `${get("year")}-${get("month")}-${get("day")}`;
    } catch { return date.toISOString().slice(0, 10); }
  }
  function timeInTz(date, tz) {
    if (!tz) return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    try {
      return new Intl.DateTimeFormat(undefined, {
        timeZone: tz, hour: "numeric", minute: "2-digit",
      }).format(date);
    } catch { return date.toLocaleTimeString(); }
  }
  function weekdayInTz(date, tz) {
    if (!tz) return new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(date);
    try {
      return new Intl.DateTimeFormat(undefined, { timeZone: tz, weekday: "short" }).format(date);
    } catch { return ""; }
  }
  // Friendly short offset like "UTC-5" or "UTC+9:30" computed for *now*.
  function offsetLabel(tz) {
    if (!tz) {
      const m = -new Date().getTimezoneOffset();
      const sign = m >= 0 ? "+" : "−";
      const abs = Math.abs(m);
      return `UTC${sign}${Math.floor(abs / 60)}${abs % 60 ? `:${String(abs % 60).padStart(2, "0")}` : ""}`;
    }
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: tz, timeZoneName: "shortOffset",
      }).formatToParts(new Date());
      const off = parts.find((p) => p.type === "timeZoneName")?.value || "";
      return off.replace("GMT", "UTC");
    } catch { return ""; }
  }
  // The friendly label for the current selection, used in the pill.
  function currentTzLabel() {
    if (isLocalTz()) {
      const browser = localTimezone();
      return `Local · ${browser} · ${offsetLabel("")}`;
    }
    const opt = TZ_OPTIONS.find((o) => o.value === selectedTz);
    return opt ? opt.label : `${selectedTz} · ${offsetLabel(selectedTz)}`;
  }

  // ────────────────────────────────────────────────────────────
  // Filter state
  // ────────────────────────────────────────────────────────────
  const DEFAULT_FILTERS = Object.freeze({
    range: "3d",     // today | past | 3d | 7d | all
    status: "any",   // any | upcoming | live | final
    teams: [],       // [teamId, ...]
    venues: [],      // [venueName, ...]
  });

  let filters = { ...DEFAULT_FILTERS };
  let allData = null;
  let allMatches = []; // flattened

  function loadFilters() {
    // URL hash takes precedence, then localStorage, then defaults.
    const fromHash = readFiltersFromHash();
    if (fromHash) return normalizeFilters(fromHash);
    try {
      const raw = localStorage.getItem(FILTER_KEY);
      if (raw) return normalizeFilters(JSON.parse(raw));
    } catch { /* ignore */ }
    return { ...DEFAULT_FILTERS };
  }

  function saveFilters() {
    try { localStorage.setItem(FILTER_KEY, JSON.stringify(filters)); } catch { /* ignore */ }
    writeFiltersToHash();
  }

  function normalizeFilters(f) {
    const out = { ...DEFAULT_FILTERS, ...f };
    out.range = ["today", "past", "3d", "7d", "all"].includes(out.range) ? out.range : "3d";
    out.status = ["any", "upcoming", "live", "final"].includes(out.status) ? out.status : "any";
    out.teams = Array.isArray(out.teams) ? out.teams.slice(0, 8) : [];
    out.venues = Array.isArray(out.venues) ? out.venues.slice(0, 16) : [];
    return out;
  }

  function readFiltersFromHash() {
    if (!location.hash || location.hash.length < 2) return null;
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      const r = params.get("r");
      const s = params.get("s");
      const t = params.get("t");
      const v = params.get("v");
      if (!r && !s && !t && !v) return null;
      return {
        range: r || DEFAULT_FILTERS.range,
        status: s || DEFAULT_FILTERS.status,
        teams: t ? t.split(",").filter(Boolean) : [],
        venues: v ? v.split(",").filter(Boolean) : [],
      };
    } catch { return null; }
  }

  function writeFiltersToHash() {
    const params = new URLSearchParams();
    if (filters.range !== DEFAULT_FILTERS.range) params.set("r", filters.range);
    if (filters.status !== DEFAULT_FILTERS.status) params.set("s", filters.status);
    if (filters.teams.length) params.set("t", filters.teams.join(","));
    if (filters.venues.length) params.set("v", filters.venues.join(","));
    const newHash = params.toString();
    const target = newHash ? `#${newHash}` : " ";
    if (location.hash !== target) {
      history.replaceState(null, "", target);
    }
  }

  function isDefaultFilters() {
    return (
      filters.range === DEFAULT_FILTERS.range &&
      filters.status === DEFAULT_FILTERS.status &&
      filters.teams.length === 0 &&
      filters.venues.length === 0
    );
  }

  // ────────────────────────────────────────────────────────────
  // Filtering
  // ────────────────────────────────────────────────────────────
  function applyFilters() {
    if (!allData) return [];
    // Use the user's display TZ for the "today" reference so that
    // selecting a TZ on the other side of the world reshuffles which
    // matches fall into "today" / "tomorrow" / the 3d / 7d windows.
    const tz = currentTz();
    const now = nowInZone(tz);
    const todayIso = dateInTz(new Date(), tz);

    // Compute the date window from the range filter.
    let windowStart, windowEnd;
    if (filters.range === "today") {
      windowStart = windowEnd = todayIso;
    } else if (filters.range === "past") {
      // Everything from the start of the tournament up to (and
      // including) yesterday, in the display TZ. Today is excluded
      // so the user can quickly jump back to "what's already
      // happened" without seeing today's games twice.
      windowStart = allData.tournament.start;
      windowEnd = addDays(todayIso, -1);
    } else if (filters.range === "3d") {
      windowStart = todayIso;
      windowEnd = addDays(todayIso, 2);
    } else if (filters.range === "7d") {
      windowStart = todayIso;
      windowEnd = addDays(todayIso, 6);
    } else {
      windowStart = allData.tournament.start;
      windowEnd = allData.tournament.end;
    }

    const out = [];
    for (const m of allMatches) {
      // Bucket the match by its local date in the *display* TZ.
      const mDate = dateInTz(new Date(m.kickoff_utc), tz);
      if (mDate < windowStart || mDate > windowEnd) continue;

      // Status
      if (filters.status !== "any") {
        const live = m.status === "LIVE";
        const fin = m.status === "FINAL";
        // For SCHEDULED, decide upcoming vs based on kickoff vs now
        let s = m.status;
        if (s === "SCHEDULED" && new Date(m.kickoff_utc) <= now) s = "LIVE";
        if (filters.status === "upcoming" && !(s === "SCHEDULED")) continue;
        if (filters.status === "live" && !live && s !== "LIVE") continue;
        if (filters.status === "final" && !fin) continue;
      }

      if (filters.teams.length) {
        const homeId = String(m.home.id), awayId = String(m.away.id);
        if (!filters.teams.includes(homeId) && !filters.teams.includes(awayId)) continue;
      }

      if (filters.venues.length) {
        if (!filters.venues.includes(m.venue.name)) continue;
      }

      out.push(m);
    }
    return out;
  }

  function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  // ────────────────────────────────────────────────────────────
  // Render
  // ────────────────────────────────────────────────────────────
  function renderHeader(data) {
    updateTzPill();

    const tour = data.tournament || {};
    if (tour.edition) $("#tournament-edition").textContent = `${tour.edition} edition`;
    if (tour.dates || tour.host) {
      $("#tournament-subtitle").textContent =
        [tour.dates, tour.host].filter(Boolean).join(" · ");
    }

    const updatedAt = new Date(data.generated_at);
    $("#updated").textContent = `Updated ${formatRelative(updatedAt, new Date())}`;
    $("#updated").title = updatedAt.toLocaleString();
  }

  function renderMatches(matches) {
    const content = $("#content");
    content.innerHTML = "";

    if (!allData) return;

    if (matches.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.innerHTML = isDefaultFilters()
        ? `<strong>No matches in this window.</strong><div class="empty-hint">Try a wider time range or clear your filters.</div>`
        : `<strong>No matches match these filters.</strong><div class="empty-hint">Try widening the time range or clearing filters.</div>`;
      content.appendChild(empty);
      $("#result-count").textContent = `0 matches`;
      return;
    }

    // Group by the match's local date in the *display* TZ.
    const tz = currentTz();
    const byDate = new Map();
    for (const m of matches) {
      const mDate = dateInTz(new Date(m.kickoff_utc), tz);
      if (!byDate.has(mDate)) byDate.set(mDate, []);
      byDate.get(mDate).push(m);
    }

    const dayTemplate = $("#day-template");
    const matchTemplate = $("#match-template");
    const todayIso = dateInTz(new Date(), tz);
    const tomorrowIso = addDays(todayIso, 1);

    for (const [date, items] of [...byDate.entries()].sort()) {
      items.sort((a, b) => a.kickoff_utc < b.kickoff_utc ? -1 : 1);
      const section = dayTemplate.content.firstElementChild.cloneNode(true);
      section.classList.add(`is-${dayClass(date, todayIso, tomorrowIso)}`);
      $(".day-title", section).textContent = dayTitle(date, todayIso, tomorrowIso);
      $(".day-count", section).textContent = items.length === 1
        ? "1 match"
        : `${items.length} matches`;

      const list = $(".matches", section);
      for (const m of items) list.appendChild(renderMatch(m, matchTemplate));
      content.appendChild(section);
    }

    $("#result-count").textContent = matches.length === 1
      ? "1 match"
      : `${matches.length} matches`;
  }

  function dayClass(date, todayIso, tomorrowIso) {
    if (date === todayIso) return "today";
    if (date === tomorrowIso) return "tomorrow";
    return "other";
  }
  function dayTitle(date, todayIso, tomorrowIso) {
    if (date === todayIso) return `Today · ${friendlyDate(date)}`;
    if (date === tomorrowIso) return `Tomorrow · ${friendlyDate(date)}`;
    return friendlyDate(date);
  }
  function friendlyDate(iso) {
    try {
      return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
        weekday: "long", month: "short", day: "numeric",
      });
    } catch { return iso; }
  }

  function renderMatch(m, tpl) {
    const li = tpl.content.firstElementChild.cloneNode(true);
    if (m.status === "LIVE") li.classList.add("is-live");
    if (m.status === "FINAL") li.classList.add("is-final");

    // Compute the time + weekday + date in the *display* TZ. The
    // server-pre-baked `kickoff_time` / `kickoff_local_date` are in
    // America/Chicago (the data's TZ), so we re-render from `kickoff_utc`
    // when the display TZ differs.
    const tz = currentTz();
    const kickoff = new Date(m.kickoff_utc);
    const viewTime = isLocalTz() && tz === (allData?.timezone || localTimezone())
      ? (m.kickoff_time || timeInTz(kickoff, tz))
      : timeInTz(kickoff, tz);
    $(".time-main", li).textContent = viewTime;
    $(".time-main", li).title = `${weekdayInTz(kickoff, tz)} · ${dateInTz(kickoff, tz)} ${viewTime} (${tz})`;

    const statusEl = $(".time-status", li);
    if (m.status === "LIVE") {
      statusEl.textContent = m.status_short || "LIVE";
      statusEl.classList.add("is-live");
    } else if (m.status === "FINAL") {
      statusEl.textContent = m.status_short || "Final";
      statusEl.classList.add("is-final");
    } else {
      const kickoff = new Date(m.kickoff_utc);
      const now = nowInZone(tz);
      const diffMs = kickoff.getTime() - now.getTime();
      if (diffMs <= 0) {
        statusEl.textContent = "Starting soon";
        statusEl.title = "Auto-refresh in a moment…";
        triggerBackgroundRefresh();
      } else {
        statusEl.textContent = formatRelative(kickoff, now);
        statusEl.title = kickoff.toLocaleString(undefined, { timeZone: tz });
      }
    }

    populateTeam(li, ".home", m.home, m);
    populateTeam(li, ".away", m.away, m);

    $(".stage", li).textContent = m.stage || "World Cup";
    const venueText = m.venue?.name
      ? `${m.venue.name}${m.venue.city ? `, ${m.venue.city}` : ""}`
      : "—";
    const venueEl = $(".venue", li);
    venueEl.textContent = venueText;
    venueEl.title = m.venue?.name
      ? `${m.venue.name}${m.venue.city ? `, ${m.venue.city}` : ""}${m.venue.country ? `, ${m.venue.country}` : ""}`
      : "";

    const bc = (m.broadcasts || []).filter(Boolean);
    $(".broadcasts", li).textContent = bc.length ? bc.join(" · ") : "—";

    $(".link.espn", li).href = m.espn_url || "#";
    $(".link.fox", li).href = m.fox_url || "https://www.foxsports.com/soccer";

    return li;
  }

  function populateTeam(li, sel, team, match) {
    const root = $(sel, li);
    if (!root || !team) return;
    $(".team-flag", root).textContent = team.flag || "🏳️";
    const nameEl = $(".team-name", root);
    nameEl.textContent = team.name || "?";
    nameEl.title = team.name || "";
    const scoreEl = $(".team-score", root);
    if (match.status === "FINAL" || match.status === "LIVE") {
      scoreEl.textContent = team.score ?? "0";
    } else {
      scoreEl.textContent = "";
    }
    if (team.winner === true) root.classList.add("is-winner");
  }

  // ────────────────────────────────────────────────────────────
  // Filter UI wiring
  // ────────────────────────────────────────────────────────────
  function setPillActive(group, value) {
    const root = document.querySelector(`.filter-group[data-filter="${group}"] .pills`);
    if (!root) return;
    for (const btn of $$(".pill", root)) {
      const isActive = btn.dataset.value === value;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-checked", isActive ? "true" : "false");
    }
  }

  function wirePills() {
    for (const group of $$(".filter-group[data-filter]")) {
      const key = group.dataset.filter;
      if (key !== "range" && key !== "status") continue;
      for (const btn of $$(".pill", group)) {
        btn.addEventListener("click", () => {
          filters[key] = btn.dataset.value;
          setPillActive(key, filters[key]);
          onFilterChange();
        });
      }
    }
  }

  function setInitialPills() {
    setPillActive("range", filters.range);
    setPillActive("status", filters.status);
  }

  // ────────────────────────────────────────────────────────────
  // Timezone picker UI
  // ────────────────────────────────────────────────────────────
  function updateTzPill() {
    const label = $("#tz-pill-label");
    const pill = $("#tz-pill");
    if (!label || !pill) return;
    label.textContent = `Times in ${currentTzLabel()}`;
    pill.classList.toggle("is-local", isLocalTz());
  }

  function populateTzMenu() {
    const ul = $("#tz-menu");
    if (!ul) return;
    ul.innerHTML = "";
    let lastGroup = null;
    for (const opt of TZ_OPTIONS) {
      if (opt.group && opt.group !== lastGroup) {
        const h = document.createElement("li");
        h.className = "tz-group-label";
        h.setAttribute("role", "presentation");
        h.textContent = opt.group;
        ul.appendChild(h);
        lastGroup = opt.group;
      }
      const li = document.createElement("li");
      li.className = "tz-option";
      li.setAttribute("role", "option");
      li.dataset.value = opt.value;
      const isSel = (opt.value === "" && isLocalTz()) || (opt.value === selectedTz);
      li.setAttribute("aria-selected", isSel ? "true" : "false");
      li.tabIndex = 0;
      const off = opt.value ? offsetLabel(opt.value) : offsetLabel("");
      li.innerHTML = `
        <span class="tz-name">${escapeHtml(opt.label)}</span>
        <span class="tz-offset">${escapeHtml(off)}</span>
      `;
      li.addEventListener("click", () => {
        setTz(opt.value || null);
        closeTzMenu();
      });
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setTz(opt.value || null);
          closeTzMenu();
        } else if (e.key === "Escape") {
          closeTzMenu();
          $("#tz-pill")?.focus();
        }
      });
      ul.appendChild(li);
    }
  }

  function openTzMenu() {
    const menu = $("#tz-menu");
    const pill = $("#tz-pill");
    if (!menu || !pill) return;
    menu.hidden = false;
    pill.setAttribute("aria-expanded", "true");
    // Focus the currently selected option for keyboard users.
    const sel = menu.querySelector('.tz-option[aria-selected="true"]') || menu.querySelector(".tz-option");
    if (sel) sel.focus();
  }
  function closeTzMenu() {
    const menu = $("#tz-menu");
    const pill = $("#tz-pill");
    if (!menu || !pill) return;
    menu.hidden = true;
    pill.setAttribute("aria-expanded", "false");
  }
  function toggleTzMenu() {
    const menu = $("#tz-menu");
    if (!menu) return;
    if (menu.hidden) openTzMenu();
    else closeTzMenu();
  }

  function setTz(tz) {
    selectedTz = tz || null;
    saveTz(selectedTz);
    updateTzPill();
    populateTzMenu();
    if (allData) {
      const matches = applyFilters();
      renderMatches(matches);
      renderHeader(allData);
    }
  }

  function wireTzPicker() {
    const pill = $("#tz-pill");
    if (!pill) return;
    pill.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleTzMenu();
    });
    pill.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
        e.preventDefault();
        openTzMenu();
      }
    });
    // Click outside / Escape closes the menu.
    document.addEventListener("click", (e) => {
      const menu = $("#tz-menu");
      if (!menu || menu.hidden) return;
      if (e.target.closest("#tz-picker")) return;
      closeTzMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeTzMenu();
    });
  }

  // Team combobox
  function buildTeamList() {
    const ul = $("#team-options");
    ul.innerHTML = "";
    const teams = allData?.facets?.teams || [];
    // Sort: favorites (selected) first, then alphabetical.
    const sel = new Set(filters.teams);
    const sorted = [...teams].sort((a, b) => {
      const aSel = sel.has(String(a.id)) ? 0 : 1;
      const bSel = sel.has(String(b.id)) ? 0 : 1;
      if (aSel !== bSel) return aSel - bSel;
      return a.name.localeCompare(b.name);
    });
    if (sorted.length === 0) {
      const li = document.createElement("li");
      li.className = "combo-empty";
      li.textContent = "No teams available";
      ul.appendChild(li);
      return;
    }
    for (const t of sorted) {
      const li = document.createElement("li");
      li.className = "combo-option";
      li.setAttribute("role", "option");
      li.dataset.value = String(t.id);
      const isSel = sel.has(String(t.id));
      li.setAttribute("aria-selected", isSel ? "true" : "false");
      li.innerHTML = `
        <span class="opt-flag">${t.flag || "🏳️"}</span>
        <span class="opt-name">${escapeHtml(t.name)}</span>
        <span class="opt-meta">${escapeHtml(t.abbr || "")}</span>
      `;
      li.addEventListener("click", () => toggleTeam(String(t.id)));
      ul.appendChild(li);
    }
  }

  function renderTeamChips() {
    const wrap = $("#team-chips");
    wrap.innerHTML = "";
    const sel = new Set(filters.teams);
    const teams = allData?.facets?.teams || [];
    const lookup = new Map(teams.map((t) => [String(t.id), t]));
    for (const id of filters.teams) {
      const t = lookup.get(id);
      if (!t) continue;
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = `${t.flag || "🏳️"} ${escapeHtml(t.short || t.name)} <button type="button" aria-label="Remove ${escapeHtml(t.name)}">×</button>`;
      chip.querySelector("button").addEventListener("click", () => toggleTeam(id));
      wrap.appendChild(chip);
    }
    void sel;
  }

  function toggleTeam(id) {
    const idx = filters.teams.indexOf(id);
    if (idx >= 0) filters.teams.splice(idx, 1);
    else if (filters.teams.length < 8) filters.teams.push(id);
    renderTeamChips();
    buildTeamList();
    onFilterChange();
  }

  function filterTeamOptions(query) {
    const ul = $("#team-options");
    const q = query.trim().toLowerCase();
    let visible = 0;
    for (const li of $$(".combo-option", ul)) {
      const text = li.textContent.toLowerCase();
      const hit = !q || text.includes(q);
      li.style.display = hit ? "" : "none";
      if (hit) visible++;
    }
    ul.querySelector(".combo-empty")?.remove();
    if (visible === 0) {
      const li = document.createElement("li");
      li.className = "combo-empty";
      li.textContent = q ? `No teams matching “${query}”` : "No teams available";
      ul.appendChild(li);
    }
  }

  function wireTeamCombo() {
    const input = $("#team-search");
    const caret = input.parentElement.querySelector(".combo-caret");
    const options = $("#team-options");

    function open() { options.hidden = false; caret.setAttribute("aria-expanded", "true"); }
    function close() { options.hidden = true; caret.setAttribute("aria-expanded", "false"); }
    function isOpen() { return !options.hidden; }

    input.addEventListener("focus", () => { open(); filterTeamOptions(input.value); });
    input.addEventListener("input", () => { open(); filterTeamOptions(input.value); });
    caret.addEventListener("click", () => { isOpen() ? close() : (input.focus(), open()); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const first = $$(".combo-option", options).find((li) => li.style.display !== "none");
        if (first) toggleTeam(first.dataset.value);
      } else if (e.key === "Backspace" && input.value === "" && filters.teams.length) {
        filters.teams.pop();
        renderTeamChips();
        buildTeamList();
        onFilterChange();
      } else if (e.key === "Escape") {
        close();
        input.blur();
      }
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".combo--teams")) close();
    });
  }

  // Venue dropdown
  function buildVenueList() {
    const ul = $("#venue-options");
    ul.innerHTML = "";
    const venues = allData?.facets?.venues || [];
    if (venues.length === 0) {
      const li = document.createElement("li");
      li.className = "combo-empty";
      li.textContent = "No venues available";
      ul.appendChild(li);
      return;
    }
    for (const v of venues) {
      const li = document.createElement("li");
      li.className = "combo-option";
      li.setAttribute("role", "option");
      li.dataset.value = v.name;
      const isSel = filters.venues.includes(v.name);
      li.setAttribute("aria-selected", isSel ? "true" : "false");
      li.innerHTML = `
        <input type="checkbox" ${isSel ? "checked" : ""} tabindex="-1" />
        <div style="display:flex; flex-direction:column; min-width:0;">
          <span class="opt-name">${escapeHtml(v.name)}</span>
          <span class="opt-meta" style="margin-left:0;">${escapeHtml([v.city, v.country].filter(Boolean).join(", "))} · ${v.match_count} matches</span>
        </div>
      `;
      li.addEventListener("click", (e) => {
        if (e.target.tagName !== "INPUT") {
          const cb = li.querySelector("input");
          cb.checked = !cb.checked;
        }
        toggleVenue(v.name);
      });
      ul.appendChild(li);
    }
  }

  function updateVenueTrigger() {
    const total = allData?.facets?.venues?.length || 0;
    const label = $("#venue-trigger-label");
    if (filters.venues.length === 0) {
      label.textContent = total === 1 ? `All ${total} venue` : `All ${total} venues`;
    } else if (filters.venues.length === 1) {
      label.textContent = filters.venues[0];
    } else {
      label.textContent = `${filters.venues.length} venues selected`;
    }
  }

  function toggleVenue(name) {
    const idx = filters.venues.indexOf(name);
    if (idx >= 0) filters.venues.splice(idx, 1);
    else filters.venues.push(name);
    updateVenueTrigger();
    buildVenueList();
    onFilterChange();
  }

  function wireVenueCombo() {
    const trigger = $("#venue-trigger");
    const options = $("#venue-options");
    function open() { options.hidden = false; trigger.setAttribute("aria-expanded", "true"); }
    function close() { options.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      if (options.hidden) open(); else close();
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".combo--venues")) close();
    });
  }

  function wireClear() {
    const btn = $("#clear-btn");
    btn.addEventListener("click", () => {
      filters = { ...DEFAULT_FILTERS };
      setInitialPills();
      renderTeamChips();
      buildTeamList();
      buildVenueList();
      updateVenueTrigger();
      onFilterChange();
    });
  }

  function refreshClearVisibility() {
    $("#clear-btn").hidden = isDefaultFilters();
  }

  // ────────────────────────────────────────────────────────────
  // Central filter change handler
  // ────────────────────────────────────────────────────────────
  function onFilterChange() {
    saveFilters();
    refreshClearVisibility();
    const matches = applyFilters();
    renderMatches(matches);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
    );
  }

  // ────────────────────────────────────────────────────────────
  // Boot
  // ────────────────────────────────────────────────────────────
  let backgroundRefreshScheduled = false;
  function triggerBackgroundRefresh() {
    if (backgroundRefreshScheduled) return;
    backgroundRefreshScheduled = true;
    setTimeout(async () => {
      try {
        const data = await loadMatches(true);
        initFromData(data);
      } catch { /* keep last render */ }
      finally { backgroundRefreshScheduled = false; }
    }, 15_000);
  }

  function initFromData(data) {
    allData = data;
    // Flatten matches
    allMatches = [];
    for (const day of data.days || []) {
      for (const m of day.matches) allMatches.push(m);
    }
    renderHeader(data);
    buildTeamList();
    buildVenueList();
    updateVenueTrigger();
    renderTeamChips();
    onFilterChange();
  }

  async function boot() {
    filters = loadFilters();
    selectedTz = loadTz();
    setInitialPills();
    wirePills();
    wireTzPicker();
    populateTzMenu();
    updateTzPill();
    wireTeamCombo();
    wireVenueCombo();
    wireClear();
    renderTeamChips();

    $("#refresh-btn").addEventListener("click", async () => {
      const btn = $("#refresh-btn");
      btn.classList.add("spinning");
      try {
        const data = await loadMatches(true);
        initFromData(data);
      } catch (e) {
        showError(e);
      } finally {
        setTimeout(() => btn.classList.remove("spinning"), 400);
      }
    });

    try {
      const data = await loadMatches();
      initFromData(data);
    } catch (e) {
      const cached = readCache();
      if (cached) initFromData(cached);
      else showError(e);
    }

    // Self-rescheduling refresh. While any match is LIVE we poll
    // every 30 s so a goal / score change shows up fast; otherwise we
    // settle back to the 5-min baseline (the cron covers catch-up
    // for users who don't have the page open).
    function scheduleRefresh() {
      const hasLive = allMatches.some((m) => m.status === "LIVE");
      const delay = hasLive ? REFRESH_LIVE_MS : REFRESH_INTERVAL_MS;
      setTimeout(async () => {
        try {
          const data = await loadMatches(true);
          initFromData(data);
        } catch { /* keep last render */ }
        scheduleRefresh();
      }, delay);
    }
    scheduleRefresh();

    // Re-render every minute so relative countdowns stay fresh.
    setInterval(() => {
      if (allData) {
        const matches = applyFilters();
        renderMatches(matches);
        renderHeader(allData);
      }
    }, RERENDER_TICK_MS);
  }

  function showError(err) {
    const content = $("#content");
    content.innerHTML = "";
    const div = document.createElement("div");
    div.className = "error";
    div.innerHTML = `<strong>Couldn't load match data.</strong><br />${escapeHtml(String(err))}<br /><br />Try the refresh button.`;
    content.appendChild(div);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
