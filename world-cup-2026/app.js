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

  // R32 matches in bracket-slot order (slot 1..16). ESPN assigns R32 IDs
  // in kickoff-time order, but the knockout bracket tree is fixed: this
  // array pins each R32 match to its bracket slot so the connecting
  // lines and visual pairing into R16/QF reflect the actual FIFA bracket,
  // not the broadcast schedule. Mirrors R32_BRACKET in the odds section
  // (renderOddsBody) — kept separate because odds also needs the
  // group/position fields for slot rendering.
  // R32 matches in **bracket** order (slot 1..16). ESPN's gameId
  // ordering follows kickoff time and does not match the FIFA bracket
  // structure — e.g. ENG vs COD (M80, 11:00 AM ET) is one of the last
  // R32 matches in the upper half but lands in the middle of an
  // ascending gameId list. This array pins each match to its actual
  // bracket slot so the bracket tree matches FIFA's published layout.
  //
  // NOTE: Slots 1–8 vs 9–16 follow FIFA's own M73–M80 / M81–88
  // labeling for the R32 round, but those labels do NOT correspond to
  // the two SF halves. The SF halves are interleaved by design (M101 =
  // M97 + M98 mixes upper R32 slots 1,2,3,5 with lower slots 9,10,11,12)
  // so e.g. France (slot 2, M97) and Norway (slot 4, M99) end up on
  // opposite wings even though both are "upper" R32 slots by M-number.
  // See HALF_BY_R32_SLOT below for the per-slot SF-half assignment.
  //
  // NOTE: This ordering differs from R32_BRACKET below (the odds
  // section, which iterates by kickoff time so users see upcoming
  // matchups chronologically). Pairing data here is what the bracket
  // geometry uses.
  //
  //   R16-1: (1, 3)   R16-2: (2, 5)   R16-3: (4, 6)   R16-4: (7, 8)
  //   R16-5: (9, 10)  R16-6: (11, 12) R16-7: (13, 15) R16-8: (14, 16)
  const R32_BRACKET_IDS = [
    // Upper half (slots 1–8, M73–M80)
    "760486",  //  1  M73  2A vs 2B       (RSA vs CAN)
    "760492",  //  2  M77  1I vs Best 3rd  (FRA vs SWE)
    "760488",  //  3  M75  1F vs 2C       (NED vs MAR)
    "760490",  //  4  M78  2E vs 2I       (CIV vs NOR)
    "760489",  //  5  M74  1E vs Best 3rd (GER vs PAR)
    "760487",  //  6  M76  1C vs 2F       (BRA vs JPN)
    "760491",  //  7  M79  1A vs Best 3rd (MEX vs ECU)
    "760495",  //  8  M80  1L vs Best 3rd (ENG vs COD)
    // Lower half (slots 9–16, M81–M88)
    "760494",  //  9  M81  1D vs Best 3rd (USA vs BIH)
    "760493",  // 10  M82  1G vs Best 3rd (BEL vs SEN)
    "760496",  // 11  M83  2K vs 2L       (POR vs CRO)
    "760497",  // 12  M84  1H vs 2J       (ESP vs AUT)
    "760498",  // 13  M85  1B vs Best 3rd (SUI vs ALG)
    "760500",  // 14  M86  1J vs 2H       (ARG vs CPV)
    "760501",  // 15  M87  1K vs Best 3rd (COL vs GHA)
    "760499",  // 16  M88  2D vs 2G       (AUS vs EGY)
  ];

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
      "view.scorers": "Scorers",
      "view.weekly": "Weekly Picks",
      "view.odds": "Knockout Odds",
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
      "match.countdown": "#{n} to go",
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
      "scorers.title": "Top Scorers",
      "scorers.hint": "Left: live counts for this tournament. Right: all-time men's WC totals — the 2026 baseline is merged in live, so Mbappé, Cristiano Ronaldo and others climb the ranks as the tournament progresses.",
      "scorers.section.current": "This Tournament · WC 2026",
      "scorers.section.alltime": "All-Time · 1930–2026",
      "scorers.col.player": "Player",
      "scorers.col.team": "Team",
      "scorers.col.goals": "Goals",
      "scorers.col.mp": "MP",
      "scorers.col.assists": "A",
      "scorers.col.country": "Country",
      "scorers.col.tournaments": "Tournaments",
      "scorers.col.span": "Span",
      "scorers.col.penalties": "PK",
      "scorers.empty.current": "No goals yet — the tournament kicked off June 11. Check back after the first match.",
      "scorers.empty.alltime": "All-time list is unavailable.",
      "scorers.notes": "MP = matches played · A = assists · PK = penalty kicks · ▲/▼ shows rank change after merging WC 2026 goals · pre-2026 baseline covers the men's final tournament, 1930–2022.",
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
      "bracket.liveLink": "FIFA live scores (Google)",
      "footer.data": "Data:",
      "footer.refresh": "Refreshed every 20 min during the match window (11:00–04:00 CT) and once overnight at 04:00 CT",
      "footer.source": "Source",
      "tz.times.in": "Times in {tz}",

      // 本周看点 tab (Weekly Picks)
      "weekly.title": "Weekly Picks",
      "weekly.hint": "Hand-curated picks for this matchday / round — which matches are worth your evening, which you can skip, and why. Stakes (advancement math) are auto-computed; the rest is written by an analyst after reviewing the round's fixtures.",
      "weekly.verdict.must": "Must watch",
      "weekly.verdict.lively": "Worth a look",
      "weekly.verdict.skip": "Skippable",
      "weekly.score": "Score {n}/5",
      "weekly.match.kickoff": "Kickoff",
      "weekly.match.stage": "Stage",
      "weekly.match.venue": "Venue",
      "weekly.match.stakes": "Stakes",
      "weekly.match.watch": "What to watch",
      "weekly.match.players": "Players to watch",
      "weekly.match.news": "News angle",
      "weekly.match.records": "Record watch",
      "weekly.match.why_skip": "Why you can skip",
      "weekly.match.links": "More",
      "weekly.empty.title": "No picks yet for this round.",
      "weekly.empty.hint": "Auto-refresh writes a skeleton every cycle. The analyst fills in the rest on request — ask for this round's analysis and the picks will appear here within minutes.",
      "weekly.empty.ask": "Ask in Telegram for this round's picks.",
      "weekly.stale.title": "These picks are from {round}.",
      "weekly.stale.hint": "The next batch of picks is generated when the analyst reviews the round's fixtures. Check back later, or ask in Telegram.",
      "weekly.manual.fresh": "Analyst pick · {when}",
      "weekly.manual.never": "Skeleton only — awaiting analyst review.",
      "weekly.manual.partial": "Analyst pick in progress · {n}/{total} matches reviewed.",
      "weekly.section.must": "Must watch",
      "weekly.section.lively": "Worth a look",
      "weekly.section.skip": "Skippable",
      "weekly.day.today": "Today",
      "weekly.day.tomorrow": "Tomorrow",

      // 出线概率 tab (Knockout Odds)
      "odds.title": "Knockout Odds",
      "odds.hint": "Each R32 matchup and the teams that could fill each slot, computed by Monte Carlo simulation over the remaining group-stage matches. Top 2 + 8 best 3rd advance to the Round of 32.",
      "odds.sims": "Sims",
      "odds.legend.1": "1st in group",
      "odds.legend.2": "2nd",
      "odds.legend.3": "3rd (best 8 advance)",
      "odds.legend.4": "4th (out)",
      "odds.pts": "pts",
      "odds.advance.tip": "Chance of advancing to the Round of 32 (top 2 + best 3rd)",
      "odds.empty.title": "No knockout odds yet.",
      "odds.empty.hint": "Run scripts/compute_knockout_odds.py to generate.",
      "odds.group.complete": "Group complete",
      "odds.slot.winner": "Winner of Group {group}",
      "odds.slot.runnerup": "Runner-up of Group {group}",
      "odds.slot.best3rd": "Best 3rd from {groups}",
      "odds.matchup.vs": "vs",
      "odds.matchup.home": "Home",
      "odds.matchup.away": "Away",
    },
    zh: {
      "page.title": "2026 国际足联世界杯 — 每日预告",
      "tournament.edition": "第 23 届",
      "tournament.dates": "2026年6月11日 – 7月19日 · 美国 · 加拿大 · 墨西哥",
      "view.label": "视图",
      "view.matches": "比赛",
      "view.standings": "积分",
      "view.scorers": "射手榜",
      "view.weekly": "本周看点",
      "view.odds": "出线概率",
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
      "match.countdown": "倒计时 #{n} 场",
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
      "scorers.title": "射手榜",
      "scorers.hint": "左侧：2026 世界杯实时数据。右侧：男足世界杯历史总进球榜，2026 进球实时合并，姆巴佩、C罗等球员随比赛推进不断飙升。",
      "scorers.section.current": "本届 · 2026 世界杯",
      "scorers.section.alltime": "历史总榜 · 1930–2026",
      "scorers.col.player": "球员",
      "scorers.col.team": "球队",
      "scorers.col.goals": "进球",
      "scorers.col.mp": "出场",
      "scorers.col.assists": "助",
      "scorers.col.country": "国家",
      "scorers.col.tournaments": "参赛届数",
      "scorers.col.span": "跨度",
      "scorers.col.penalties": "点",
      "scorers.empty.current": "尚未开赛（6 月 11 日揭幕），暂无进球数据。",
      "scorers.empty.alltime": "历史榜单暂不可用。",
      "scorers.notes": "出场 = 出场场次 · 助 = 助攻 · 点 = 点球；▲/▼ 为合并 2026 进球后的排名变化；2026 之前基线涵盖 1930–2022 年男足世界杯决赛圈。",
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
      "bracket.liveLink": "FIFA 官方实时比分（Google）",
      "footer.data": "数据：",
      "footer.refresh": "比赛时段（11:00–04:00 CT）每 20 分钟刷新一次，凌晨 04:00 CT 再补一次冷数据",
      "footer.source": "源码",
      "tz.times.in": "时间显示：{tz}",

      // AI 推荐今日必看 tab
      "weekly.title": "本周看点",
      "weekly.hint": "本轮/本周挑出的场次——哪场值得熬到深夜，哪场可以放心跳过，理由是什么。球队升降级关键由程序自动算；其余字段由分析师根据当日对阵手写。",
      "weekly.verdict.must": "必看",
      "weekly.verdict.lively": "可以看看",
      "weekly.verdict.skip": "可跳过",
      "weekly.score": "推荐分 {n}/5",
      "weekly.match.kickoff": "开球",
      "weekly.match.stage": "阶段",
      "weekly.match.venue": "球场",
      "weekly.match.stakes": "球队升降级关键",
      "weekly.match.watch": "看点",
      "weekly.match.players": "重点球员",
      "weekly.match.news": "新闻关注点",
      "weekly.match.records": "破纪录可能性",
      "weekly.match.why_skip": "跳过的理由",
      "weekly.match.links": "更多",
      "weekly.empty.title": "本轮还没有推荐。",
      "weekly.empty.hint": "每次自动刷新会写入骨架数据，分析师补充主观判断后在 Telegram 留言即可，分钟级上线。",
      "weekly.empty.ask": "在 Telegram 问一句\"本周看哪场\"即可生成。",
      "weekly.stale.title": "当前推荐来自 {date}。",
      "weekly.stale.hint": "本轮推荐会在分析师审阅对阵后生成，请稍后再来，或在 Telegram 留言。",
      "weekly.manual.fresh": "分析师已选 · {when}",
      "weekly.manual.never": "仅有骨架，等待分析师审阅。",
      "weekly.manual.partial": "分析师进行中 · {n}/{total} 场已评。",
      "weekly.section.must": "必看场次",
      "weekly.section.lively": "可以看看",
      "weekly.section.skip": "可跳过",

      // 出线概率 tab (Knockout Odds)
      "odds.title": "出线概率",
      "odds.hint": "每个 1/8 决赛对阵的两端可能由哪些队填上（蒙特卡洛模拟 10,000 次）。前 2 名 + 8 个最佳第 3 名晋级。",
      "odds.sims": "模拟次数",
      "odds.legend.1": "小组第 1",
      "odds.legend.2": "小组第 2",
      "odds.legend.3": "第 3（前 8 晋级）",
      "odds.legend.4": "第 4（出局）",
      "odds.pts": "分",
      "odds.advance.tip": "晋级 1/8 决赛的概率（前 2 + 8 个最佳第 3）",
      "odds.empty.title": "暂无出线概率数据。",
      "odds.empty.hint": "运行 scripts/compute_knockout_odds.py 生成。",
      "odds.group.complete": "小组赛已结束",
      "odds.slot.winner": "{group} 组第 1 名",
      "odds.slot.runnerup": "{group} 组第 2 名",
      "odds.slot.best3rd": "最佳第 3 名（{groups}）",
      "odds.matchup.vs": "vs",
      "odds.matchup.home": "主场",
      "odds.matchup.away": "客场",
    },
  };

  let currentLang = "en";
  function i18n(key, vars = {}) {
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
    $$("[data-i18n]").forEach((el) => { el.textContent = i18n(el.dataset.i18n); });
    $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = i18n(el.dataset.i18nPlaceholder); });
    $$("[data-i18n-title]").forEach((el) => { el.title = i18n(el.dataset.i18nTitle, { tz: "Local" }); });
    $$("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", i18n(el.dataset.i18nAria)); });
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
    if (abs < minute) label = i18n(key);
    else if (abs < hour) label = past ? i18n("relative.m.ago", { n: Math.round(abs / minute) }) : i18n("relative.in.m", { n: Math.round(abs / minute) });
    else if (abs < day) label = past ? i18n("relative.h.ago", { n: Math.round(abs / hour) }) : i18n("relative.in.h", { n: Math.round(abs / hour) });
    else label = past ? i18n("relative.d.ago", { n: Math.round(abs / day) }) : i18n("relative.in.d", { n: Math.round(abs / day) });
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

  // Weekday abbreviation, language-aware. EN: "Mon"/"Tue"/...; ZH: "周一"/"周二"/...
  const WEEKDAY_EN_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const WEEKDAY_ZH_SHORT = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  function weekdayShort(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00Z"); // ISO is YYYY-MM-DD → UTC midnight, day-of-week is stable
    if (isNaN(d.getTime())) return "";
    const dow = d.getUTCDay();
    return currentLang === "zh" ? WEEKDAY_ZH_SHORT[dow] : WEEKDAY_EN_SHORT[dow];
  }
  // Format an ISO date with a trailing weekday abbrev, in the current language.
  // Used for headers, range labels, and anywhere a bare "YYYY-MM-DD" is shown.
  function formatDateWithDow(iso) {
    if (!iso) return "";
    return `${iso} ${weekdayShort(iso)}`;
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
  // matchId -> reverse position in tournament (1 = Final, 104 = first
  // match). Used by the per-card "倒计时 #N" badge so each scheduled
  // match shows its place counting backwards from the Final.
  let matchCountdown = new Map();
  let currentView = "matches";  // matches | standings | scorers | weekly | odds

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
    if (currentView === "scorers") {
      renderScorers();
      return;
    }
    if (currentView === "weekly") {
      renderWeekly();
      return;
    }
    if (currentView === "odds") {
      renderOdds();
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
      countEl.textContent = matches.length === 1 ? i18n("1.match") : i18n("n.matches", { n: matches.length });
    }

    if (matches.length === 0) {
      const hasFilters = !isDefaultFilters();
      const div = document.createElement("div");
      div.className = "empty";
      div.innerHTML = `<div>${escapeHtml(hasFilters ? i18n("empty.filtered") : i18n("empty.title"))}</div>
        <div class="empty-hint">${escapeHtml(i18n("empty.hint"))}</div>`;
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

    grid.appendChild(buildWing("past", i18n("wing.past"), past, "wing-past-empty"));
    grid.appendChild(buildWing("today", i18n("wing.today"), today, "wing-today-empty"));
    grid.appendChild(buildWing("future", i18n("wing.future"), future, "wing-future-empty"));

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
      empty.textContent = i18n(emptyKey);
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
        label: d === today ? i18n("day.today", { date: formatDateWithDow(d) }) : d === tomorrow ? i18n("day.tomorrow", { date: formatDateWithDow(d) }) : i18n("day.other", { date: formatDateWithDow(d) }),
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
      div.innerHTML = `<div>${escapeHtml(i18n("standings.empty"))}</div>`;
      content.appendChild(div);
      return;
    }

    const wrap = document.createElement("section");
    wrap.className = "standings-section";
    const head = document.createElement("header");
    head.className = "standings-head";
    head.innerHTML = `<h2 class="standings-title">${escapeHtml(i18n("standings.title"))}</h2>
      <p class="standings-hint">${escapeHtml(i18n("standings.hint"))}</p>`;
    wrap.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "standings-grid";
    for (const g of groups) grid.appendChild(buildGroupTable(g));
    wrap.appendChild(grid);

    const note = document.createElement("p");
    note.className = "standings-notes";
    note.textContent = i18n("standings.notes");
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
          <th class="col-team">${escapeHtml(i18n("standings.col.team"))}</th>
          <th class="col-rank">#</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.mp"))}">${escapeHtml(i18n("standings.col.mp"))}</th>
          <th class="col-num col-pts" title="${escapeHtml(i18n("standings.col.pts"))}">${escapeHtml(i18n("standings.col.pts"))}</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.w"))}">${escapeHtml(i18n("standings.col.w"))}</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.d"))}">${escapeHtml(i18n("standings.col.d"))}</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.l"))}">${escapeHtml(i18n("standings.col.l"))}</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.gf"))}">${escapeHtml(i18n("standings.col.gf"))}</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.ga"))}">${escapeHtml(i18n("standings.col.ga"))}</th>
          <th class="col-num" title="${escapeHtml(i18n("standings.col.gd"))}">${escapeHtml(i18n("standings.col.gd"))}</th>
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
        <td class="col-team">
          <span class="team-flag">${escapeHtml(e.team.flag || "")}</span>
          <span class="team-short">${escapeHtml(teamDisplayName(e.team))}${teamRankSpan(e.team)}</span>
        </td>
        <td class="col-rank">
          <span class="rank-num">${rank}</span>
          ${rank === 1 || rank === 2 ? `<span class="qual-q" title="${escapeHtml(i18n("standings.q"))}">Q</span>` : ""}
        </td>
        <td class="col-num">${e.mp}</td>
        <td class="col-num col-pts"><strong>${e.pts}</strong></td>
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


  // ─────────────────────────────────────────────────────────────
  // Render: scorers — two side-by-side panes
  //   • Current tournament — aggregated from each match's `incidents`
  //     (kind === "goal"). Re-derives on every render so it tracks the
  //     rolling JSON without a separate API call.
  //   • All-time — static list baked into matches.json under
  //     `scorers_history`. Covers 1930–2022, men's final tournament.
  // ─────────────────────────────────────────────────────────────
  function aggregateCurrentScorers(matches) {
    const byPlayer = new Map();  // key -> { player, team_id, team_name, team_zh, flag, goals, assists, matches:Set, penalty_kicks, minutes:[] }
    function bumpSet(m, key) {
      const cur = byPlayer.get(key);
      if (cur) return cur;
      const next = {
        player: m.player,
        player_zh: null,  // filled in lazily via team search if available
        team_id: m.team_id,
        team_name: m.team,
        team_zh: null,
        flag: "",
        goals: 0,
        assists: 0,
        penalty_kicks: 0,
        matches: new Set(),
        minutes: [],
      };
      byPlayer.set(key, next);
      return next;
    }

    // First pass — count goals, assists, penalties, distinct matches,
    // and remember the most recent minute scored.
    for (const match of matches) {
      const incs = match.incidents || [];
      if (incs.length === 0) continue;
      const playerTeam = { home: match.home, away: match.away };
      for (const inc of incs) {
        if (inc.kind !== "goal") continue;
        // ESPN tags own goals with the team that benefited from them,
        // not the player. Detect via the incident text and skip the
        // player entry — their name should not appear in the scorers
        // list. We still let the legitimate scorer through.
        const txt = (inc.text || "").toLowerCase();
        if (txt.includes("own goal") || txt.includes("own-goal")) continue;
        const scorerKey = `goal|${inc.player}|${inc.team_id || inc.team || "?"}`;
        const s = bumpSet(inc, scorerKey);
        if (match.id) s.matches.add(match.id);
        s.goals += 1;
        s.minutes.push(inc.minute || "");
        // ESPN encodes the scoring text in `text` — it usually mentions
        // "(penalty kick)" / "Penalty" when it's a PK. Cheap string
        // sniff; we don't have a structured field.
        const text = (inc.text || "").toLowerCase();
        if (text.includes("penalty")) s.penalty_kicks += 1;
        // Walk assist: the same match's incidents may carry an assist
        // on the goal itself (`inc.assist`), or there may be a separate
        // assist-flavored entry. ESPN nests assists inside the goal
        // incident's `text` field, so we read it from `inc.assist`.
        if (inc.assist) {
          // The assist is attributed to the OTHER side.
          const otherSide = inc.team_side === "home" ? "away" : "home";
          const assistKey = `goal|${inc.assist}|${(playerTeam[otherSide] || {}).id || "?"}`;
          // We may not have a separate incident for the assister;
          // ensure an entry exists.
          const a = byPlayer.get(assistKey) || {
            player: inc.assist,
            player_zh: null,
            team_id: (playerTeam[otherSide] || {}).id,
            team_name: (playerTeam[otherSide] || {}).name,
            team_zh: (playerTeam[otherSide] || {}).name_zh,
            flag: (playerTeam[otherSide] || {}).flag,
            goals: 0,
            assists: 0,
            penalty_kicks: 0,
            matches: new Set(),
            minutes: [],
          };
          byPlayer.set(assistKey, a);
          if (match.id) a.matches.add(match.id);
          a.assists += 1;
        }
      }
    }

    // Second pass — fill in team flag / Chinese name from the match
    // sides when we have the team_id handy.
    for (const m of matches) {
      for (const side of [m.home, m.away]) {
        for (const entry of byPlayer.values()) {
          if (entry.team_id && String(entry.team_id) === String(side.id)) {
            if (!entry.flag && side.flag) entry.flag = side.flag;
            if (!entry.team_zh && side.name_zh) entry.team_zh = side.name_zh;
          }
        }
      }
    }

    // Materialize — promote Set to count, freeze, sort by:
    //   1. goals desc (primary)
    //   2. assists desc
    //   3. matches_played desc ("出场时间" — proxy for total
    //      minutes, since ESPN doesn't ship per-player minutes)
    //   4. player name (final tiebreak, deterministic)
    const out = [];
    for (const e of byPlayer.values()) {
      out.push({
        player: e.player,
        team_id: e.team_id,
        team_name: e.team_name,
        team_zh: e.team_zh,
        flag: e.flag,
        goals: e.goals,
        assists: e.assists,
        penalty_kicks: e.penalty_kicks,
        matches_played: e.matches.size,
        minutes: e.minutes,
      });
    }
    out.sort((a, b) =>
      (b.goals - a.goals) ||
      (b.assists - a.assists) ||
      (b.matches_played - a.matches_played) ||
      a.player.localeCompare(b.player)
    );
    return out;
  }

    // ─────────────────────────────────────────────────────────────
  // Merge current-tournament goals into the all-time list.
  //
  // The all-time list lives in matches.json under `scorers_history`
  // and is frozen at the end of the 2022 World Cup (Klose 16,
  // Ronaldo 15, …). For WC 2026 we want the leaderboard to keep
  // moving: every goal scored in 2026 should add to a player's
  // career total and shift the rankings live.
  //
  // This function:
  //   1. Takes the pre-2026 baseline.
  //   2. Adds the current-tournament goals produced by
  //      aggregateCurrentScorers() to the matching player.
  //   3. Updates that player's span and tournament list to include
  //      2026 (if they hadn't been there before).
  //   4. Inserts brand-new entries for WC 2026 scorers who weren't
  //      in the pre-2026 top 28 (e.g., a rookie with 1–2 goals).
  //   5. Re-sorts and re-ranks the merged list.
  //
  // Matching is name-based with a few normalizations:
  //   • Unicode NFD strip (so "Kylian Mbappé" matches "Kylian Mbappe")
  //   • Lowercase
  //   • Strip trailing "Jr/Sr/Junior/Senior" (Neymar Jr → Neymar)
  //   • A small alias map for known ESPN-vs-historical mismatches
  // ─────────────────────────────────────────────────────────────
  const PLAYER_ALIASES = {
    // ESPN may report the Brazilian forward as "Neymar" while the
    // historical entry also uses "Neymar" — they match on their own.
    // Keep this map as a safety net for any name drift we discover
    // in future data dumps.
  };
  function normPlayerName(s) {
    return (s || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")  // strip combining diacritics
      .replace(/\b(jr|sr|junior|senior)\.?$/i, "")
      .replace(/[^a-z0-9\s]/gi, "")
      .toLowerCase()
      .trim();
  }
  function buildMergedScorersList() {
    const baseline = (allData && allData.scorers_history) || [];
    // First, compute the natural pre-2026 ranking. The `rank` field
    // in HISTORICAL_SCORERS is a snapshot, but it doesn't always
    // match the natural all-time ordering (e.g., Lato has 10G like
    // five others but is filed at #22). Sort by goals desc with
    // the existing rank as the tiebreak, then number 1..N. This
    // is what we compare ▲/▼ deltas against — not the raw rank
    // field.
    const naturalBaseline = baseline
      .map((h) => ({ ...h, tournaments: Array.isArray(h.tournaments) ? [...h.tournaments] : [] }))
      .sort((a, b) => (b.goals - a.goals) || ((a.rank || 9999) - (b.rank || 9999)));
    naturalBaseline.forEach((e, i) => (e.natural_baseline_rank = i + 1));

    const merged = naturalBaseline.map((h) => ({ ...h }));
    const byName = new Map();
    for (const h of merged) byName.set(normPlayerName(h.player), h);

    const current = aggregateCurrentScorers(allMatches || []);
    for (const c of current) {
      const key = normPlayerName(c.player);
      let entry = byName.get(key);
      if (!entry && PLAYER_ALIASES[key]) {
        entry = byName.get(normPlayerName(PLAYER_ALIASES[key]));
      }
      if (entry) {
        entry.goals = (entry.goals || 0) + c.goals;
        if (!entry.tournaments.includes(2026)) {
          entry.tournaments = [...entry.tournaments, 2026].sort((a, b) => a - b);
        }
        // Extend span: single year (e.g. "1958") and range forms both
        // get a "–2026" appended; the merged span still reflects the
        // earliest WC year the player appeared in.
        if (/^\d{4}$/.test(entry.span)) {
          entry.span = entry.span + "\u20132026";
        } else {
          const m = (entry.span || "").match(/^(\d{4})[\u2013-](\d{4})$/);
          if (m) {
            const start = parseInt(m[1], 10);
            if (2026 > parseInt(m[2], 10)) entry.span = start + "\u20132026";
          }
        }
        entry.live_2026 = c.goals;  // hint for the front-end badge
      } else {
        // Brand new — first-time WC scorer or someone outside the
        // pre-2026 top 28.
        const newEntry = {
          rank: 999,
          player: c.player,
          player_zh: null,
          country: c.team_name,
          country_zh: c.team_zh,
          flag: c.flag,
          goals: c.goals,
          tournaments: [2026],
          span: "2026",
          live_2026: c.goals,
          natural_baseline_rank: null,  // not in pre-2026 top 28 — flag as NEW
        };
        merged.push(newEntry);
        byName.set(key, newEntry);
      }
    }

    // Re-rank by total goals desc. Within the same goal count, keep
    // the natural pre-2026 order so the ▲/▼ badges only reflect
    // real rank movement caused by 2026 goals (not alphabetic
    // tiebreak reshuffles). New entries (natural_baseline_rank =
    // null) go to the end of their goal group.
    merged.sort((a, b) => {
      if (b.goals !== a.goals) return b.goals - a.goals;
      const ar = a.natural_baseline_rank ?? 9999;
      const br = b.natural_baseline_rank ?? 9999;
      if (ar !== br) return ar - br;
      return a.player.localeCompare(b.player);
    });
    merged.forEach((e, i) => (e.rank = i + 1));
    return merged;
  }

  function renderScorers() {
    const content = $("#content");
    content.innerHTML = "";
    const countEl = $("#result-count");
    if (countEl) countEl.textContent = "";

    const wrap = document.createElement("section");
    wrap.className = "scorers-section";
    const head = document.createElement("header");
    head.className = "scorers-head";
    head.innerHTML = `<h2 class="scorers-title">${escapeHtml(i18n("scorers.title"))}</h2>
      <p class="scorers-hint">${escapeHtml(i18n("scorers.hint"))}</p>`;
    wrap.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "scorers-grid";

    // Pane 1 — current tournament (live)
    const current = aggregateCurrentScorers(allMatches || []);
    grid.appendChild(buildScorerPane("current", i18n("scorers.section.current"), current, /*limit*/ 20, /*kind*/ "current"));

    // Pane 2 — all-time (static + live merge of WC 2026 goals)
    const history = buildMergedScorersList();
    grid.appendChild(buildScorerPane("alltime", i18n("scorers.section.alltime"), history, /*limit*/ 30, /*kind*/ "alltime"));

    wrap.appendChild(grid);

    const note = document.createElement("p");
    note.className = "scorers-notes";
    note.textContent = i18n("scorers.notes");
    wrap.appendChild(note);

    content.appendChild(wrap);
  }

  function buildScorerPane(kind, title, rows, limit, rowKind) {
    const card = document.createElement("div");
    card.className = `scorer-card scorer-card--${kind}`;

    const head = document.createElement("header");
    head.className = "scorer-head";
    head.innerHTML = `<span class="scorer-pane-title">${escapeHtml(title)}</span>
      <span class="scorer-pane-count">${rows.length}</span>`;
    card.appendChild(head);

    const isEmpty = rows.length === 0;
    if (isEmpty) {
      const empty = document.createElement("div");
      empty.className = "empty";
      const key = kind === "current" ? "scorers.empty.current" : "scorers.empty.alltime";
      empty.innerHTML = `<div>${escapeHtml(i18n(key))}</div>`;
      card.appendChild(empty);
      return card;
    }

    const table = document.createElement("table");
    table.className = "scorer-table";
    const isCurrent = rowKind === "current";
    table.innerHTML = `
      <thead>
        <tr>
          <th class="col-num">#</th>
          <th class="col-player">${escapeHtml(i18n("scorers.col.player"))}</th>
          ${isCurrent
            ? `<th class="col-team">${escapeHtml(i18n("scorers.col.team"))}</th>
               <th class="col-num col-goals" title="${escapeHtml(i18n("scorers.col.goals"))}">${escapeHtml(i18n("scorers.col.goals"))}</th>
               <th class="col-num col-mp" title="${escapeHtml(i18n("scorers.col.mp"))}">${escapeHtml(i18n("scorers.col.mp"))}</th>
               <th class="col-num col-a" title="${escapeHtml(i18n("scorers.col.assists"))}">${escapeHtml(i18n("scorers.col.assists"))}</th>
               <th class="col-num col-pk" title="${escapeHtml(i18n("scorers.col.penalties"))}">${escapeHtml(i18n("scorers.col.penalties"))}</th>`
            : `<th class="col-team">${escapeHtml(i18n("scorers.col.country"))}</th>
               <th class="col-num col-goals" title="${escapeHtml(i18n("scorers.col.goals"))}">${escapeHtml(i18n("scorers.col.goals"))}</th>
               <th class="col-num col-tours" title="${escapeHtml(i18n("scorers.col.tournaments"))}">${escapeHtml(i18n("scorers.col.tournaments"))}</th>
               <th class="col-span" title="${escapeHtml(i18n("scorers.col.span"))}">${escapeHtml(i18n("scorers.col.span"))}</th>`}
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");
    const maxGoals = rows.length ? (rows[0].goals || 0) : 0;
    rows.slice(0, limit).forEach((r, i) => {
      const tr = document.createElement("tr");
      if (r.goals === maxGoals && maxGoals > 0) tr.classList.add("is-leader");
      const rank = r.rank || (i + 1);
      const playerName = isCurrent
        ? (currentLang === "zh" ? r.player : r.player)  // ESPN only ships English player names; keep as-is
        : (currentLang === "zh" && r.player_zh ? r.player_zh : r.player);
      const teamName = isCurrent
        ? (currentLang === "zh" && r.team_zh ? r.team_zh : r.team_name)
        : (currentLang === "zh" && r.country_zh ? r.country_zh : r.country);
      const flag = r.flag || "🏳️";
      if (isCurrent) {
        tr.innerHTML = `
          <td class="col-num col-rank"><span class="rank-num">${rank}</span></td>
          <td class="col-player"><span class="player-name">${escapeHtml(playerName || "—")}</span></td>
          <td class="col-team">
            <span class="team-flag">${escapeHtml(flag)}</span>
            <span class="team-short">${escapeHtml(teamName || "—")}</span>
          </td>
          <td class="col-num col-goals"><strong>${r.goals || 0}</strong></td>
          <td class="col-num">${r.matches_played || 0}</td>
          <td class="col-num">${r.assists || 0}</td>
          <td class="col-num ${r.penalty_kicks ? "is-pk" : ""}">${r.penalty_kicks || 0}</td>
        `;
      } else {
        // Render the tournaments list with the 2026 entry wrapped in
        // a special span so we can highlight the live portion.
        const tourParts = (r.tournaments || []).map((y) => {
          if (y === 2026) return `<span class="tour-2026">${y}</span>`;
          return `${y}`;
        });
        const tours = tourParts.join(" · ");
        // Rank-change badge: ▲ = climbed, ▼ = dropped, NEW = not in
        // pre-2026 baseline,  (empty) = unchanged. We compare
        // against natural_baseline_rank so the badge reflects real
        // rank movement (not internal list ordering quirks).
        let rankBadge = "";
        if (r.natural_baseline_rank == null) {
          rankBadge = `<span class="rank-badge rank-new" title="Not in pre-2026 top 28">NEW</span>`;
        } else if (r.natural_baseline_rank > rank) {
          const up = r.natural_baseline_rank - rank;
          rankBadge = `<span class="rank-badge rank-up" title="Climbed ${up} places after merging WC 2026 goals">▲${up}</span>`;
        } else if (r.natural_baseline_rank < rank) {
          const dn = rank - r.natural_baseline_rank;
          rankBadge = `<span class="rank-badge rank-down" title="Dropped ${dn} places after merging WC 2026 goals">▼${dn}</span>`;
        }
        tr.innerHTML = `
          <td class="col-num col-rank"><span class="rank-num">${rank}</span>${rankBadge}</td>
          <td class="col-player"><span class="player-name">${escapeHtml(playerName || "—")}</span></td>
          <td class="col-team">
            <span class="team-flag">${escapeHtml(flag)}</span>
            <span class="team-short">${escapeHtml(teamName || "—")}</span>
          </td>
          <td class="col-num col-goals"><strong>${r.goals || 0}</strong></td>
          <td class="col-num col-tours">${tours}</td>
          <td class="col-span">${escapeHtml(r.span || "")}</td>
        `;
      }
      tbody.appendChild(tr);
    });
    card.appendChild(table);
    return card;
  }


  // ────────────────────────────────────────────────────────────
  // Weekly Picks view
  //
  // Pulls from data/weekly-picks.json (a small, mostly-static file
  // refreshed by scripts/build_ai_recommend.py and curated by hand).
  // The view degrades gracefully: missing file → "no picks yet"
  // empty state; stale date → "these picks are from {date}".
  //
  // v2 schema supports multiple rounds per file. The user picks
  // which round to view via a pill row above the picks; the
  // selection is remembered in localStorage.
  // ────────────────────────────────────────────────────────────
  const WEEKLY_JSON_URL = "data/weekly-picks.json";
  const WEEKLY_CACHE_KEY = "wc2026.weekly.v1";
  const WEEKLY_CACHE_TTL_MS = 5 * 60 * 1000;
  const WEEKLY_ROUND_KEY = "wc2026.weekly.round";

  let weeklyData = null;
  let weeklyLoading = false;
  let weeklyRounds = [];      // normalized round list
  let weeklySelectedIdx = 0;  // index into weeklyRounds

  function normalizeWeeklyRounds(raw) {
    if (!raw) return [];
    // v2: {schema_version:2, rounds:[{...}]}
    if (raw.schema_version === 2 && Array.isArray(raw.rounds)) {
      return raw.rounds.map((r) => ({
        round_id: r.round_id || r.round_label?.zh || "round",
        stage_slug: r.stage_slug || (r.matches?.[0]?.stage_slug) || null,
        round_label: r.round_label || { zh: "本轮", en: "This round" },
        round_date_range: r.round_date_range || [],
        round_intro_zh: r.round_intro_zh || null,
        round_intro_en: r.round_intro_en || null,
        manual_count: r.manual_count || 0,
        last_manual_update: r.last_manual_update || null,
        matches: r.matches || [],
      }));
    }
    // v1 (legacy): single round at top level. Wrap it as a one-round list.
    if (Array.isArray(raw.matches)) {
      return [{
        round_id: "v1",
        stage_slug: raw.matches[0]?.stage_slug || null,
        round_label: raw.round_label || { zh: "本轮", en: "This round" },
        round_date_range: raw.round_date_range || [],
        round_intro_zh: raw.round_intro_zh || null,
        round_intro_en: raw.round_intro_en || null,
        manual_count: raw.manual_count || 0,
        last_manual_update: raw.last_manual_update || null,
        matches: raw.matches,
      }];
    }
    return [];
  }

  function pickDefaultRoundIdx(rounds, todayIso) {
    if (!rounds.length) return -1;
    const today = new Date(todayIso + "T00:00:00Z").getTime();
    const nowMs = Date.now();

    // Pick the round with the most unplayed matches (kickoff_utc > now),
    // so the user lands on the round that still has football to watch.
    // Tiebreakers: prefer manual content, then the soonest start date.
    const unplayedCount = (r) => {
      let n = 0;
      for (const m of (r.matches || [])) {
        const k = m.kickoff_utc;
        if (k && new Date(k).getTime() > nowMs) n++;
      }
      return n;
    };
    const scoreRound = (r) => {
      const has = (r.manual_count || 0) > 0 ? 1 : 0;
      const lo = (r.round_date_range || [])[0] || "";
      return [has, lo];
    };
    const sorted = rounds
      .map((r, i) => ({ i, r, unplayed: unplayedCount(r) }))
      .sort((a, b) => {
        // 1. Most unplayed matches first.
        if (a.unplayed !== b.unplayed) return b.unplayed - a.unplayed;
        // 2. Manual content wins.
        const sa = scoreRound(a.r);
        const sb = scoreRound(b.r);
        if (sa[0] !== sb[0]) return sb[0] - sa[0];
        // 3. Soonest start date first (the round that begins next).
        const la = new Date(sa[1] + "T00:00:00Z").getTime();
        const lb = new Date(sb[1] + "T00:00:00Z").getTime();
        if (!isNaN(la) && !isNaN(lb) && la !== lb) return la - lb;
        // 4. Most recent start as last resort.
        return lb - la;
      });
    return sorted[0]?.i ?? 0;
  }

  function weeklyRoundShortLabel(r, lang) {
    const lbl = (r.round_label || {})[lang] || r.round_label?.zh || "—";
    const rng = r.round_date_range || [];
    if (rng.length < 2) return lbl;
    return `${lbl} · ${formatDateWithDow(rng[0])}`;
  }

  async function loadWeekly(force = false) {
    if (!force && weeklyData) return weeklyData;
    if (!force) {
      try {
        const raw = sessionStorage.getItem(WEEKLY_CACHE_KEY);
        if (raw) {
          const { at, data } = JSON.parse(raw);
          if (Date.now() - at < WEEKLY_CACHE_TTL_MS) {
            weeklyData = data;
            return data;
          }
        }
      } catch { /* ignore */ }
    }
    if (weeklyLoading) return weeklyData;
    weeklyLoading = true;
    try {
      const res = await fetch(`${WEEKLY_JSON_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      weeklyData = data;
      try { sessionStorage.setItem(WEEKLY_CACHE_KEY, JSON.stringify({ at: Date.now(), data })); } catch { /* ignore */ }
      return data;
    } catch (e) {
      // Stale-while-error: keep whatever we had, surface the error to the caller.
      throw e;
    } finally {
      weeklyLoading = false;
    }
  }

  function weeklyTeamName(side) {
    if (!side) return "—";
    if (currentLang === "zh" && side.name_zh) return side.name_zh;
    return side.name || "—";
  }

  function relativeDateLabel(iso, nowIso) {
    // iso / nowIso: YYYY-MM-DD. Returns a friendly relative label.
    if (!iso || !nowIso) return iso || "";
    const a = new Date(iso + "T00:00:00Z").getTime();
    const b = new Date(nowIso + "T00:00:00Z").getTime();
    const diffDays = Math.round((a - b) / 86_400_000);
    if (diffDays === 0) return i18n("day.today", { date: iso }).replace(/^[^·]*·\s*/, "");
    if (diffDays === 1) return iso;
    if (diffDays === -1) return iso;
    return iso;
  }

  function weeklyLastManualLabel(data) {
    if (!data || !data.last_manual_update) return i18n("weekly.manual.never");
    const when = data.last_manual_update;
    let rel = "";
    try {
      const dt = new Date(when);
      const ms = Date.now() - dt.getTime();
      const minute = 60_000, hour = 3_600_000, day = 86_400_000;
      if (ms < 0) rel = when.slice(0, 16).replace("T", " ");
      else if (ms < hour) rel = i18n("relative.m.ago", { n: Math.max(1, Math.round(ms / minute)) });
      else if (ms < day) rel = i18n("relative.h.ago", { n: Math.round(ms / hour) });
      else rel = i18n("relative.d.ago", { n: Math.round(ms / day) });
    } catch { rel = when.slice(0, 16).replace("T", " "); }
    return i18n("weekly.manual.fresh", { when: rel });
  }

  function renderWeekly() {
    const content = $("#content");
    content.innerHTML = "";
    const countEl = $("#result-count");
    if (countEl) countEl.textContent = "";

    // Show a quick loading placeholder; loadWeekly resolves fast on cache hit.
    const placeholder = document.createElement("div");
    placeholder.className = "loading";
    placeholder.textContent = i18n("loading");
    content.appendChild(placeholder);

    loadWeekly().then((raw) => {
      content.innerHTML = "";
      const countEl2 = $("#result-count");
      if (countEl2) countEl2.textContent = "";

      // Normalize v1 (single round) or v2 (rounds[]) into a uniform list.
      weeklyData = raw;
      weeklyRounds = normalizeWeeklyRounds(raw);

      if (weeklyRounds.length === 0) {
        renderWeeklyEmpty(content);
        return;
      }

      // Pick the round to show: user's saved preference (if still
      // exists) wins; otherwise the default (in-progress → recent
      // finished → next upcoming → 0).
      const tz = currentTz();
      const todayIso = dateInTz(new Date(), tz);
      let savedId = null;
      try { savedId = localStorage.getItem(WEEKLY_ROUND_KEY); } catch {}
      let idx = weeklyRounds.findIndex((r) => r.round_id === savedId);
      if (idx < 0) idx = pickDefaultRoundIdx(weeklyRounds, todayIso);
      if (idx < 0) idx = 0;
      weeklySelectedIdx = idx;
      renderWeeklyRound(content, weeklyRounds[idx], todayIso, tz);
    }).catch((err) => {
      renderWeeklyEmpty(content, err);
    });
  }

  function renderWeeklyRound(content, round, todayIso, tz) {
    // Empty-round fallback.
    if (!round || !round.matches || round.matches.length === 0) {
      renderWeeklyEmpty(content);
      return;
    }

    // Round selector (pill row). Only render when there's more than 1
    // round in the file; otherwise the title is enough.
    if (weeklyRounds.length > 1) {
      const picker = document.createElement("div");
      picker.className = "weekly-round-picker";
      picker.setAttribute("role", "tablist");
      picker.setAttribute("aria-label", "Round");
      for (let i = 0; i < weeklyRounds.length; i++) {
        const r = weeklyRounds[i];
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "weekly-round-pill" + (i === weeklySelectedIdx ? " is-active" : "");
        btn.setAttribute("role", "tab");
        btn.setAttribute("aria-selected", String(i === weeklySelectedIdx));
        btn.dataset.idx = String(i);
        btn.textContent = weeklyRoundShortLabel(r, currentLang);
        btn.addEventListener("click", () => {
          if (i === weeklySelectedIdx) return;
          weeklySelectedIdx = i;
          try { localStorage.setItem(WEEKLY_ROUND_KEY, r.round_id); } catch {}
          // Re-render in place.
          const newContent = $("#content");
          newContent.innerHTML = "";
          renderWeeklyRound(newContent, weeklyRounds[i], todayIso, tz);
        });
        picker.appendChild(btn);
      }
      content.appendChild(picker);
    }

    // Stale-round banner: if the picks' date range is fully in the past.
    const dateRange = round.round_date_range || [];
    const isStale = dateRange.length === 2 && dateRange[1] < todayIso;

    const wrap = document.createElement("section");
    wrap.className = "weekly-section";

    // Header
    const head = document.createElement("header");
    head.className = "weekly-head";
    const totalCount = round.matches.length;
    const roundLabel = (round.round_label || {})[currentLang] || i18n("weekly.title");
    const rangeText = dateRange.length === 2
      ? `${formatDateWithDow(dateRange[0])} → ${formatDateWithDow(dateRange[1])}`
      : "";
    const manualLabel = round.last_manual_update
      ? weeklyLastManualLabel({ last_manual_update: round.last_manual_update })
      : null;
    const showManual = round.manual_count > 0 && manualLabel;
    head.innerHTML = `
      <h2 class="weekly-title">${escapeHtml(i18n("weekly.title"))}</h2>
      <p class="weekly-round-label">${escapeHtml(roundLabel)}${rangeText ? ` <span class="weekly-round-range">· ${escapeHtml(rangeText)}</span>` : ""}</p>
      <p class="weekly-hint">${escapeHtml(i18n("weekly.hint"))}</p>
      <p class="weekly-meta">
        <span class="weekly-meta-count">${escapeHtml(i18n("n.matches", { n: totalCount }))}</span>
        ${showManual ? `<span class="weekly-meta-dot">·</span><span class="weekly-meta-manual">${escapeHtml(manualLabel)}</span>` : ""}
      </p>
    `;
    wrap.appendChild(head);

    // Stale-date banner
    if (isStale) {
      const banner = document.createElement("div");
      banner.className = "weekly-stale";
      banner.innerHTML = `
        <strong>${escapeHtml(i18n("weekly.stale.title", { round: roundLabel }))}</strong>
        <span class="weekly-stale-hint">${escapeHtml(i18n("weekly.stale.hint"))}</span>
      `;
      wrap.appendChild(banner);
    }

    // Round intro (manual, optional)
    const intro = currentLang === "zh" ? round.round_intro_zh : round.round_intro_en;
    if (intro) {
      const p = document.createElement("div");
      p.className = "weekly-intro";
      // Allow multi-paragraph intros (\n\n splits). Lightweight
      // markdown-ish handling: paragraphs separated by blank lines.
      const paragraphs = String(intro).split(/\n\s*\n/).map((para) =>
        `<p>${escapeHtml(para).replace(/\n/g, "<br/>")}</p>`
      ).join("");
      p.innerHTML = paragraphs;
      wrap.appendChild(p);
    }

    // Manual in-progress hint
    if (round.manual_count > 0 && round.manual_count < totalCount) {
      const note = document.createElement("p");
      note.className = "weekly-partial";
      note.textContent = i18n("weekly.manual.partial", { n: round.manual_count, total: totalCount });
      wrap.appendChild(note);
    }

    // Group matches by verdict. Within each bucket, group by date
    // so the user can see "what's on tomorrow" at a glance.
    const buckets = {
      must:   { items: [] },
      lively: { items: [] },
      skip:   { items: [] },
    };
    for (const m of round.matches) {
      const v = m.verdict || m.stakes_verdict_auto || "lively";
      if (!buckets[v]) buckets[v] = { items: [] };
      buckets[v].items.push(m);
    }
    const bucketOrder = ["must", "lively", "skip"];
    const todayIso2 = todayIso;
    for (const key of bucketOrder) {
      const b = buckets[key];
      if (!b.items.length) continue;
      const section = document.createElement("section");
      section.className = `weekly-bucket weekly-bucket--${key}`;
      const bhead = document.createElement("header");
      bhead.className = "weekly-bucket-head";
      const verdictLabel =
        key === "must" ? i18n("weekly.verdict.must")
        : key === "lively" ? i18n("weekly.verdict.lively")
        : i18n("weekly.verdict.skip");
      bhead.innerHTML = `<span class="weekly-bucket-title">${escapeHtml(verdictLabel)}</span><span class="weekly-bucket-count">${b.items.length}</span>`;
      section.appendChild(bhead);

      // Group within bucket by local kickoff date, preserving the
      // overall sort (must > lively > skip, then by time).
      const byDate = new Map();
      for (const m of b.items) {
        const d = m.kickoff_local_date || m.kickoff_utc?.slice(0, 10) || "—";
        if (!byDate.has(d)) byDate.set(d, []);
        byDate.get(d).push(m);
      }
      const showDateHeader = byDate.size > 1;
      for (const [date, items] of byDate) {
        if (showDateHeader) {
          const dh = document.createElement("div");
          dh.className = "weekly-day-head";
          const tomorrowDate = (() => {
            const d = new Date(todayIso2 + "T00:00:00Z");
            d.setUTCDate(d.getUTCDate() + 1);
            return d.toISOString().slice(0, 10);
          })();
          const label = date === todayIso2
            ? `${i18n("weekly.day.today")} · ${formatDateWithDow(date)}`
            : date === tomorrowDate
              ? `${i18n("weekly.day.tomorrow")} · ${formatDateWithDow(date)}`
              : formatDateWithDow(date);
          dh.textContent = label;
          section.appendChild(dh);
        }
        const list = document.createElement("ul");
        list.className = "weekly-list";
        list.setAttribute("role", "list");
        for (const m of items) list.appendChild(buildWeeklyCard(m));
        section.appendChild(list);
      }
      wrap.appendChild(section);
    }

    // Manual note (footer of analyst)
    const note = currentLang === "zh" ? round.manual_note_zh : round.manual_note_en;
    if (note) {
      const p = document.createElement("p");
      p.className = "weekly-foot-note";
      p.textContent = note;
      wrap.appendChild(p);
    }

    content.appendChild(wrap);
  }

  function renderWeeklyEmpty(content, err) {
    const div = document.createElement("div");
    div.className = "empty";
    const errBlock = err && !/HTTP\s*404/i.test(String(err))
      ? `<div class="empty-hint" style="opacity:.6">${escapeHtml(String(err))}</div>`
      : "";
    div.innerHTML = `<div>${escapeHtml(i18n("weekly.empty.title"))}</div>
      <div class="empty-hint">${escapeHtml(i18n("weekly.empty.hint"))}</div>
      <div class="empty-hint">${escapeHtml(i18n("weekly.empty.ask"))}</div>
      ${errBlock}`;
    content.appendChild(div);
  }

  function buildWeeklyCard(m) {
    const li = document.createElement("li");
    li.className = "weekly-card";
    li.dataset.verdict = m.verdict || "lively";

    const home = m.home || {};
    const away = m.away || {};
    const homeName = weeklyTeamName(home);
    const awayName = weeklyTeamName(away);
    const headline = currentLang === "zh" ? m.headline_zh : m.headline_en;
    const stakes = m.stakes_narrative_zh && m.stakes_narrative_en
      ? (currentLang === "zh" ? m.stakes_narrative_zh : m.stakes_narrative_en)
      : null;
    const watch = currentLang === "zh" ? (m.watch_for_zh || []) : (m.watch_for_en || []);
    const players = currentLang === "zh" ? (m.key_players_zh || []) : (m.key_players_en || []);
    const news = currentLang === "zh" ? m.news_focus_zh : m.news_focus_en;
    const records = currentLang === "zh" ? (m.record_potential_zh || []) : (m.record_potential_en || []);
    const whySkip = currentLang === "zh" ? m.why_skip_zh : m.why_skip_en;
    const score = m.score != null ? m.score : m.stakes_score_auto;

    // Verdict badge + score
    const verdictKey = m.verdict || "lively";
    const verdictLabel = verdictKey === "must" ? i18n("weekly.verdict.must")
      : verdictKey === "lively" ? i18n("weekly.verdict.lively")
      : i18n("weekly.verdict.skip");

    const head = document.createElement("header");
    head.className = "weekly-card-head";
    head.innerHTML = `
      <div class="weekly-card-time">
        <span class="weekly-card-time-main">${escapeHtml(m.kickoff_time || "")}</span>
        ${m.stage ? `<span class="weekly-card-stage">${escapeHtml(m.stage)}</span>` : ""}
        ${m.group_name ? `<span class="weekly-card-group">${escapeHtml(m.group_name)}</span>` : ""}
      </div>
      <div class="weekly-card-verdict">
        <span class="weekly-verdict-badge weekly-verdict-badge--${verdictKey}">${escapeHtml(verdictLabel)}</span>
        ${score != null ? `<span class="weekly-score">${escapeHtml(i18n("weekly.score", { n: score }))}</span>` : ""}
      </div>
    `;
    li.appendChild(head);

    // Matchup
    const teams = document.createElement("div");
    teams.className = "weekly-card-teams";
    teams.innerHTML = `
      <div class="weekly-team">
        <span class="weekly-team-flag">${escapeHtml(home.flag || "")}</span>
        <span class="weekly-team-name">${escapeHtml(homeName)}</span>
        ${home.rank ? `<span class="weekly-team-rank">#${home.rank}</span>` : ""}
      </div>
      <div class="weekly-team-sep">vs</div>
      <div class="weekly-team">
        <span class="weekly-team-flag">${escapeHtml(away.flag || "")}</span>
        <span class="weekly-team-name">${escapeHtml(awayName)}</span>
        ${away.rank ? `<span class="weekly-team-rank">#${away.rank}</span>` : ""}
      </div>
    `;
    li.appendChild(teams);

    // Headline (manual)
    if (headline) {
      const h = document.createElement("h3");
      h.className = "weekly-card-headline";
      h.textContent = headline;
      li.appendChild(h);
    }

    // Stakes block (always present — comes from auto script)
    if (stakes) {
      li.appendChild(weeklyBlock(i18n("weekly.match.stakes"), stakes, "weekly-block--stakes"));
    }

    // Why-skip block (only for skip / lively)
    if (whySkip && (verdictKey === "skip" || verdictKey === "lively")) {
      li.appendChild(weeklyBlock(i18n("weekly.match.why_skip"), whySkip, "weekly-block--skip"));
    }

    // Watch-for list
    if (watch.length) {
      li.appendChild(weeklyListBlock(i18n("weekly.match.watch"), watch, "weekly-block--watch"));
    }

    // Players
    if (players.length) {
      li.appendChild(weeklyListBlock(i18n("weekly.match.players"), players, "weekly-block--players"));
    }

    // News focus
    if (news) {
      li.appendChild(weeklyBlock(i18n("weekly.match.news"), news, "weekly-block--news"));
    }

    // Records
    if (records.length) {
      li.appendChild(weeklyListBlock(i18n("weekly.match.records"), records, "weekly-block--records"));
    }

    // Awaiting-analysis placeholder when a card has nothing manual yet
    const hasManual = headline || watch.length || players.length || news || records.length || whySkip;
    if (!hasManual) {
      const ph = document.createElement("div");
      ph.className = "weekly-awaiting";
      ph.textContent = i18n("weekly.manual.never");
      li.appendChild(ph);
    }

    // Footer: venue + links
    const links = [];
    if (m.espn_url) links.push(`<a class="link espn" target="_blank" rel="noopener noreferrer" href="${escapeHtml(m.espn_url)}">${escapeHtml(i18n("link.espn"))}</a>`);
    if (m.fox_url) links.push(`<a class="link fox" target="_blank" rel="noopener noreferrer" href="${escapeHtml(m.fox_url)}">${escapeHtml(i18n("link.fox"))}</a>`);
    if (m.venue || links.length) {
      const foot = document.createElement("footer");
      foot.className = "weekly-card-foot";
      const venueBits = [];
      if (m.venue) {
        const venueTitle = [m.venue, m.venue_city].filter(Boolean).join(", ");
        const venueText = m.venue_city
          ? `${escapeHtml(m.venue)} <span class="weekly-card-venue-city">${escapeHtml(m.venue_city)}</span>`
          : escapeHtml(m.venue);
        venueBits.push(`<span class="weekly-card-venue" title="${escapeHtml(venueTitle)}">🏟️ ${venueText}</span>`);
      }
      foot.innerHTML = venueBits.join("") + (links.length ? `<span class="weekly-card-links">${links.join("")}</span>` : "");
      li.appendChild(foot);
    }

    return li;
  }

  function weeklyBlock(label, text, cls) {
    const div = document.createElement("div");
    div.className = `weekly-block ${cls || ""}`;
    div.innerHTML = `<span class="weekly-block-label">${escapeHtml(label)}</span><span class="weekly-block-text">${escapeHtml(text)}</span>`;
    return div;
  }
  function weeklyListBlock(label, items, cls) {
    const div = document.createElement("div");
    div.className = `weekly-block ${cls || ""}`;
    const ul = items.map((it) => `<li>${escapeHtml(it)}</li>`).join("");
    div.innerHTML = `<span class="weekly-block-label">${escapeHtml(label)}</span><ul class="weekly-block-list">${ul}</ul>`;
    return div;
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

  function renderIncidents(container, m) {
    if (!container) return;
    const incidents = (m && m.incidents) || [];
    if (!incidents.length) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    container.hidden = false;
    container.innerHTML = "";

    // Bucket per side so cards / goals cluster under their team header.
    // The header shows team flag + name and a quick yellow/red tally so
    // the eye can land on "how many cards did each side get" without
    // having to walk the rows.
    const lang = currentLang;
    const buckets = {
      home: { team: m && m.home, goals: [], yellows: [], reds: [] },
      away: { team: m && m.away, goals: [], yellows: [], reds: [] },
      other: { goals: [], yellows: [], reds: [] },
    };
    for (const inc of incidents) {
      const side = inc.team_side === "home" || inc.team_side === "away" ? inc.team_side : "other";
      const b = buckets[side];
      if (inc.kind === "goal") b.goals.push(inc);
      else if (inc.kind === "yellow_card") b.yellows.push(inc);
      else if (inc.kind === "red_card") b.reds.push(inc);
    }

    for (const key of ["home", "away"]) {
      const b = buckets[key];
      if (!b.team) continue;
      const total = b.goals.length + b.yellows.length + b.reds.length;
      if (!total) continue;
      _incidentSideHead(container, b.team, lang, b.yellows.length, b.reds.length);
      if (b.goals.length)   _incidentRow(container, "goal",   "⚽", b.goals);
      if (b.yellows.length) _incidentRow(container, "yellow", "🟨", b.yellows);
      if (b.reds.length)    _incidentRow(container, "red",    "🟥", b.reds);
    }

    // Unknown-side incidents (ESPN sometimes omits team_id) — render flat
    // so nothing disappears, but no header.
    const ob = buckets.other;
    if (ob.goals.length + ob.yellows.length + ob.reds.length) {
      if (ob.goals.length)   _incidentRow(container, "goal",   "⚽", ob.goals);
      if (ob.yellows.length) _incidentRow(container, "yellow", "🟨", ob.yellows);
      if (ob.reds.length)    _incidentRow(container, "red",    "🟥", ob.reds);
    }
  }

  function _incidentSideHead(container, team, lang, yellowCount, redCount) {
    const head = document.createElement("div");
    head.className = "incident-side-head";
    const flag = escapeHtml(team.flag || "🏳️");
    const zh = (lang === "zh") && team.name_zh;
    const name = escapeHtml(zh || team.name || team.name_zh || "");
    const counts = [];
    if (yellowCount) counts.push(`<span class="ish-count is-y">🟨${yellowCount}</span>`);
    if (redCount) counts.push(`<span class="ish-count is-r">🟥${redCount}</span>`);
    head.innerHTML =
      `<span class="ish-flag">${flag}</span>` +
      `<span class="ish-name">${name}</span>` +
      `<span class="ish-counts">${counts.join("")}</span>`;
    container.appendChild(head);
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
      timeStatus.textContent = i18n("status.live.short");
      node.classList.add("is-live");
    } else if (isFinal) {
      timeStatus.classList.add("is-final");
      timeStatus.textContent = i18n("status.final.short");
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

    // Countdown badge: "倒计时 #N 场" / "#N to go" — reverse position
    // in the tournament (Final = 1, first match = 104). Only shown for
    // SCHEDULED matches where the relative time + countdown pair is
    // most informative. LIVE/FINAL keep their single status badge so
    // the time column doesn't get cluttered.
    const cdEl = node.querySelector(".time-countdown");
    if (cdEl) {
      const cd = matchCountdown.get(m.id);
      if (isScheduled && cd) {
        cdEl.textContent = i18n("match.countdown", { n: cd });
        cdEl.hidden = false;
      } else {
        cdEl.hidden = true;
        cdEl.textContent = "";
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
    renderIncidents(node.querySelector(".match-incidents"), m);

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
      updated.textContent = i18n("updated", { rel: formatRelative(now, new Date()) });
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
    // The bracket is only relevant alongside the match list. The
    // scorers view treats the bracket as out of scope; standings
    // keeps the existing "bracket below standings" behavior.
    if (currentView === "scorers") {
      section.hidden = true;
      return;
    }
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

    // The knockout bracket is a fixed tree — ESPN's IDs follow kickoff
    // order but each match has a bracket slot independent of when it
    // plays. We parse espn_url to learn which slots feed which parent.
    //
    // Display order keeps TIME order (so R32 cards scan chronologically
    // — users come to the bracket asking "who's playing today?" not
    // "what's the FIFA bracket structure?"). Sorting by bracket slot
    // would visually group future R16 opponents together from day 1,
    // which is information users don't have yet.
    //
    // R16/QF/SF stay in time order too; the simple (i, i+1) pairing in
    // linkRound works for those because each round's pairings happen to
    // be (1,2)(3,4)(5,6)(7,8) in the actual bracket, and time order
    // doesn't shuffle them (we verified empirically).
    //
    // Only R32 → R16 needs special handling because its actual
    // pairings are non-consecutive: (1,3)(2,5)(4,6)(7,8)(9,10)
    // (11,12)(13,15)(14,16). Lines from time-ordered R32 to
    // time-ordered R16 will cross — that's the actual bracket, accept
    // the crossings.
    const slotRe = /round-of-(\d+)-(\d+)-winner/g;
    const parentSlug = (stageSlug) =>
      stageSlug === "quarterfinals" ? "quarterfinal"
      : stageSlug === "semifinals"  ? "semifinal"
      : stageSlug;  // "round-of-32" / "round-of-16" stay as-is
    const parentSlots = (m, stageSlug) => {
      const url = m.espn_url || "";
      const re = new RegExp(`${parentSlug(stageSlug)}-(\\d+)-winner`, "g");
      return [...url.matchAll(re)].map(x => parseInt(x[1])).sort((a, b) => a - b);
    };
    const byId = (slug) => new Map((byRound[slug] || []).map(m => [m.id, m]));
    // When an R16's URL has been replaced with team names (because both
    // parents are decided), the slot regex returns 0–1 entries. Fall
    // back to looking up each parent's R32 slot from team data so the
    // match lands in its correct bracket position rather than the tail
    // of the sorted list.
    const r32SlotForTeam = (() => {
      const idToSlot = new Map(R32_BRACKET_IDS.map((id, i) => [id, i + 1]));
      const teamToR32 = new Map();
      for (const r32Match of byRound["round-of-32"]) {
        if (r32Match.home?.id) teamToR32.set(r32Match.home.id, r32Match.id);
        if (r32Match.away?.id) teamToR32.set(r32Match.away.id, r32Match.id);
      }
      return (team) => {
        if (!team?.id) return null;
        const r32Id = teamToR32.get(team.id);
        return r32Id != null ? idToSlot.get(r32Id) : null;
      };
    })();
    const r16ParentSlots = (m) => {
      const fromUrl = parentSlots(m, "round-of-32");
      if (fromUrl.length >= 2) return fromUrl;
      // Fill in any missing slots via the home/away team lookup.
      const slots = new Set(fromUrl);
      const homeSlot = r32SlotForTeam(m.home);
      const awaySlot = r32SlotForTeam(m.away);
      if (homeSlot != null) slots.add(homeSlot);
      if (awaySlot != null) slots.add(awaySlot);
      return [...slots].sort((a, b) => a - b);
    };
    // Build bracket-slot lookup tables for every knockout round. A
    // match's "bracket slot" is its position in the bracket TREE (not
    // its position in the time-sorted display array). The tree order
    // is determined by min parent slot: R32 #1 is slot 1 by virtue of
    // R32_BRACKET_IDS[0]; R16 #1 is slot 1 because it's the first R16
    // pair (R32 #(1,3)) in min-R32-slot order; etc.
    const slotToMatch = {};
    slotToMatch["round-of-32"] = new Map(R32_BRACKET_IDS.map((id, i) => [i + 1, byId("round-of-32").get(id)]));
    // The R16 → R32 pairing is fixed by the FIFA 2026 bracket:
    //   R16-1: (1,3)   R16-2: (2,5)   R16-3: (4,6)   R16-4: (7,8)
    //   R16-5: (9,10) R16-6: (11,12) R16-7: (13,15) R16-8: (14,16)
    // The URL-derived r16ParentSlots() is unreliable once one parent is
    // decided (espn rewrites the URL to a team name and drops the
    // slot number for the still-TBD parent), so we hardcode the
    // pairing and use the URL/team lookup only as a sanity check.
    const R16_TO_R32 = {
      1: [1, 3], 2: [2, 5], 3: [4, 6], 4: [7, 8],
      5: [9, 10], 6: [11, 12], 7: [13, 15], 8: [14, 16],
    };
    const r16ByMinR32Slot = byRound["round-of-16"]
      .map(m => ({ match: m, r32Slots: r16ParentSlots(m) }))
      .sort((a, b) => (a.r32Slots[0] ?? 999) - (b.r32Slots[0] ?? 999));
    const r16IdToSlot = new Map();
    slotToMatch["round-of-16"] = new Map();
    r16ByMinR32Slot.forEach((x, i) => {
      slotToMatch["round-of-16"].set(i + 1, x.match);
      r16IdToSlot.set(x.match.id, i + 1);
    });
    const r16ParentSlotsHardcoded = (m) => {
      const slot = r16IdToSlot.get(m.id);
      return slot ? R16_TO_R32[slot] : r16ParentSlots(m);
    };
    // Same fallback pattern as r32SlotForTeam above: if a QF's espn_url
    // has been rewritten to team names (the QF is decided), the URL
    // regex returns nothing and the match would be pushed to the end
    // of the sort, landing in the wrong half of the bracket. Look up
    // each team's R16 instead so the QF keeps its correct slot.
    const r16IdByTeam = (() => {
      const teamToR16 = new Map();
      for (const r16Match of byRound["round-of-16"]) {
        if (r16Match.home?.id) teamToR16.set(r16Match.home.id, r16Match.id);
        if (r16Match.away?.id) teamToR16.set(r16Match.away.id, r16Match.id);
      }
      return (team) => (team?.id != null) ? teamToR16.get(team.id) : null;
    })();
    const qfParentSlots = (m) => {
      const fromUrl = parentSlots(m, "round-of-16");
      if (fromUrl.length >= 2) return fromUrl;
      const slots = new Set();
      const homeR16 = r16IdByTeam(m.home);
      const awayR16 = r16IdByTeam(m.away);
      if (homeR16 != null) {
        const slot = r16IdToSlot.get(homeR16);
        if (slot != null) slots.add(slot);
      }
      if (awayR16 != null) {
        const slot = r16IdToSlot.get(awayR16);
        if (slot != null) slots.add(slot);
      }
      return [...slots].sort((a, b) => a - b);
    };
    const qfByMinR16Slot = byRound["quarterfinals"]
      .map(m => ({ match: m, r16Slots: qfParentSlots(m) }))
      .sort((a, b) => (a.r16Slots[0] ?? 999) - (b.r16Slots[0] ?? 999));
    const qfIdToSlot = new Map();
    slotToMatch["quarterfinals"] = new Map(qfByMinR16Slot.map((x, i) => [i + 1, x.match]));
    qfByMinR16Slot.forEach((x, i) => qfIdToSlot.set(x.match.id, i + 1));
    // Same fallback for SFs once they start getting decided.
    const qfIdByTeam = (() => {
      const teamToQf = new Map();
      for (const qfMatch of byRound["quarterfinals"]) {
        if (qfMatch.home?.id) teamToQf.set(qfMatch.home.id, qfMatch.id);
        if (qfMatch.away?.id) teamToQf.set(qfMatch.away.id, qfMatch.id);
      }
      return (team) => (team?.id != null) ? teamToQf.get(team.id) : null;
    })();
    const sfParentSlots = (m) => {
      const fromUrl = parentSlots(m, "quarterfinals");
      if (fromUrl.length >= 2) return fromUrl;
      const slots = new Set();
      const homeQf = qfIdByTeam(m.home);
      const awayQf = qfIdByTeam(m.away);
      if (homeQf != null) {
        const slot = qfIdToSlot.get(homeQf);
        if (slot != null) slots.add(slot);
      }
      if (awayQf != null) {
        const slot = qfIdToSlot.get(awayQf);
        if (slot != null) slots.add(slot);
      }
      return [...slots].sort((a, b) => a - b);
    };
    // SF pairing is interleaved, not consecutive: SF slot 1 (M101) takes
    // QF slot 1 + QF slot 3 (M97 + M98), SF slot 2 (M102) takes QF
    // slot 2 + QF slot 4 (M99 + M100). This matches FIFA's actual
    // bracket — the halves are interleaved at the QF level so teams
    // from the same group (e.g. France 1I in M97 and Norway 2I in M99)
    // land on opposite SFs and can only meet in the Final.
    //
    // SF URLs use M-number order ("quarterfinal-2-winner-quarterfinal-1-winner"
    // = M98 winner + M97 winner for M101) which doesn't match code's
    // QF slot ordering (slot 2 = M99, not M98). So we hardcode the
    // pairing instead of relying on URL parsing.
    const SF_TO_QF_SLOTS = {
      1: [1, 3],  // M101 → M97 + M98
      2: [2, 4],  // M102 → M99 + M100
    };
    // Build slotToMatch["semifinals"] by M-number (M101 → 1, M102 → 2).
    slotToMatch["semifinals"] = new Map(
      [...byRound["semifinals"]]
        .sort((a, b) => String(a.id).localeCompare(String(b.id)))
        .map((m, i) => [i + 1, m])
    );
    const sfIdToSlot = new Map();
    for (const [slot, m] of slotToMatch["semifinals"]) sfIdToSlot.set(m.id, slot);

    // Reorder R32 in visual display order so pair members are adjacent
    // and connecting lines form clean V shapes (no crossings). The
    // actual pairing data (slotToMatch) is unchanged — only the y-axis
    // position of each card changes.
    //
    // Actual pairings per ESPN:
    //   R16-1: (R32-1, R32-3)
    //   R16-2: (R32-2, R32-5)
    //   R16-3: (R32-4, R32-6)
    //   R16-4: (R32-7, R32-8)
    //   R16-5: (R32-9, R32-10)
    //   R16-6: (R32-11, R32-12)
    //   R16-7: (R32-13, R32-15)
    //   R16-8: (R32-14, R32-16)
    //
    // The bracket halves are defined by the SF tree, not by slot range.
    // FIFA's actual bracket pairs QFs interleaved: M101 = M97 + M98,
    // M102 = M99 + M100. So M101's half contains slots {1, 2, 3, 5,
    // 9, 10, 11, 12} (4 upper + 4 lower) and M102's half contains
    // slots {4, 6, 7, 8, 13, 14, 15, 16}. Putting slots 1-8 vs 9-16 on
    // opposite wings would put teams from the same group (e.g. France
    // 1I in slot 2 and Norway 2I in slot 4) on the same wing — they'd
    // meet in the SF instead of only in the Final. The half maps below
    // pin each slot to its correct SF-half parent.
    const HALF_BY_R32_SLOT = {
      1: 1, 2: 1, 3: 1,       // upper R32 → M101's half
      4: 2, 5: 1, 6: 2, 7: 2, 8: 2,
      9: 1, 10: 1, 11: 1, 12: 1, // M94, M93 → M98 → M101
      13: 2, 14: 2, 15: 2, 16: 2,
    };
    const HALF_BY_R16_SLOT = {
      1: 1, 2: 1,             // R16-1, R16-2 → M97 → M101
      3: 2, 4: 2,             // R16-3, R16-4 → M99 → M102
      5: 1, 6: 1,             // R16-5, R16-6 → M98 → M101
      7: 2, 8: 2,             // R16-7, R16-8 → M100 → M102
    };
    const HALF_BY_QF_SLOT = {
      1: 1,                   // M97 (min R16 slot 1) → M101
      2: 2,                   // M99 (min R16 slot 3) → M102
      3: 1,                   // M98 (min R16 slot 5) → M101
      4: 2,                   // M100 (min R16 slot 7) → M102
    };

    // Each pair becomes (slot N, slot N+1) in display position, but the
    // 8 pairs are split 4-and-4 between the two wings so each wing is
    // exactly one SF half (M101's half on left, M102's half on right).
    const R32_VISUAL_ORDER = [
      1, 3,    // → R16-1  ┐
      2, 5,    // → R16-2  ├ M101's half (left wing)
      9, 10,   // → R16-5  │
      11, 12,  // → R16-6  ┘
      4, 6,    // → R16-3  ┐
      7, 8,    // → R16-4  ├ M102's half (right wing)
      13, 15,  // → R16-7  │
      14, 16,  // → R16-8  ┘
    ];
    byRound["round-of-32"] = R32_VISUAL_ORDER.map(s => slotToMatch["round-of-32"].get(s));
    // R16 in slot order (y-position comes from parent R32 midpoints,
    // side comes from HALF_BY_R16_SLOT).
    byRound["round-of-16"] = Array.from(slotToMatch["round-of-16"].values());
    // QF in slot order (y-position comes from parent R16 midpoints,
    // side comes from HALF_BY_QF_SLOT).
    byRound["quarterfinals"] = Array.from(slotToMatch["quarterfinals"].values());
    const third = allMatches.find((m) => m.stage_slug === "3rd-place-match");

    // Compute Y position (0-100% of height) and side (L/R) for every match.
    // Center of each match sits at the midpoint of its two source matches.
    const pos = {};  // matchId -> { y, side }
    function place(round) {
      const ms = byRound[round] || [];
      const n = ms.length;
      if (n === 0) return;
      if (round === "final") {
        // Final sits at 46% (was 50%) so the Final + 3rd-place pair
        // becomes a tight, vertically-centered unit. Pair spans 46–58%
        // with center at 52%, the 3rd-place match below at 58%.
        for (const m of ms) pos[m.id] = { y: 46, side: "C" };
        return;
      }
      // Each wing (L/R) gets half the cards. Distribute them across the
      // full bracket height (0–100%) so L wing spans the full left
      // column and R wing spans the full right column, mirroring around
      // the vertical center axis where the Final sits.
      //
      // R32 uses a NON-uniform y distribution: the two R32 cards in the
      // same R16 pair sit close together (within-pair distance = one
      // card height = 5.33% in 600px), and different pairs are
      // separated by a wider gap (17.57%). The R16/QF positions fall
      // out automatically from the pair midpoints, and the sum of all
      // 8 R32 y values is exactly 400 so the SF lands on the center
      // axis. The Final sits at 46% (was 50%) — see place("final").
      const half = n / 2;
      // Side (L/R) is determined by which SF half the match belongs
      // to, not by its index within byRound. The half maps above
      // encode FIFA's actual bracket tree (M101 = M97+M98 interleaved,
      // M102 = M99+M100 interleaved) so e.g. France (slot 2 in M97)
      // and Norway (slot 4 in M99) end up on opposite wings even
      // though both R32 slots are "upper".
      const halfOfMatch = (m) => {
        if (round === "round-of-32") {
          const slot = [...slotToMatch["round-of-32"].entries()].find(([_, mm]) => mm.id === m.id)?.[0];
          return HALF_BY_R32_SLOT[slot];
        }
        if (round === "round-of-16") return HALF_BY_R16_SLOT[r16IdToSlot.get(m.id)];
        if (round === "quarterfinals") {
          const slot = qfIdToSlot.get(m.id);
          return HALF_BY_QF_SLOT[slot];
        }
        if (round === "semifinals") {
          const slot = [...slotToMatch["semifinals"].entries()].find(([_, mm]) => mm.id === m.id)?.[0];
          return slot;  // SF slot 1 = M101 (half 1), slot 2 = M102 (half 2)
        }
        return 1;
      };
      if (round === "round-of-32") {
        // Uniform ladder: 16 cards (8 per wing) stack with no gap,
        // each card height = 100/16 = 6.25%, so consecutive cards
        // touch (no within-pair / between-pair distinction). The
        // byRound order is structured so each wing's 8 cards form 4
        // R16 pairs in tree order (M101's half pairs on left, M102's
        // half pairs on right).
        const STEP = 100 / 16;
        ms.forEach((m, i) => {
          const w = i % half;  // position within the wing (0..half-1)
          const y = (w + 0.5) * STEP;
          pos[m.id] = { y, side: halfOfMatch(m) === 1 ? "L" : "R" };
        });
        return;
      }
      // R16, QF, SF: all derived from their parent matches' y values.
      // Each card sits at the midpoint of its two parent matches.
      // QF-N takes R16-(2N-1) and R16-2N (consecutive slot order,
      // which is what R16_TO_R32 + the byRound slot order produce).
      // SF-N takes QF-N and QF-(N+2) (interleaved, so SF-1 = M97+M98
      // and SF-2 = M99+M100 — matches FIFA's actual bracket).
      ms.forEach((m, i) => {
        const w = i % half;  // position within the wing (0..half-1)
        let y;
        if (round === "round-of-16") {
          const slot = r16IdToSlot.get(m.id);
          const parentSlots = R16_TO_R32[slot];
          const yA = pos[slotToMatch["round-of-32"].get(parentSlots[0]).id].y;
          const yB = pos[slotToMatch["round-of-32"].get(parentSlots[1]).id].y;
          y = (yA + yB) / 2;
        } else if (round === "quarterfinals") {
          const slot = qfIdToSlot.get(m.id);
          const r16SlotA = (slot - 1) * 2 + 1;
          const r16SlotB = slot * 2;
          const yA = pos[slotToMatch["round-of-16"].get(r16SlotA).id].y;
          const yB = pos[slotToMatch["round-of-16"].get(r16SlotB).id].y;
          y = (yA + yB) / 2;
        } else if (round === "semifinals") {
          // Interleaved pairing: SF slot N takes QF slots N and N+2.
          // SF-1 → QF-1 (M97) + QF-3 (M98); SF-2 → QF-2 (M99) + QF-4 (M100).
          const slot = i + 1;
          const qfSlotA = slot;
          const qfSlotB = slot + 2;
          const yA = pos[slotToMatch["quarterfinals"].get(qfSlotA).id].y;
          const yB = pos[slotToMatch["quarterfinals"].get(qfSlotB).id].y;
          y = (yA + yB) / 2;
        }
        pos[m.id] = { y, side: halfOfMatch(m) === 1 ? "L" : "R" };
      });
    }
    place("round-of-32");
    place("round-of-16");
    place("quarterfinals");
    place("semifinals");
    place("final");
    if (third) pos[third.id] = { y: 58, side: "C" };

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
      if (stage === "3rd-place-match") return 50 - pxToPct(CARD_W) / 2;  // centered under Final
      const offsetPx = COL_PX[stage] || 0;
      const offsetPct = pxToPct(offsetPx);
      if (side === "L") return offsetPct;
      // Mirror: 100% - left_offset% - card_width%
      return 100 - offsetPct - pxToPct(CARD_W);
    }
    function cardRightX(stage, side) {
      if (stage === "final") return 50;
      if (stage === "3rd-place-match") return 50 + pxToPct(CARD_W) / 2;  // centered under Final
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
      const slotMap = slotToMatch[stage];
      if (!slotMap) return;
      // All knockout pairings come from espn_url — not from a naive
      // (i, i+1) over time-sorted matches, because each round's actual
      // bracket pairings are independent of kickoff order:
      //
      //   round-of-32: (1,3) (2,5) (4,6) (7,8) (9,10) (11,12) (13,15) (14,16)
      //   round-of-16: (1,2) (3,4) (5,6) (7,8)
      //   quarterfinals: (1,2) (3,4)
      //   semifinals: (1,2)
      //
      // Lines will cross when sorted by time — that's the real bracket,
      // not a display bug.
      const parents = (byRound[nextStage] || []).map(m => ({
        match: m,
        // Use team-aware slot lookup for R16, QF, and SF parents so
        // decided matches (whose URL has been rewritten to team names
        // instead of slot refs) still draw the correct V-shape
        // connectors.
        slots: nextStage === "round-of-16" ? r16ParentSlotsHardcoded(m)
             : nextStage === "quarterfinals" ? qfParentSlots(m)
             : nextStage === "semifinals" ? (SF_TO_QF_SLOTS[sfIdToSlot.get(m.id)] || parentSlots(m, "quarterfinals"))
             : parentSlots(m, stage),
      }));
      for (const p of parents) {
        const parent = p.match;
        const [slotA, slotB] = p.slots;
        const a = slotMap.get(slotA);
        const b = slotMap.get(slotB);
        if (!a || !b || !parent) continue;
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
      span.textContent = i18n(l.key);
      labels.appendChild(span);
    }
    // Append above the butterfly (not inside it) so the labels sit
    // in normal flow above the cards and don't overlap the topmost
    // R32 card.
    const scroll = container.parentElement;
    if (scroll) scroll.insertBefore(labels, container);

    // Build cards
    function appendCard(m, customY, attrs) {
      if (!m) return;
      const p = pos[m.id];
      const card = buildBracketCard(m, p);
      card.style.top = (customY != null ? customY : p.y) + "%";
      if (attrs) for (const k in attrs) card.dataset[k] = attrs[k];
      container.appendChild(card);
    }
    // Pair index for R32 cards (0..7) so CSS can highlight which two
    // cards feed the same R16 match. Index is the position in the
    // R32 visual display order on each wing: (0,1)(2,3)(4,5)(6,7).
    byRound["round-of-32"].forEach((m, idx) => {
      if (!m) return;
      appendCard(m, null, { pair: String(Math.floor(idx / 2)) });
    });
    for (const r of rounds.slice(1)) for (const m of byRound[r] || []) appendCard(m);
    if (third) {
      // Place the 3rd-place match directly below the Final so the
      // pair reads as a cohesive unit (Final 46%, 3rd 58%, gap 12%).
      // No connecting lines (per Frank: "放到一二名下面就好，不用
      // 联线").
      pos[third.id] = { y: 58, side: "C" };
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
    const roundLabel = showLabel ? `<span class="bracket-round-label">${escapeHtml(i18n(roundKey))}</span>` : "";
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
          m.status === "LIVE" ? "● " + i18n("status.live.short") :
          m.status === "FINAL" ? i18n("status.final.short") :
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
    const open = () => {
      ul.hidden = false;
      // Always land at the top of the list when reopening — don't
      // inherit a stale scrollTop from a previous session.
      ul.scrollTop = 0;
      filterTeamList();
    };
    input.addEventListener("focus", open);
    input.addEventListener("input", filterTeamList);
    caret?.addEventListener("click", () => {
      if (ul.hidden) open();
      else ul.hidden = true;
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
      const city = v.city ? ` <span class="opt-city">${escapeHtml(v.city)}</span>` : "";
      li.innerHTML = `<span class="opt-name">${escapeHtml(v.name)}${city}</span><span class="opt-meta">${count}</span>`;
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
    if (!allData) { label.textContent = i18n("venues.all", { n: 0 }); return; }
    const total = allData.facets?.venues?.length || 0;
    if (filters.venues.length === 0) {
      label.textContent = i18n("venues.all", { n: total });
    } else if (filters.venues.length === 1) {
      label.textContent = i18n("venue.single", { name: filters.venues[0] });
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
      // Land at the top on every open so a stale scroll position
      // from a previous session doesn't hide the first venues.
      if (open) ul.scrollTop = 0;
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
    // Always default to the Matches tab on a fresh load — we don't
    // want a stale "standings" / "scorers" / etc. to trap the user
    // after a refresh.
    return "matches";
  }
  function saveView(_v) {
    // No-op: view is intentionally not persisted across reloads.
  }
  function setView(v) {
    if (v === "standings" || v === "scorers" || v === "matches" || v === "weekly" || v === "odds") currentView = v;
    updateViewPills();
    // Hide filters in any non-match view (standings, scorers, ai).
    const filterEl = $("#filters");
    if (filterEl) filterEl.hidden = currentView !== "matches";
    // The knockout bracket only makes sense next to the match list.
    // Hide it on alternate views. Standings keeps the bracket below
    // it for backwards compatibility.
    const bracketEl = $("#bracket-section");
    if (bracketEl) {
      bracketEl.hidden = currentView !== "matches" && currentView !== "standings";
    }
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
    // Build the countdown map: sort by kickoff_utc and assign each
    // match a reverse position (total - index). The Final is the last
    // chronologically so it gets 1; the first match gets 104.
    matchCountdown = new Map();
    {
      const sorted = [...allMatches].sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
      const total = sorted.length;
      for (let i = 0; i < sorted.length; i++) {
        matchCountdown.set(sorted[i].id, total - i);
      }
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
    $$("[data-i18n]").forEach((el) => { el.textContent = i18n(el.dataset.i18n); });
    $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = i18n(el.dataset.i18nPlaceholder); });
    $$("[data-i18n-title]").forEach((el) => { el.title = i18n(el.dataset.i18nTitle); });
    $$("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", i18n(el.dataset.i18nAria)); });
    updateLangPills();
    updateViewPills();
    updateVenueTrigger();
    // Apply persisted view (hide filters if standings or scorers)
    if (currentView !== "matches") {
      const filterEl = $("#filters");
      if (filterEl) filterEl.hidden = true;
      const bracketEl = $("#bracket-section");
      if (bracketEl && currentView !== "standings") bracketEl.hidden = true;
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
    div.innerHTML = `<strong>${escapeHtml(i18n("error.title"))}</strong><br />${escapeHtml(String(err))}<br /><br />${escapeHtml(i18n("error.hint"))}`;
    content.appendChild(div);
  }

  // ───────────────────────────────────────────────────────────────
  // Render: Knockout Odds (per-group position probabilities)
  //
  // Loads data/knockout-odds.json (computed by
  // scripts/compute_knockout_odds.py via Monte Carlo). Renders a
  // grid of group cards, each with 4 team rows showing a stacked
  // bar of {1st / 2nd / 3rd / 4th} probabilities and an overall
  // "advance to R32" badge.
  // ───────────────────────────────────────────────────────────────
  const ODDS_JSON_URL = "data/knockout-odds.json";
  const ODDS_CACHE_KEY = "wc2026.odds.v1";
  const ODDS_CACHE_TTL_MS = 5 * 60 * 1000;
  let oddsData = null;
  let oddsLoading = false;

  async function loadOdds(force = false) {
    if (!force && oddsData) return oddsData;
    if (!force) {
      try {
        const raw = sessionStorage.getItem(ODDS_CACHE_KEY);
        if (raw) {
          const { at, data } = JSON.parse(raw);
          if (Date.now() - at < ODDS_CACHE_TTL_MS) {
            oddsData = data;
            return data;
          }
        }
      } catch { /* ignore */ }
    }
    if (oddsLoading) return oddsData;
    oddsLoading = true;
    try {
      const res = await fetch(`${ODDS_JSON_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      oddsData = data;
      try { sessionStorage.setItem(ODDS_CACHE_KEY, JSON.stringify({ at: Date.now(), data })); } catch { /* ignore */ }
      return data;
    } finally {
      oddsLoading = false;
    }
  }

  function formatPct(p) {
    if (p == null) return "—";
    if (p >= 99.95) return "100%";
    if (p < 0.05) return "0%";
    return `${p.toFixed(1)}%`;
  }

  function renderOdds() {
    const content = $("#content");
    content.innerHTML = "";
    const countEl = $("#result-count");
    if (countEl) countEl.textContent = "";
    const placeholder = document.createElement("div");
    placeholder.className = "loading";
    placeholder.textContent = i18n("loading");
    content.appendChild(placeholder);

    loadOdds().then((data) => {
      content.innerHTML = "";
      if (!data || !data.groups || data.groups.length === 0) {
        renderOddsEmpty(content);
        return;
      }
      renderOddsBody(content, data);
    }).catch((err) => {
      content.innerHTML = "";
      renderOddsEmpty(content, err);
    });
  }

  function renderOddsEmpty(content, err) {
    const div = document.createElement("div");
    div.className = "empty";
    const errBlock = err && !/HTTP\s*404/i.test(String(err))
      ? `<div class="empty-hint" style="opacity:.6">${escapeHtml(String(err))}</div>`
      : "";
    div.innerHTML = `<div>${escapeHtml(i18n("odds.empty.title", "No knockout odds yet."))}</div>
      <div class="empty-hint">${escapeHtml(i18n("odds.empty.hint", "Run scripts/compute_knockout_odds.py to generate."))}</div>
      ${errBlock}`;
    content.appendChild(div);
  }

  // 2026 WC R32 bracket — each match is one of 16 R32 games. The
  // home/away slots are either a fixed group+position (e.g. "winner
  // of A") or a "best 3rd" pool that resolves to whichever 3rd-place
  // team is matched there after the group stage. The 3rd-place pool
  // is shown as all 12 teams sorted by p_3rd_top8 — the user can
  // mentally filter by the bracket rules. (The "specific 5 groups"
  // pattern in the ESPN URL is bracket-dependent and reshuffles per
  // scenario; surfacing it would be more confusing than illuminating.)
  const R32_BRACKET = [
    { id: "760486", date: "2026-06-28", time: "2:00 PM", label: "2A vs 2B",
      home: { kind: "runnerup", group: "A" }, away: { kind: "runnerup", group: "B" } },
    { id: "760487", date: "2026-06-29", time: "12:00 PM", label: "1C vs 2F",
      home: { kind: "winner", group: "C" }, away: { kind: "runnerup", group: "F" } },
    { id: "760488", date: "2026-06-29", time: "8:00 PM", label: "1F vs 2C",
      home: { kind: "winner", group: "F" }, away: { kind: "runnerup", group: "C" } },
    { id: "760489", date: "2026-06-29", time: "3:30 PM", label: "1E vs Best 3rd",
      home: { kind: "winner", group: "E" }, away: { kind: "best3rd" } },
    { id: "760490", date: "2026-06-30", time: "12:00 PM", label: "2E vs 2I",
      home: { kind: "runnerup", group: "E" }, away: { kind: "runnerup", group: "I" } },
    { id: "760491", date: "2026-06-30", time: "8:00 PM", label: "1A vs Best 3rd",
      home: { kind: "winner", group: "A" }, away: { kind: "best3rd" } },
    { id: "760492", date: "2026-06-30", time: "4:00 PM", label: "1I vs Best 3rd",
      home: { kind: "winner", group: "I" }, away: { kind: "best3rd" } },
    { id: "760493", date: "2026-07-01", time: "3:00 PM", label: "1G vs Best 3rd",
      home: { kind: "winner", group: "G" }, away: { kind: "best3rd" } },
    { id: "760494", date: "2026-07-01", time: "7:00 PM", label: "1D vs Best 3rd",
      home: { kind: "winner", group: "D" }, away: { kind: "best3rd" } },
    { id: "760495", date: "2026-07-01", time: "11:00 AM", label: "1L vs Best 3rd",
      home: { kind: "winner", group: "L" }, away: { kind: "best3rd" } },
    { id: "760496", date: "2026-07-02", time: "6:00 PM", label: "2K vs 2L",
      home: { kind: "runnerup", group: "K" }, away: { kind: "runnerup", group: "L" } },
    { id: "760497", date: "2026-07-02", time: "2:00 PM", label: "1H vs 2J",
      home: { kind: "winner", group: "H" }, away: { kind: "runnerup", group: "J" } },
    { id: "760498", date: "2026-07-02", time: "10:00 PM", label: "1B vs Best 3rd",
      home: { kind: "winner", group: "B" }, away: { kind: "best3rd" } },
    { id: "760499", date: "2026-07-03", time: "2:00 PM", label: "2D vs 2G",
      home: { kind: "runnerup", group: "D" }, away: { kind: "runnerup", group: "G" } },
    { id: "760500", date: "2026-07-03", time: "5:00 PM", label: "1J vs 2H",
      home: { kind: "winner", group: "J" }, away: { kind: "runnerup", group: "H" } },
    { id: "760501", date: "2026-07-03", time: "8:30 PM", label: "1K vs Best 3rd",
      home: { kind: "winner", group: "K" }, away: { kind: "best3rd" } },
  ];

  function getTeamForGroup(groupName, data) {
    const g = (data.groups || []).find((x) => x.name === groupName);
    return g ? g.teams : null;
  }

  function getCandidatesForSlot(slot, data) {
    // Returns array of {team, probability} sorted by probability desc.
    if (slot.kind === "winner") {
      const teams = getTeamForGroup(`Group ${slot.group}`, data) || [];
      return teams
        .map((t) => ({ team: t, probability: t.p_1st || 0 }))
        .sort((a, b) => b.probability - a.probability);
    }
    if (slot.kind === "runnerup") {
      const teams = getTeamForSlot(slot.group, data);
      return (teams || [])
        .map((t) => ({ team: t, probability: t.p_2nd || 0 }))
        .sort((a, b) => b.probability - a.probability);
    }
    if (slot.kind === "best3rd") {
      // Pool all 12 groups' teams, sort by p_3rd_top8.
      const all = [];
      for (const g of (data.groups || [])) {
        for (const t of (g.teams || [])) {
          all.push({ team: t, probability: t.p_3rd_top8 || 0 });
        }
      }
      return all.sort((a, b) => b.probability - a.probability);
    }
    return [];
  }

  function getTeamForSlot(groupName, data) {
    return getTeamForGroup(`Group ${groupName}`, data);
  }

  function slotLabel(slot) {
    if (slot.kind === "winner") return i18n("odds.slot.winner", "Winner of Group {group}", { group: slot.group });
    if (slot.kind === "runnerup") return i18n("odds.slot.runnerup", "Runner-up of Group {group}", { group: slot.group });
    if (slot.kind === "best3rd") {
      // For 3rd slots, list all 12 groups (A-L) — the actual opponent
      // depends on the bracket which only resolves after group stage.
      return i18n("odds.slot.best3rd", "Best 3rd from {groups}", { groups: "A, B, C, D, E, F, G, H, I, J, K, L" });
    }
    return "";
  }

  function renderOddsBody(content, data) {
    const wrap = document.createElement("section");
    wrap.className = "odds-section";

    const head = document.createElement("header");
    head.className = "odds-head";
    const win = data.match_window || [];
    const winRange = win.length === 2
      ? `${formatDateWithDow(win[0])} → ${formatDateWithDow(win[1])}`
      : "";
    head.innerHTML = `
      <h2 class="odds-title">${escapeHtml(i18n("odds.title", "Knockout Odds"))}</h2>
      <p class="odds-hint">${escapeHtml(i18n("odds.hint", "Each R32 matchup and the teams that could fill each slot, computed by Monte Carlo simulation over the remaining group-stage matches. Top 2 + 8 best 3rd advance to the Round of 32."))}</p>
      <p class="odds-meta">
        <span>${escapeHtml(i18n("odds.sims", "Sims"))}: ${(data.n_simulations || 10000).toLocaleString()}</span>
        ${winRange ? `<span class="odds-meta-dot">·</span><span>${escapeHtml(winRange)}</span>` : ""}
      </p>
    `;
    wrap.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "odds-grid";
    for (const m of R32_BRACKET) {
      grid.appendChild(buildOddsMatchupCard(m, data));
    }
    wrap.appendChild(grid);

    content.appendChild(wrap);
  }

  function buildOddsMatchupCard(match, data) {
    const card = document.createElement("article");
    card.className = "odds-matchup-card";

    const head = document.createElement("header");
    head.className = "odds-matchup-head";
    const vs = i18n("odds.matchup.vs", "vs");
    head.innerHTML = `
      <h3 class="odds-matchup-label">${escapeHtml(match.label)}</h3>
      <p class="odds-matchup-when">${escapeHtml(formatDateWithDow(match.date))} · ${escapeHtml(match.time)}</p>
    `;
    card.appendChild(head);

    const body = document.createElement("div");
    body.className = "odds-matchup-body";
    body.appendChild(buildOddsSlotColumn(match.home, data, "home"));
    body.appendChild(buildOddsSlotColumn(match.away, data, "away"));
    card.appendChild(body);

    return card;
  }

  function buildOddsSlotColumn(slot, data, side) {
    const col = document.createElement("div");
    col.className = `odds-slot odds-slot--${side}`;

    const labelEl = document.createElement("div");
    labelEl.className = "odds-slot-label";
    labelEl.textContent = slotLabel(slot);
    col.appendChild(labelEl);

    const candidates = getCandidatesForSlot(slot, data);
    const list = document.createElement("div");
    list.className = "odds-slot-list";
    for (const { team, probability } of candidates) {
      list.appendChild(buildOddsSlotRow(team, probability, slot.kind));
    }
    col.appendChild(list);
    return col;
  }

  function buildOddsSlotRow(team, probability, slotKind) {
    const row = document.createElement("div");
    row.className = "odds-slot-row";
    const pct = Number(probability) || 0;
    const name = currentLang === "zh" && team.name_zh ? team.name_zh : team.name;
    const barClass =
      slotKind === "winner" ? "odds-bar--1" :
      slotKind === "runnerup" ? "odds-bar--2" :
      "odds-bar--3";
    row.innerHTML = `
      <div class="odds-slot-row-head">
        <span class="odds-slot-flag">${escapeHtml(team.flag || "")}</span>
        <span class="odds-slot-name">${escapeHtml(name)}</span>
        <span class="odds-slot-pct">${formatPct(pct)}</span>
      </div>
      <div class="odds-bar-row">
        <div class="odds-bar ${barClass}" style="width: ${pct}%"></div>
      </div>
    `;
    return row;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();