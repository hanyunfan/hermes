// app.js — render the WC 2026 daily preview from data/matches.json
// Pure ES2022, no build step, no dependencies. Caches the JSON in
// sessionStorage so navigating away and back is instant.

(() => {
  "use strict";

  const JSON_URL = "data/matches.json";
  const CACHE_KEY = "wc2026.matches.v1";
  const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 min

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
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
    } catch {
      return "local";
    }
  }

  function browserZone() {
    try {
      return new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
        .formatToParts(new Date())
        .find((p) => p.type === "timeZoneName")?.value || "";
    } catch {
      return "";
    }
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
      // Build a Date whose wall clock equals the requested zone's "now".
      const partsNow = new Date();
      const localStr = partsNow.toLocaleString("en-US", { timeZone: tzName });
      return new Date(localStr);
    } catch {
      return new Date();
    }
  }

  // ────────────────────────────────────────────────────────────
  // Render
  // ────────────────────────────────────────────────────────────
  function render(data) {
    const tz = data.timezone || localTimezone();
    const tzShort = browserZone();
    $("#tz-pill").textContent = `Times shown in ${tz}${tzShort ? ` (${tzShort})` : ""}`;

    const tour = data.tournament || {};
    if (tour.edition) {
      const t = $("#tournament-edition");
      t.textContent = `${tour.edition} edition`;
    }
    if (tour.dates || tour.host) {
      $("#tournament-subtitle").textContent =
        [tour.dates, tour.host].filter(Boolean).join(" · ");
    }

    // "Updated X ago"
    const updatedAt = new Date(data.generated_at);
    const updatedEl = $("#updated");
    const relNow = new Date();
    updatedEl.textContent = `Updated ${formatRelative(updatedAt, relNow)}`;
    updatedEl.title = updatedAt.toLocaleString();

    const content = $("#content");
    content.innerHTML = "";

    const days = data.days || [];
    const dayTemplate = $("#day-template");
    const matchTemplate = $("#match-template");

    let totalMatches = 0;
    let anyScheduled = false;
    let anyLive = false;

    for (const day of days) {
      totalMatches += day.match_count;
      const section = dayTemplate.content.firstElementChild.cloneNode(true);
      section.classList.add(`is-${day.label.toLowerCase()}`);
      $(".day-title", section).textContent =
        day.label === "Today"
          ? `Today · ${friendlyDate(day.date)}`
          : day.label === "Tomorrow"
            ? `Tomorrow · ${friendlyDate(day.date)}`
            : friendlyDate(day.date);
      $(".day-count", section).textContent =
        day.match_count === 0
          ? "no matches"
          : day.match_count === 1
            ? "1 match"
            : `${day.match_count} matches`;

      const list = $(".matches", section);
      if (day.matches.length === 0) {
        const li = document.createElement("li");
        li.className = "match-empty";
        li.textContent = day.label === "Today"
          ? "No World Cup matches scheduled for today. 🏖️"
          : "No World Cup matches scheduled for tomorrow.";
        list.appendChild(li);
      } else {
        for (const m of day.matches) {
          list.appendChild(renderMatch(m, matchTemplate));
          if (m.status === "LIVE") anyLive = true;
          if (m.status === "SCHEDULED") anyScheduled = true;
        }
      }

      content.appendChild(section);
    }

    // Empty / over state
    if (totalMatches === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.innerHTML = `<strong>No matches today or tomorrow.</strong><br />The 2026 World Cup runs Jun 11 – Jul 19. Check back later.`;
      content.appendChild(empty);
    }

    return { totalMatches, anyScheduled, anyLive };
  }

  function friendlyDate(iso) {
    try {
      const d = new Date(iso + "T00:00:00");
      return d.toLocaleDateString(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      });
    } catch {
      return iso;
    }
  }

  function renderMatch(m, tpl) {
    const li = tpl.content.firstElementChild.cloneNode(true);
    if (m.status === "LIVE") li.classList.add("is-live");
    if (m.status === "FINAL") li.classList.add("is-final");

    $(".time-main", li).textContent = m.kickoff_time || "—";

    const statusEl = $(".time-status", li);
    if (m.status === "LIVE") {
      statusEl.textContent = m.status_short || "LIVE";
      statusEl.classList.add("is-live");
    } else if (m.status === "FINAL") {
      statusEl.textContent = m.status_short || "Final";
      statusEl.classList.add("is-final");
    } else {
      // SCHEDULED — show relative countdown, but if we're past kickoff the
      // API snapshot is stale; surface that clearly and force a refresh.
      const tz = tzName();
      const target = nowInZone(tz);
      const kickoff = new Date(m.kickoff_utc);
      const diffMs = kickoff.getTime() - target.getTime();
      if (diffMs <= 0) {
        statusEl.textContent = "Starting soon";
        statusEl.title = "Auto-refresh in a moment…";
        triggerBackgroundRefresh();
      } else {
        statusEl.textContent = formatRelative(kickoff, target);
        statusEl.title = kickoff.toLocaleString();
      }
    }

    populateTeam(li, ".home", m.home, m);
    populateTeam(li, ".away", m.away, m);

    $(".stage", li).textContent = m.stage || "World Cup";
    $(".venue", li).textContent = m.venue?.name
      ? `${m.venue.name}${m.venue.city ? `, ${m.venue.city}` : ""}`
      : "—";
    $(".venue", li).title = m.venue?.name
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
    const logo = $(".team-logo", root);
    if (team.logo) logo.src = team.logo;
    logo.alt = team.name || "";
    $(".team-flag", root).textContent = team.flag || "🏳️";
    const nameEl = $(".team-name", root);
    // Prefer the full name; ellipsis handles overflow on narrow viewports.
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

  // Mirror of timezone from the data so render can use it for countdowns
  function tzName() {
    const cached = readCache();
    return cached?.timezone || localTimezone();
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
        render(data);
      } catch {
        /* keep last render */
      } finally {
        backgroundRefreshScheduled = false;
      }
    }, 15_000);
  }

  async function boot() {
    const refreshBtn = $("#refresh-btn");
    refreshBtn.addEventListener("click", async () => {
      refreshBtn.classList.add("spinning");
      try {
        const data = await loadMatches(true);
        render(data);
      } catch (e) {
        showError(e);
      } finally {
        setTimeout(() => refreshBtn.classList.remove("spinning"), 400);
      }
    });

    try {
      const data = await loadMatches();
      render(data);
    } catch (e) {
      // Try cache as a fallback so the page is never blank
      const cached = readCache();
      if (cached) {
        render(cached);
      } else {
        showError(e);
      }
    }

    // Periodic background refresh
    setInterval(async () => {
      try {
        const data = await loadMatches(true);
        render(data);
      } catch {
        /* keep last render */
      }
    }, REFRESH_INTERVAL_MS);
  }

  function showError(err) {
    const content = $("#content");
    content.innerHTML = "";
    const div = document.createElement("div");
    div.className = "error";
    div.innerHTML = `<strong>Couldn't load match data.</strong><br />${escapeHtml(String(err))}<br /><br />Try the refresh button.`;
    content.appendChild(div);
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
