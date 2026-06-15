// app.js — render the WC 2026 daily preview with filters
// Pure ES2022, no build step, no dependencies. Caches the JSON in
// sessionStorage. Filter state is session-only — refresh always
// returns to DEFAULT_FILTERS (no localStorage / URL-hash write).
// Default view: past + today + next 3 days, in 3 columns.

(() => {
  "use strict";

  const JSON_URL = "data/matches.json";
  const CACHE_KEY = "wc2026.matches.v2";
  const TZ_KEY = "wc2026.tz.v1";
  const LANG_KEY = "wc2026.lang.v1";
  const VIEW_KEY = "wc2026.view.v1";
  const REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  const REFRESH_LIVE_MS    = 30 * 1000;
  const RERENDER_TICK_MS   = 60 * 1000;

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ────────────────────────────────────────────────────────────
  // i18n — EN / 中文
  // ────────────────────────────────────────────────────────────
  const I18N = {
    en: {
      "page.title": "FIFA World Cup 2026 — Daily Preview",
      "tournament.edition": "23rd edition",
      "tournament.dates": "Jun 11 – Jul 19, 2026 · USA · Canada · Mexico",
      "view.label": "View",
      "view.matches": "Matches",
      "view.standings": "Standings",
      "filter.time": "Time",
      "filter.status": "Status",
      "filter.teams": "Teams",
      "filter.venues": "Venues",
      "filter.lang": "Language",
      "range.butterfly": "Overview",
      "range.today": "Today",
      "range.past": "Past",
      "range.3d": "Next 3 days",
      "range.7d": "Next 7 days",
      "range.all": "All 104",
      "status.any": "Any",
      "status.upcoming": "Upcoming",
      "status.live": "Live",
      "status.final": "Final",
      "search.teams.placeholder": "Search 48 teams…",
      "venues.all": "All {n} venues",
      "venue.single": "{name}",
      "refresh": "Refresh",
      "updated": "Updated {rel}",
      "loading": "Loading matches…",
      "error.title": "Couldn't load match data.",
      "error.hint": "Try the refresh button.",
      "empty.title": "No matches in this window.",
      "empty.hint": "Try a wider time range or clear your filters.",
      "empty.filtered": "No matches match these filters.",
      "clear": "Clear filters",
      "n.matches": "{n} matches",
      "1.match": "1 match",
      "day.today": "Today · {date}",
      "day.tomorrow": "Tomorrow · {date}",
      "day.other": "{date}",
      "wing.past": "Wing · Past",
      "wing.today": "Body · Today",
      "wing.future": "Wing · Next 3 days",
      "wing.past.empty": "No completed matches yet",
      "wing.future.empty": "No upcoming matches in this window",
      "standings.title": "Group Stage Standings",
      "standings.hint": "Top 2 advance to the Round of 32. The 8 best 3rd-place teams also advance.",
      "standings.col.team": "Team",
      "standings.col.mp": "MP",
      "standings.col.w": "W",
      "standings.col.d": "D",
      "standings.col.l": "L",
      "standings.col.gf": "GF",
      "standings.col.ga": "GA",
      "standings.col.gd": "GD",
      "standings.col.pts": "Pts",
      "standings.empty": "No group standings yet — the group stage starts June 11.",
      "standings.q": "Q",
      "standings.notes": "Q = qualified · q = best 3rd-place",
      "stage": "Stage",
      "venue": "Venue",
      "watch": "Watch",
      "link.espn": "ESPN ↗",
      "link.fox": "Fox Sports ↗",
      "status.live.short": "LIVE",
      "status.final.short": "Final",
      "status.scheduled": "Scheduled",
      "status.starting": "Starting soon",
      "status.halftime": "Halftime",
      "relative.in.h": "in {n}h",
      "relative.in.m": "in {n}m",
      "relative.in.d": "in {n}d",
      "relative.h.ago": "{n}h ago",
      "relative.m.ago": "{n}m ago",
      "relative.d.ago": "{n}d ago",
      "relative.less.than.minute": "less than a minute",
      "relative.less.than.minute.ago": "less than a minute ago",
      "bracket.title": "Knockout bracket",
      "bracket.hint": "Placeholders like \"Group A 2nd Place\" fill in as the group stage completes.",
      "bracket.round-of-32": "Round of 32",
      "bracket.round-of-16": "Round of 16",
      "bracket.quarterfinals": "Quarterfinals",
      "bracket.semifinals": "Semifinals",
      "bracket.final": "Final",
      "bracket.3rd-place": "3rd Place",
      "footer.data": "Data:",
      "footer.refresh": "Refreshed 12× daily at 01:00 / 03:00 / 05:00 / 07:00 / 09:00 / 11:00 / 13:00 / 15:00 / 17:00 / 19:00 / 21:00 / 23:00 CT (every 2h)",
      "footer.source": "Source",
      "tz.times.in": "Times in {tz}",
    },
    zh: {
      "page.title": "2026 国际足联世界杯 — 每日预告",
      "tournament.edition": "第 23 届",
      "tournament.dates": "2026年6月11日 – 7月19日 · 美国 · 加拿大 · 墨西哥",
      "view.label": "视图",
      "view.matches": "比赛",
      "view.standings": "积分",
      "filter.time": "时间",
      "filter.status": "状态",
      "filter.teams": "球队",
      "filter.venues": "场馆",
      "filter.lang": "语言",
      "range.butterfly": "总览",
      "range.today": "今日",
      "range.past": "已结束",
      "range.3d": "未来 3 天",
      "range.7d": "未来 7 天",
      "range.all": "全部 104 场",
      "status.any": "全部",
      "status.upcoming": "未开始",
      "status.live": "直播中",
      "status.final": "已结束",
      "search.teams.placeholder": "搜索 48 支球队…",
      "venues.all": "全部 {n} 个场馆",
      "venue.single": "{name}",
      "refresh": "刷新",
      "updated": "{rel}前更新",
      "loading": "加载比赛中…",
      "error.title": "无法加载比赛数据。",
      "error.hint": "请尝试刷新按钮。",
      "empty.title": "当前范围没有比赛。",
      "empty.hint": "试试更宽的时间范围或清除筛选条件。",
      "empty.filtered": "没有符合筛选条件的比赛。",
      "clear": "清除筛选",
      "n.matches": "{n} 场比赛",
      "1.match": "1 场比赛",
      "day.today": "今日 · {date}",
      "day.tomorrow": "明日 · {date}",
      "day.other": "{date}",
      "wing.past": "左翼 · 已结束",
      "wing.today": "中央 · 今日",
      "wing.future": "右翼 · 未来 3 天",
      "wing.past.empty": "暂无已完赛比赛",
      "wing.future.empty": "近 3 天暂无比赛",
      "standings.title": "小组赛积分",
      "standings.hint": "各组前 2 名晋级 32 强，8 个成绩最好的第 3 名同样晋级。",
      "standings.col.team": "球队",
      "standings.col.mp": "赛",
      "standings.col.w": "胜",
      "standings.col.d": "平",
      "standings.col.l": "负",
      "standings.col.gf": "进",
      "standings.col.ga": "失",
      "standings.col.gd": "净",
      "standings.col.pts": "分",
      "standings.empty": "小组赛尚未开赛（6 月 11 日开始），暂无积分数据。",
      "standings.q": "Q",
      "standings.notes": "Q = 已晋级 · q = 成绩最好的第 3 名",
      "stage": "阶段",
      "venue": "场馆",
      "watch": "观看",
      "link.espn": "ESPN ↗",
      "link.fox": "福克斯体育 ↗",
      "status.live.short": "直播",
      "status.final.short": "终场",
      "status.scheduled": "未开赛",
      "status.starting": "即将开赛",
      "status.halftime": "中场",
      "relative.in.h": "{n} 小时后",
      "relative.in.m": "{n} 分钟后",
      "relative.in.d": "{n} 天后",
      "relative.h.ago": "{n} 小时前",
      "relative.m.ago": "{n} 分钟前",
      "relative.d.ago": "{n} 天前",
      "relative.less.than.minute": "不到一分钟",
      "relative.less.than.minute.ago": "不到一分钟前",
      "bracket.title": "淘汰赛对阵",
      "bracket.hint": "占位符（如\"A 组第二名\"）将在小组赛进行后填入。",
      "bracket.round-of-32": "16 强",
      "bracket.round-of-16": "八强",
      "bracket.quarterfinals": "四分之一决赛",
      "bracket.semifinals": "半决赛",
      "bracket.final": "决赛",
      "bracket.3rd-place": "三四名决赛",
      "footer.data": "数据：",
      "footer.refresh": "每日 12 次刷新（01:00 / 03:00 / 05:00 / 07:00 / 09:00 / 11:00 / 13:00 / 15:00 / 17:00 / 19:00 / 21:00 / 23:00 CT，每 2 小时一次）",
      "footer.source": "源码",
      "tz.times.in": "时间显示：{tz}",
    },
  };

  let currentLang = "en";
  function t(key, vars = {}) {
    const dict = I18N[currentLang] || I18N.en;
    let str = dict[key] || I18N.en[key] || key;
    for (const [k, v] of Object.entries(vars)) {
      str = str.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
    return str;
  }

  // Single-language team display: zh mode shows the Chinese name,
  // en mode shows the English short name. Knockout placeholders
  // ("Group A Winner", etc.) have no `name_zh` entry, so they fall
  // through to the English placeholder string — which is what we want.
  function teamDisplayName(team) {
    if (!team) return "—";
    if (currentLang === "zh" && team.name_zh) return team.name_zh;
    return team.short || team.name || "—";
  }

  // Search corpus for the team picker. Always includes both English
  // and Chinese names regardless of the active language toggle, so
  // typing "巴西" or "Brazil" both find Brazil.
  function teamSearchText(team) {
    const parts = [team.name, team.short, team.name_zh, team.abbr];
    return parts.filter(Boolean).join(" ").toLowerCase();
  }

  // Small `#N` suffix for a team's FIFA ranking. Returns "" if the
  // ranking is missing (knockout placeholders, future qualifiers).
  // Used as a tiny annotation right after the team name.
  function teamRankSpan(team) {
    if (!team || team.rank == null) return "";
    return ` <span class="team-rank">#${team.rank}</span>`;
  }

  function loadLang() {
    try {
      const raw = localStorage.getItem(LANG_KEY);
      if (raw === "zh" || raw === "en") return raw;
    } catch { /* ignore */ }
    return "zh";
  }
  function saveLang(lang) {
    try { localStorage.setItem(LANG_KEY, lang); } catch { /* ignore */ }
  }
  function setLang(lang) {
    currentLang = (lang === "zh") ? "zh" : "en";
    saveLang(currentLang);
    document.documentElement.lang = currentLang === "zh" ? "zh-Hans" : "en";
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    $$("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle, { tz: "Local" }); });
    $$("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
    updateLangPills();
    if (allData) {
      renderHeader(allData);
      render();
      renderBracket();
    }
  }
  function updateLangPills() {
    $$(".lang-pill").forEach((p) => {
      const checked = p.dataset.lang === currentLang;
      p.setAttribute("aria-checked", checked ? "true" : "false");
    });
  }

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
      if (Date.now() - at > 60 * 1000) return null;
      return data;
    } catch {
      return null;
    }
  }

  function writeCache(data) {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), data }));
    } catch { /* private mode / quota — fine */ }
  }

  // ────────────────────────────────────────────────────────────
  // Time helpers
  // ────────────────────────────────────────────────────────────
  function localTimezone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "local"; }
    catch { return "local"; }
  }
  function nowInZone(tzName) {
    if (!tzName) return new Date();
    try {
      const localStr = new Date().toLocaleString("en-US", { timeZone: tzName });
      return new Date(localStr);
    } catch { return new Date(); }
  }
  function formatRelative(target, now) {
    const diffMs = target.getTime() - now.getTime();
    const abs = Math.abs(diffMs);
    const past = diffMs < 0;
    const minute = 60_000, hour = 3_600_000, day = 86_400_000;
    const key = past ? "relative.less.than.minute.ago" : "relative.less.than.minute";
    let label;
    if (abs < minute) label = t(key);
    else if (abs < hour) label = past ? t("relative.m.ago", { n: Math.round(abs / minute) }) : t("relative.in.m", { n: Math.round(abs / minute) });
    else if (abs < day) label = past ? t("relative.h.ago", { n: Math.round(abs / hour) }) : t("relative.in.h", { n: Math.round(abs / hour) });
    else label = past ? t("relative.d.ago", { n: Math.round(abs / day) }) : t("relative.in.d", { n: Math.round(abs / day) });
    return label;
  }

  // ────────────────────────────────────────────────────────────
  // Display-timezone state
  // ────────────────────────────────────────────────────────────
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

  let selectedTz = null;

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
  function currentTz() { return selectedTz || localTimezone(); }
  function isLocalTz() { return !selectedTz; }

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
  function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
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
  function currentTzLabel() {
    if (isLocalTz()) {
      const browser = localTimezone();
      return `Local · ${browser} · ${offsetLabel("")}`;
    }
    const opt = TZ_OPTIONS.find((o) => o.value === selectedTz);
    return opt ? opt.label : `${selectedTz} · ${offsetLabel(selectedTz)}`;
  }

  // ────────────────────────────────────────────────────────────
  // Filter state — "butterfly" is the default
  // ────────────────────────────────────────────────────────────
  const DEFAULT_FILTERS = Object.freeze({
    range: "3d",         // butterfly | today | past | 3d | 7d | all
    status: "any",
    teams: [],
    venues: [],
  });

  let filters = { ...DEFAULT_FILTERS };
  let allData = null;
  let allMatches = [];
  let currentView = "matches";  // matches | standings

  function loadFilters() {
    // Filters are intentionally session-only. On every page load we
    // start from DEFAULT_FILTERS and ignore any prior localStorage
    // state or URL-hash state. (Refresh → defaults, every time.)
    // The URL hash is cleared so the address bar doesn't lie about
    // what the page is showing.
    if (location.hash) {
      try { history.replaceState(null, "", location.pathname + location.search); } catch { /* ignore */ }
    }
    return { ...DEFAULT_FILTERS };
  }

  function saveFilters() {
    // No-op: filter changes are in-memory only and don't survive
    // a page load. (The wrapper is kept so call sites don't need
    // to change.)
  }

  function normalizeFilters(f) {
    const out = { ...DEFAULT_FILTERS, ...f };
    out.range = ["butterfly", "today", "past", "3d", "7d", "all"].includes(out.range) ? out.range : "3d";
    out.status = ["any", "upcoming", "live", "final"].includes(out.status) ? out.status : "any";
    out.teams = Array.isArray(out.teams) ? out.teams.slice(0, 8) : [];
    out.venues = Array.isArray(out.venues) ? out.venues.slice(0, 16) : [];
    return out;
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
  // Bucketing logic for the butterfly view
  // Past  = date < todayIso, status === "FINAL" (no scores missing)
  // Today = date === todayIso (LIVE/SCHEDULED — never classified as past
  //         even if kickoff has technically passed; ESPN has not flipped
  //         the status yet, so it stays here)
  // Future= today < date <= today+2  (3-day window including today+2)
  // ────────────────────────────────────────────────────────────
  function bucketButterfly(matches, tz) {
    const todayIso = dateInTz(new Date(), tz);
    const futureEnd = addDays(todayIso, 2);
    const past = [];
    const today = [];
    const future = [];
    for (const m of matches) {
      const mDate = dateInTz(new Date(m.kickoff_utc), tz);
      if (mDate < todayIso) {
        // Only show past matches that actually finished. A SCHEDULED
        // match from an earlier date (e.g. rescheduled, postponed)
        // stays out of "past" so the user doesn't see ghosts.
        if (m.status === "FINAL") past.push(m);
      } else if (mDate === todayIso) {
        today.push(m);
      } else if (mDate <= futureEnd) {
        future.push(m);
      }
    }
    past.sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
    today.sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
    future.sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
    return { past, today, future, todayIso, futureEnd };
  }

  // ────────────────────────────────────────────────────────────
  // Filtering
  // ────────────────────────────────────────────────────────────
  function applyFilters() {
    if (!allData) return [];
    const tz = currentTz();
    const now = nowInZone(tz);
    const todayIso = dateInTz(new Date(), tz);

    let windowStart, windowEnd;
    if (filters.range === "butterfly") {
      // Past + today + next 3 days (4-day window)
      windowStart = allData.tournament.start;
      windowEnd = addDays(todayIso, 2);
    } else if (filters.range === "today") {
      windowStart = windowEnd = todayIso;
    } else if (filters.range === "past") {
      // Hard rule: "past" only includes dates strictly before today.
      // Within those dates, only FINAL matches show. Any SCHEDULED
      // match from before today stays hidden here.
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
      const mDate = dateInTz(new Date(m.kickoff_utc), tz);
      if (mDate < windowStart || mDate > windowEnd) continue;

      // Past filter excludes any not-yet-finalized match
      if (filters.range === "past" && m.status !== "FINAL") continue;

      if (filters.status !== "any") {
        const live = m.status === "LIVE";
        const fin = m.status === "FINAL";
        let s = m.status;
        if (s === "SCHEDULED" && new Date(m.kickoff_utc) <= now) s = "LIVE";
        if (filters.status === "upcoming" && !(s === "SCHEDULED" && new Date(m.kickoff_utc) > now)) continue;
        if (filters.status === "live" && !live && s !== "LIVE") continue;
        if (filters.status === "final" && !fin) continue;
      }

      if (filters.teams.length) {
        const ids = filters.teams.map(String);
        if (!ids.includes(String(m.home.id)) && !ids.includes(String(m.away.id))) continue;
      }
      if (filters.venues.length) {
        if (!filters.venues.includes(m.venue.name)) continue;
      }

      out.push(m);
    }
    out.sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
    return out;
  }

  // ────────────────────────────────────────────────────────────
  // Render dispatcher (view-aware)
  // ────────────────────────────────────────────────────────────
  function render() {
    if (currentView === "standings") {
      renderStandings();
      return;
    }
    const matches = applyFilters();
    renderMatches(matches);
  }

  // ────────────────────────────────────────────────────────────
  // Render: match list (with butterfly layout for the default range)
  // ────────────────────────────────────────────────────────────
  function renderMatches(matches) {
    const content = $("#content");
    content.innerHTML = "";
    const countEl = $("#result-count");
    if (countEl) {
      countEl.textContent = matches.length === 1 ? t("1.match") : t("n.matches", { n: matches.length });
    }

    if (matches.length === 0) {
      const hasFilters = !isDefaultFilters();
      const div = document.createElement("div");
      div.className = "empty";
      div.innerHTML = `<div>${escapeHtml(hasFilters ? t("empty.filtered") : t("empty.title"))}</div>
        <div class="empty-hint">${escapeHtml(t("empty.hint"))}</div>`;
      content.appendChild(div);
      return;
    }

    // Butterfly view: split into past + today + future 3-day columns
    if (filters.range === "butterfly") {
      renderButterfly(content, matches);
      return;
    }

    // Other ranges: group by day in a single column
    renderDayList(content, matches);
  }

  function renderButterfly(content, matches) {
    const tz = currentTz();
    const { past, today, future } = bucketButterfly(matches, tz);
    const grid = document.createElement("div");
    grid.className = "butterfly";

    grid.appendChild(buildWing("past", t("wing.past"), past, "wing-past-empty"));
    grid.appendChild(buildWing("today", t("wing.today"), today, "wing-today-empty"));
    grid.appendChild(buildWing("future", t("wing.future"), future, "wing-future-empty"));

    content.appendChild(grid);
  }

  function buildWing(wing, title, matches, emptyKey) {
    const wrap = document.createElement("section");
    wrap.className = `butterfly-wing butterfly-wing--${wing}`;
    wrap.setAttribute("aria-label", title);

    const head = document.createElement("header");
    head.className = "wing-head";
    head.innerHTML = `<span class="wing-title">${escapeHtml(title)}</span><span class="wing-count">${matches.length}</span>`;
    wrap.appendChild(head);

    if (matches.length === 0) {
      const empty = document.createElement("div");
      empty.className = "wing-empty";
      empty.textContent = t(emptyKey);
      wrap.appendChild(empty);
      return wrap;
    }

    // Group wing matches by day so the user can still see date breaks
    const groups = groupByDay(matches);
    const list = document.createElement("ul");
    list.className = "matches";
    list.setAttribute("role", "list");
    for (const group of groups) {
      // Day sub-header (only emit when there are 2+ days in this wing)
      if (groups.length > 1) {
        const dh = document.createElement("li");
        dh.className = "wing-day-head";
        dh.innerHTML = `<span>${escapeHtml(group.label)}</span><span class="wing-day-count">${group.matches.length}</span>`;
        list.appendChild(dh);
      }
      for (const m of group.matches) {
        const card = buildMatchCard(m);
        // Inject compact venue + broadcast row in the wing card body
        injectWingMeta(card, m);
        list.appendChild(card);
      }
    }
    wrap.appendChild(list);
    return wrap;
  }

  function injectWingMeta(card, m) {
    const body = card.querySelector(".match-body");
    if (!body) return;
    const venue = m.venue?.name || "";
    const city = m.venue?.city || "";
    const venueShort = shortenForVenue(venue);
    const venueTitle = [venue, city].filter(Boolean).join(", ");
    const broadcasts = Array.isArray(m.broadcasts) ? m.broadcasts : [];
    const bcastShort = broadcasts.slice(0, 2).join(", ");
    const bcastExtra = broadcasts.length > 2 ? ` +${broadcasts.length - 2}` : "";
    const meta = document.createElement("div");
    meta.className = "wing-meta";
    if (venueShort) {
      const v = document.createElement("span");
      v.className = "wing-venue";
      v.title = venueTitle;
      v.textContent = "🏟️ " + venueShort;
      meta.appendChild(v);
    }
    if (broadcasts.length) {
      const b = document.createElement("span");
      b.className = "wing-broadcast";
      b.title = broadcasts.join(", ");
      b.textContent = "📺 " + bcastShort + bcastExtra;
      meta.appendChild(b);
    }
    if (meta.children.length) body.appendChild(meta);
  }

  function shortenForVenue(name) {
    if (!name) return "";
    // Strip "Estádio", "Stadion", "Stadium" suffix to save space
    let s = name.replace(/\s*(Stadium|Estádio|Estadio|Stadion|Arena|Field|球埸|体育馆)\s*$/i, "").trim();
    if (!s) s = name;
    if (s.length > 16) s = s.slice(0, 15) + "…";
    return s;
  }

  function groupByDay(matches) {
    const tz = currentTz();
    const byDate = new Map();
    for (const m of matches) {
      const d = dateInTz(new Date(m.kickoff_utc), tz);
      if (!byDate.has(d)) byDate.set(d, []);
      byDate.get(d).push(m);
    }
    const today = dateInTz(new Date(), tz);
    const tomorrow = addDays(today, 1);
    return Array.from(byDate.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([d, items]) => ({
        date: d,
        label: d === today ? t("day.today", { date: d }) : d === tomorrow ? t("day.tomorrow", { date: d }) : t("day.other", { date: d }),
        matches: items,
      }));
  }

  function renderStandings() {
    const content = $("#content");
    content.innerHTML = "";
    const countEl = $("#result-count");
    if (countEl) countEl.textContent = "";

    const groups = (allData && allData.groups) || [];
    if (groups.length === 0) {
      const div = document.createElement("div");
      div.className = "empty";
      div.innerHTML = `<div>${escapeHtml(t("standings.empty"))}</div>`;
      content.appendChild(div);
      return;
    }

    const wrap = document.createElement("section");
    wrap.className = "standings-section";
    const head = document.createElement("header");
    head.className = "standings-head";
    head.innerHTML = `<h2 class="standings-title">${escapeHtml(t("standings.title"))}</h2>
      <p class="standings-hint">${escapeHtml(t("standings.hint"))}</p>`;
    wrap.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "standings-grid";
    for (const g of groups) grid.appendChild(buildGroupTable(g));
    wrap.appendChild(grid);

    const note = document.createElement("p");
    note.className = "standings-notes";
    note.textContent = t("standings.notes");
    wrap.appendChild(note);

    content.appendChild(wrap);
  }

  function buildGroupTable(group) {
    const card = document.createElement("div");
    card.className = "group-card";
    const head = document.createElement("header");
    head.className = "group-head";
    head.innerHTML = `<span class="group-name">${escapeHtml(group.abbreviation || group.name)}</span>`;
    card.appendChild(head);

    const table = document.createElement("table");
    table.className = "group-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th class="col-num col-pts" title="${escapeHtml(t("standings.col.pts"))}">${escapeHtml(t("standings.col.pts"))}</th>
          <th class="col-team">${escapeHtml(t("standings.col.team"))}</th>
          <th class="col-rank">#</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.mp"))}">${escapeHtml(t("standings.col.mp"))}</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.w"))}">${escapeHtml(t("standings.col.w"))}</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.d"))}">${escapeHtml(t("standings.col.d"))}</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.l"))}">${escapeHtml(t("standings.col.l"))}</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.gf"))}">${escapeHtml(t("standings.col.gf"))}</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.ga"))}">${escapeHtml(t("standings.col.ga"))}</th>
          <th class="col-num" title="${escapeHtml(t("standings.col.gd"))}">${escapeHtml(t("standings.col.gd"))}</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");
    for (const e of (group.entries || [])) {
      const tr = document.createElement("tr");
      const rank = e.rank || 0;
      if (rank <= 2) tr.classList.add("is-qualified");
      else if (rank === 3) tr.classList.add("is-possible");
      tr.innerHTML = `
        <td class="col-num col-pts"><strong>${e.pts}</strong></td>
        <td class="col-team">
          <span class="team-flag">${escapeHtml(e.team.flag || "")}</span>
          <span class="team-short">${escapeHtml(teamDisplayName(e.team))}${teamRankSpan(e.team)}</span>
        </td>
        <td class="col-rank">
          <span class="rank-num">${rank}</span>
          ${rank === 1 || rank === 2 ? `<span class="qual-q" title="${escapeHtml(t("standings.q"))}">Q</span>` : ""}
        </td>
        <td class="col-num">${e.mp}</td>
        <td class="col-num">${e.w}</td>
        <td class="col-num">${e.d}</td>
        <td class="col-num">${e.l}</td>
        <td class="col-num">${e.gf}</td>
        <td class="col-num">${e.ga}</td>
        <td class="col-num ${e.gd > 0 ? "is-pos" : e.gd < 0 ? "is-neg" : ""}">${e.gd > 0 ? `+${e.gd}` : e.gd}</td>
      `;
      tbody.appendChild(tr);
    }
    card.appendChild(table);
    return card;
  }


  function renderDayList(content, matches) {
    const groups = groupByDay(matches);
    for (const group of groups) {
      const day = document.createElement("section");
      day.className = "day";
      const head = document.createElement("header");
      head.className = "day-head";
      const isT = group.date === dateInTz(new Date(), currentTz());
      const isT1 = group.date === addDays(dateInTz(new Date(), currentTz()), 1);
      day.classList.add(isT ? "is-today" : isT1 ? "is-tomorrow" : "is-other");
      head.innerHTML = `<h2 class="day-title">${escapeHtml(group.label)}</h2><span class="day-count">${group.matches.length}</span>`;
      day.appendChild(head);
      const ul = document.createElement("ul");
      ul.className = "matches";
      ul.setAttribute("role", "list");
      for (const m of group.matches) ul.appendChild(buildMatchCard(m));
      day.appendChild(ul);
      content.appendChild(day);
    }
  }

  function buildMatchCard(m) {
    const tmpl = $("#match-template");
    const node = tmpl.content.firstElementChild.cloneNode(true);
    populateMatchCard(node, m);
    return node;
  }

  function renderIncidents(container, incidents) {
    if (!container) return;
    if (!incidents || incidents.length === 0) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    container.hidden = false;
    container.innerHTML = "";
    const goals   = incidents.filter((i) => i.kind === "goal");
    const yellows = incidents.filter((i) => i.kind === "yellow_card");
    const reds    = incidents.filter((i) => i.kind === "red_card");
    if (goals.length)   _incidentRow(container, "goal",   "⚽", goals);
    if (yellows.length) _incidentRow(container, "yellow", "🟨", yellows);
    if (reds.length)    _incidentRow(container, "red",    "🟥", reds);
  }

  function _incidentRow(container, rowClass, icon, list) {
    const row = document.createElement("div");
    row.className = "incident-row is-" + rowClass;
    const iconEl = document.createElement("span");
    iconEl.className = "ir-icon";
    iconEl.textContent = icon;
    row.appendChild(iconEl);
    list.forEach((inc, i) => {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.className = "ir-sep";
        sep.textContent = "·";
        row.appendChild(sep);
      }
      const incident = document.createElement("span");
      incident.className = "incident";
      const player = document.createElement("span");
      player.className = "ic-player";
      player.textContent = inc.player || "—";
      incident.appendChild(player);
      if (inc.assist) {
        const a = document.createElement("span");
        a.className = "ic-assist";
        a.textContent = inc.assist;
        incident.appendChild(a);
      }
      const min = document.createElement("span");
      min.className = "ic-minute";
      min.textContent = inc.minute;
      incident.appendChild(min);
      row.appendChild(incident);
    });
    container.appendChild(row);
  }

  function populateMatchCard(node, m) {
    const tz = currentTz();
    const now = nowInZone(tz);
    const kickoff = new Date(m.kickoff_utc);
    const isLive = m.status === "LIVE";
    const isFinal = m.status === "FINAL";
    const isScheduled = m.status === "SCHEDULED";

    const timeMain = node.querySelector(".time-main");
    const timeStatus = node.querySelector(".time-status");
    timeMain.textContent = timeInTz(kickoff, tz);
    timeStatus.classList.remove("is-live", "is-final", "is-scheduled", "is-starting");
    if (isLive) {
      timeStatus.classList.add("is-live");
      timeStatus.textContent = t("status.live.short");
      node.classList.add("is-live");
    } else if (isFinal) {
      timeStatus.classList.add("is-final");
      timeStatus.textContent = t("status.final.short");
      node.classList.add("is-final");
    } else if (isScheduled) {
      const minutes = (kickoff - now) / 60_000;
      if (minutes > 0 && minutes <= 30) {
        // Within 30 min of kickoff — show "Starting soon" / "in Xm"
        timeStatus.classList.add("is-starting");
        timeStatus.textContent = formatRelative(kickoff, now);
      } else if (minutes <= 0) {
        // Kickoff has passed but ESPN still has it as SCHEDULED.
        // Don't say "Xm ago" (it would look like the game happened).
        // Show nothing — the kickoff time itself is the truth.
        timeStatus.textContent = "";
      } else {
        timeStatus.classList.add("is-scheduled");
        timeStatus.textContent = formatRelative(kickoff, now);
      }
    }

    const home = node.querySelector(".team.home");
    const away = node.querySelector(".team.away");
    const homeFlag = home.querySelector(".team-flag");
    const homeName = home.querySelector(".team-name");
    const homeScore = home.querySelector(".team-score");
    homeFlag.textContent = m.home.flag || "🏳️";
    homeName.innerHTML = escapeHtml(teamDisplayName(m.home)) + teamRankSpan(m.home);
    if (isLive || isFinal) {
      homeScore.textContent = m.home.score != null ? m.home.score : "—";
    } else {
      homeScore.textContent = "";
    }
    if (m.home.winner === true) home.classList.add("is-winner");
    if (m.home.winner === false) home.classList.add("is-loser");

    const awayFlag = away.querySelector(".team-flag");
    const awayName = away.querySelector(".team-name");
    const awayScore = away.querySelector(".team-score");
    awayFlag.textContent = m.away.flag || "🏳️";
    awayName.innerHTML = escapeHtml(teamDisplayName(m.away)) + teamRankSpan(m.away);
    if (isLive || isFinal) {
      awayScore.textContent = m.away.score != null ? m.away.score : "—";
    } else {
      awayScore.textContent = "";
    }
    if (m.away.winner === true) away.classList.add("is-winner");
    if (m.away.winner === false) away.classList.add("is-loser");

    // Per-match incidents: goals + cards (only for LIVE / FINAL)
    renderIncidents(node.querySelector(".match-incidents"), m.incidents);

    const stage = node.querySelector(".stage");
    const venue = node.querySelector(".venue");
    const broadcasts = node.querySelector(".broadcasts");
    stage.textContent = m.stage || "—";
    venue.textContent = m.venue?.name || "—";
    const bcast = m.broadcasts?.length ? m.broadcasts.join(", ") : "—";
    broadcasts.textContent = bcast;

    const espn = node.querySelector("a.espn");
    const fox = node.querySelector("a.fox");
    if (m.espn_url) espn.href = m.espn_url;
    else espn.removeAttribute("href");
    if (m.fox_url) fox.href = m.fox_url;
    else fox.removeAttribute("href");
  }

  // ────────────────────────────────────────────────────────────
  // Header
  // ────────────────────────────────────────────────────────────
  function renderHeader(data) {
    const sub = $("#tournament-subtitle");
    if (sub && data.tournament) sub.textContent = data.tournament.dates;
    const updated = $("#updated");
    if (updated) {
      const now = new Date(data.generated_at);
      updated.textContent = t("updated", { rel: formatRelative(now, new Date()) });
      updated.title = new Date(data.generated_at).toLocaleString();
    }
  }

  // ────────────────────────────────────────────────────────────
  // Bracket rendering — double-wing butterfly with connecting lines
  // ────────────────────────────────────────────────────────────
  function renderBracket() {
    if (!allData) return;
    const section = $("#bracket-section");
    const container = $("#bracket-butterfly");
    if (!section || !container) return;
    const stages = ["round-of-32", "round-of-16", "quarterfinals", "semifinals"];
    const hasKOs = allMatches.some((m) => m.stage_slug && stages.includes(m.stage_slug));
    if (!hasKOs) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    container.innerHTML = "";

    const rounds = ["round-of-32", "round-of-16", "quarterfinals", "semifinals", "final"];
    const byRound = {};
    for (const r of rounds) {
      const ms = allMatches.filter((m) => m.stage_slug === r);
      ms.sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
      byRound[r] = ms;
    }
    const third = allMatches.find((m) => m.stage_slug === "3rd-place-match");

    // Compute Y position (0-100% of height) and side (L/R) for every match.
    // Center of each match sits at the midpoint of its two source matches.
    const pos = {};  // matchId -> { y, side }
    function place(round) {
      const ms = byRound[round] || [];
      const n = ms.length;
      if (n === 0) return;
      if (round === "final") {
        for (const m of ms) pos[m.id] = { y: 50, side: "C" };
        return;
      }
      const half = n / 2;
      ms.forEach((m, i) => {
        let y;
        if (round === "round-of-32") y = ((i + 0.5) / 16) * 100;
        else if (round === "round-of-16") y = ((2 * i + 1) / 16) * 100;
        else if (round === "quarterfinals") y = ((4 * i + 2) / 16) * 100;
        else if (round === "semifinals") y = ((8 * i + 4) / 16) * 100;
        // Compress to 90% range with 5% top/bottom margin so the topmost
        // card clears the column-labels row above. Linear transform keeps
        // the midpoint relationships that the SVG connecting lines rely on.
        y = y * 0.9 + 5;
        pos[m.id] = { y, side: i < half ? "L" : "R" };
      });
    }
    place("round-of-32");
    place("round-of-16");
    place("quarterfinals");
    place("semifinals");
    place("final");
    if (third) pos[third.id] = { y: 50, side: "C" };

    // SVG layer of connecting lines
    const SVG_NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "bracket-lines");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");

    // 9 columns: R32 | R16 | QF | SF | [Final] | SF | QF | R16 | R32
    // Card width 96px, gap 6px. Total: 9*96 + 8*6 = 912px, centered.
    // Use a normalized 912px coordinate system inside the 100% container
    // by anchoring to ((100% - 912px) / 2) horizontal padding.
    const CARD_W = 96;
    const COL_GAP = 6;
    const TOTAL_W = 9 * CARD_W + 8 * COL_GAP;  // 912
    const PAD = (100 - (TOTAL_W / 12)) / 2;  // 100% - 912; used as left/right padding in %
    const COL_PX = {
      "round-of-32":   0,
      "round-of-16":   CARD_W + COL_GAP,         // 102
      "quarterfinals": 2 * (CARD_W + COL_GAP),   // 204
      "semifinals":    3 * (CARD_W + COL_GAP),   // 306
    };
    // In %: each px offset is offset_px / 912 * 100
    function pxToPct(px) { return (px / TOTAL_W) * 100; }

    function cardLeftX(stage, side) {
      if (stage === "final") return 50;       // centered (CSS handles translate)
      if (stage === "3rd-place-match") return 50 + pxToPct(4 * (CARD_W + COL_GAP));  // 4 cols right of center
      const offsetPx = COL_PX[stage] || 0;
      const offsetPct = pxToPct(offsetPx);
      if (side === "L") return offsetPct;
      // Mirror: 100% - left_offset% - card_width%
      return 100 - offsetPct - pxToPct(CARD_W);
    }
    function cardRightX(stage, side) {
      if (stage === "final") return 50;
      if (stage === "3rd-place-match") return 50 + pxToPct(4 * (CARD_W + COL_GAP)) + pxToPct(CARD_W);
      const offsetPx = COL_PX[stage] || 0;
      const offsetPct = pxToPct(offsetPx);
      if (side === "L") return offsetPct + pxToPct(CARD_W);
      return 100 - offsetPct;
    }

    function addLine(x1, y1, x2, y2, isWinner) {
      const midX = (x1 + x2) / 2;
      const d = `M ${x1.toFixed(2)} ${y1.toFixed(2)} C ${midX.toFixed(2)} ${y1.toFixed(2)}, ${midX.toFixed(2)} ${y2.toFixed(2)}, ${x2.toFixed(2)} ${y2.toFixed(2)}`;
      const p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      if (isWinner) p.setAttribute("class", "is-winner");
      svg.appendChild(p);
    }

    function linkRound(stage, nextStage) {
      const ms = byRound[stage] || [];
      for (let i = 0; i < ms.length; i += 2) {
        const a = ms[i], b = ms[i + 1];
        const parent = (byRound[nextStage] || [])[i / 2];
        if (!parent || !a || !b) continue;
        const pa = pos[a.id], pb = pos[b.id], pp = pos[parent.id];
        if (!pa || !pb || !pp) continue;
        // Only highlight a winner's line once the parent match is
        // decided (FINAL + one winner). ESPN pre-fills both as false
        // on placeholder matches.
        const parentDecided = parent.status === "FINAL" && (parent.home.winner === true || parent.away.winner === true);
        const winnerSrc = parentDecided
          ? (parent.home.winner === true ? a : b)
          : null;
        addLine(cardRightX(stage, pa.side), pa.y, cardLeftX(nextStage, pp.side), pp.y, winnerSrc === a);
        addLine(cardRightX(stage, pb.side), pb.y, cardLeftX(nextStage, pp.side), pp.y, winnerSrc === b);
      }
    }
    linkRound("round-of-32", "round-of-16");
    linkRound("round-of-16", "quarterfinals");
    linkRound("quarterfinals", "semifinals");
    linkRound("semifinals", "final");
    container.appendChild(svg);

    // Column labels at the top (R32 | R16 | QF | SF | [Final] | SF | QF | R16 | R32)
    const labels = document.createElement("div");
    labels.className = "bracket-col-labels";
    const labelOrder = [
      { key: "bracket.round-of-32", side: "L" },
      { key: "bracket.round-of-16", side: "L" },
      { key: "bracket.quarterfinals", side: "L" },
      { key: "bracket.semifinals", side: "L" },
      { key: "bracket.final", side: "C", center: true },
      { key: "bracket.semifinals", side: "R" },
      { key: "bracket.quarterfinals", side: "R" },
      { key: "bracket.round-of-16", side: "R" },
      { key: "bracket.round-of-32", side: "R" },
    ];
    for (const l of labelOrder) {
      const span = document.createElement("span");
      span.className = "bracket-col-label" + (l.center ? " is-center" : "");
      span.textContent = t(l.key);
      labels.appendChild(span);
    }
    container.appendChild(labels);

    // Build cards
    function appendCard(m, customY) {
      if (!m) return;
      const p = pos[m.id];
      const card = buildBracketCard(m, p);
      card.style.top = (customY != null ? customY : p.y) + "%";
      container.appendChild(card);
    }
    for (const r of rounds) for (const m of byRound[r] || []) appendCard(m);
    if (third) {
      // Position the 3rd-place match slightly to the right of Final
      // and a bit below it so it doesn't overlap the SF lines.
      pos[third.id] = { y: 56, side: "C" };
      appendCard(third, 58);
    }
  }

  function buildBracketCard(m, p) {
    const node = document.createElement("a");
    node.className = "bracket-card";
    node.href = m.espn_url || "#";
    node.target = "_blank";
    node.rel = "noopener noreferrer";
    node.dataset.stage = m.stage_slug;
    if (p && p.side) node.dataset.side = p.side;
    if (m.status === "LIVE") node.classList.add("is-live");
    if (m.status === "FINAL") node.classList.add("is-final");
    if (m.status === "FINAL" && (m.home.winner || m.away.winner)) node.classList.add("is-final-winner");
    const tz = currentTz();
    const homeName = escapeHtml(teamDisplayName(m.home)) + teamRankSpan(m.home) || "TBD";
    const awayName = escapeHtml(teamDisplayName(m.away)) + teamRankSpan(m.away) || "TBD";
    const homeScore = m.status === "SCHEDULED" ? "" : (m.home.score != null ? m.home.score : "");
    const awayScore = m.status === "SCHEDULED" ? "" : (m.away.score != null ? m.away.score : "");
    const homeTbd = !m.home.id;
    const awayTbd = !m.away.id;
    const homeWin = m.home.winner === true;
    const awayWin = m.away.winner === true;
    // Only mark a team as a loser once the match is FINAL and the
    // other side has been decided as the winner. ESPN pre-fills
    // `winner: false` for both teams on placeholder matches, so we
    // must not treat that as a real loss.
    const decided = m.status === "FINAL" && (homeWin || awayWin);
    const homeLose = decided && !homeWin;
    const awayLose = decided && !awayWin;
    const roundKey = `bracket.${m.stage_slug}`;
    const showLabel = p && p.side && (m.stage_slug === "round-of-32" || m.stage_slug === "round-of-16" || m.stage_slug === "quarterfinals" || m.stage_slug === "semifinals");
    const roundLabel = showLabel ? `<span class="bracket-round-label">${escapeHtml(t(roundKey))}</span>` : "";
    node.innerHTML = `
      ${roundLabel}
      <div class="bracket-team ${homeWin ? "is-winner" : ""} ${homeLose ? "is-loser" : ""} ${homeTbd ? "is-tbd" : ""}">
        <span class="bc-team-name">${escapeHtml(homeName)}</span>
        <span class="bc-team-score">${homeScore || "—"}</span>
      </div>
      <div class="bracket-team ${awayWin ? "is-winner" : ""} ${awayLose ? "is-loser" : ""} ${awayTbd ? "is-tbd" : ""}">
        <span class="bc-team-name">${escapeHtml(awayName)}</span>
        <span class="bc-team-score">${awayScore || "—"}</span>
      </div>
      <div class="bc-status ${m.status === "LIVE" ? "is-live" : m.status === "FINAL" ? "is-final" : ""}">
        <span>${
          m.status === "LIVE" ? "● " + t("status.live.short") :
          m.status === "FINAL" ? t("status.final.short") :
          timeInTz(new Date(m.kickoff_utc), tz)
        }</span>
      </div>
    `;
    return node;
  }

  // ────────────────────────────────────────────────────────────
  // Filters UI wiring
  // ────────────────────────────────────────────────────────────
  function setInitialPills() {
    $$(".pills [data-value]").forEach((p) => {
      const group = p.closest(".filter-group");
      if (!group) return;
      const filterKey = group.dataset.filter;
      if (!filterKey) return;
      p.setAttribute("aria-checked", String(filters[filterKey] === p.dataset.value));
    });
  }

  function wirePills() {
    $$(".pills [data-value]").forEach((p) => {
      p.addEventListener("click", () => {
        const group = p.closest(".filter-group");
        const filterKey = group?.dataset.filter;
        if (!filterKey) return;
        filters[filterKey] = p.dataset.value;
        setInitialPills();
        onFilterChange();
      });
    });
  }

  function wireTzPicker() {
    const pill = $("#tz-pill");
    const menu = $("#tz-menu");
    const label = $("#tz-pill-label");
    function refresh() {
      label.textContent = currentTzLabel();
    }
    function open() {
      pill.setAttribute("aria-expanded", "true");
      menu.hidden = false;
    }
    function close() {
      pill.setAttribute("aria-expanded", "false");
      menu.hidden = true;
    }
    function toggle() { menu.hidden ? open() : close(); }
    pill.addEventListener("click", toggle);
    document.addEventListener("click", (e) => {
      if (!pill.contains(e.target) && !menu.contains(e.target)) close();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
    menu.addEventListener("click", (e) => {
      const li = e.target.closest(".tz-option");
      if (!li) return;
      selectedTz = li.dataset.value || null;
      saveTz(selectedTz);
      refresh();
      close();
      populateTzMenu();
      onFilterChange();
    });
    refresh();
  }

  function populateTzMenu() {
    const menu = $("#tz-menu");
    menu.innerHTML = "";
    let lastGroup = null;
    for (const o of TZ_OPTIONS) {
      if (o.group !== lastGroup) {
        const groupLabel = document.createElement("li");
        groupLabel.className = "tz-group-label";
        groupLabel.textContent = o.group;
        menu.appendChild(groupLabel);
        lastGroup = o.group;
      }
      const li = document.createElement("li");
      li.className = "tz-option";
      li.dataset.value = o.value;
      li.setAttribute("role", "option");
      const isSel = (o.value || null) === selectedTz;
      li.setAttribute("aria-selected", String(isSel));
      const off = offsetLabel(o.value || null);
      li.innerHTML = `<span>${escapeHtml(o.label)}</span><span class="tz-offset">${escapeHtml(off)}</span>`;
      menu.appendChild(li);
    }
  }

  function updateTzPill() {
    const label = $("#tz-pill-label");
    if (label) label.textContent = currentTzLabel();
  }

  // ────────────────────────────────────────────────────────────
  // Team and venue combos
  // ────────────────────────────────────────────────────────────
  function buildTeamList() {
    if (!allData) return;
    const ul = $("#team-options");
    ul.innerHTML = "";
    const teams = allData.facets?.teams || [];
    for (const team of teams) {
      const li = document.createElement("li");
      li.className = "combo-option";
      li.dataset.id = team.id;
      li.dataset.search = teamSearchText(team);
      li.setAttribute("role", "option");
      const selected = filters.teams.includes(team.id);
      li.setAttribute("aria-selected", String(selected));
      li.innerHTML = `<span class="opt-flag">${team.flag || "🏳️"}</span><span>${escapeHtml(teamDisplayName(team))}${teamRankSpan(team)}</span><span class="opt-meta">${escapeHtml(team.abbr || "")}</span>`;
      li.addEventListener("click", () => {
        toggleTeam(team.id);
        buildTeamList();
        renderTeamChips();
        onFilterChange();
      });
      ul.appendChild(li);
    }
  }

  function toggleTeam(id) {
    const sid = String(id);
    const idx = filters.teams.findIndex((x) => String(x) === sid);
    if (idx >= 0) filters.teams.splice(idx, 1);
    else if (filters.teams.length < 8) filters.teams.push(sid);
    else filters.teams.splice(0, 1), filters.teams.push(sid);
  }

  function renderTeamChips() {
    const wrap = $("#team-chips");
    wrap.innerHTML = "";
    if (!allData) return;
    const teams = allData.facets?.teams || [];
    for (const id of filters.teams) {
      const team = teams.find((t) => String(t.id) === String(id));
      if (!team) continue;
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = `<span class="opt-flag">${team.flag || "🏳️"}</span><span>${escapeHtml(teamDisplayName(team))}${teamRankSpan(team)}</span><button type="button" aria-label="remove">×</button>`;
      chip.querySelector("button").addEventListener("click", () => {
        toggleTeam(id);
        renderTeamChips();
        buildTeamList();
        onFilterChange();
      });
      wrap.appendChild(chip);
    }
  }

  function wireTeamCombo() {
    const input = $("#team-search");
    const ul = $("#team-options");
    const caret = input.parentElement?.querySelector(".combo-caret");
    input.addEventListener("focus", () => { ul.hidden = false; filterTeamList(); });
    input.addEventListener("input", filterTeamList);
    caret?.addEventListener("click", () => {
      ul.hidden = !ul.hidden;
      if (!ul.hidden) filterTeamList();
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".combo--teams")) ul.hidden = true;
    });
  }

  function filterTeamList() {
    const q = $("#team-search").value.trim().toLowerCase();
    $$("#team-options .combo-option").forEach((li) => {
      const corpus = li.dataset.search || li.textContent.toLowerCase();
      li.hidden = q && !corpus.includes(q);
    });
  }

  function buildVenueList() {
    if (!allData) return;
    const ul = $("#venue-options");
    ul.innerHTML = "";
    const venues = allData.facets?.venues || [];
    for (const v of venues) {
      const li = document.createElement("li");
      li.className = "combo-option";
      li.setAttribute("role", "option");
      const selected = filters.venues.includes(v.name);
      li.setAttribute("aria-selected", String(selected));
      const count = v.match_count || 0;
      li.innerHTML = `<span>${escapeHtml(v.name)}</span><span class="opt-meta">${count}</span>`;
      li.addEventListener("click", () => {
        toggleVenue(v.name);
        buildVenueList();
        updateVenueTrigger();
        onFilterChange();
      });
      ul.appendChild(li);
    }
    updateVenueTrigger();
  }

  function toggleVenue(name) {
    const idx = filters.venues.indexOf(name);
    if (idx >= 0) filters.venues.splice(idx, 1);
    else if (filters.venues.length < 16) filters.venues.push(name);
  }

  function updateVenueTrigger() {
    const label = $("#venue-trigger-label");
    if (!label) return;
    if (!allData) { label.textContent = t("venues.all", { n: 0 }); return; }
    const total = allData.facets?.venues?.length || 0;
    if (filters.venues.length === 0) {
      label.textContent = t("venues.all", { n: total });
    } else if (filters.venues.length === 1) {
      label.textContent = t("venue.single", { name: filters.venues[0] });
    } else {
      label.textContent = `${filters.venues.length} / ${total}`;
    }
  }

  function wireVenueCombo() {
    const trigger = $("#venue-trigger");
    const ul = $("#venue-options");
    trigger.addEventListener("click", () => {
      const open = ul.hidden;
      ul.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".combo--venues")) {
        ul.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
      }
    });
  }

  function wireLangToggle() {
    $$(".lang-pill").forEach((p) => {
      p.addEventListener("click", () => setLang(p.dataset.lang));
    });
  }

  function loadView() {
    try {
      const raw = localStorage.getItem(VIEW_KEY);
      if (raw === "standings" || raw === "matches") return raw;
    } catch { /* ignore */ }
    return "matches";
  }
  function saveView(v) {
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ }
  }
  function setView(v) {
    currentView = (v === "standings") ? "standings" : "matches";
    saveView(currentView);
    updateViewPills();
    // Hide filters when in standings view
    const filterEl = $("#filters");
    if (filterEl) filterEl.hidden = currentView === "standings";
    if (allData) render();
  }
  function updateViewPills() {
    $$(".view-pill").forEach((p) => {
      const checked = p.dataset.value === currentView;
      p.setAttribute("aria-checked", checked ? "true" : "false");
      p.classList.toggle("is-active", checked);
    });
  }
  function wireViewSwitch() {
    $$(".view-pill").forEach((p) => {
      p.addEventListener("click", () => setView(p.dataset.value));
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
    render();
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
    allMatches = [];
    for (const day of data.days || []) {
      for (const m of day.matches) allMatches.push(m);
    }
    renderHeader(data);
    buildTeamList();
    buildVenueList();
    updateVenueTrigger();
    renderTeamChips();
    updateVenueTrigger();
    onFilterChange();
    renderBracket();
  }

  async function boot() {
    currentLang = loadLang();
    document.documentElement.lang = currentLang === "zh" ? "zh-Hans" : "en";
    filters = loadFilters();
    selectedTz = loadTz();
    currentView = loadView();
    setInitialPills();
    wirePills();
    wireTzPicker();
    populateTzMenu();
    updateTzPill();
    wireTeamCombo();
    wireVenueCombo();
    wireLangToggle();
    wireViewSwitch();
    wireClear();
    renderTeamChips();
    // Apply translations to all data-i18n elements on first paint
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    $$("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    $$("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
    updateLangPills();
    updateViewPills();
    updateVenueTrigger();
    // Apply persisted view (hide filters if standings)
    if (currentView === "standings") {
      const filterEl = $("#filters");
      if (filterEl) filterEl.hidden = true;
    }

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

    setInterval(() => {
      if (allData) {
        render();
        renderHeader(allData);
      }
    }, RERENDER_TICK_MS);
  }

  function showError(err) {
    const content = $("#content");
    content.innerHTML = "";
    const div = document.createElement("div");
    div.className = "error";
    div.innerHTML = `<strong>${escapeHtml(t("error.title"))}</strong><br />${escapeHtml(String(err))}<br /><br />${escapeHtml(t("error.hint"))}`;
    content.appendChild(div);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();