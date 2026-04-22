import json, os
from datetime import date, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")

I18N = {
    "en": {
        "title": "Custody Calendar",
        "dad": "Dad",
        "mom": "Mom",
        "today": "Today",
        "prev_month": "Prev",
        "next_month": "Next",
        "mode_spo": "SPO",
        "mode_espo": "ESPO",
        "lang_en": "EN",
        "lang_cn": "CN",
        "weekdays": ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],
        "months": ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"],
        "breaks": {
            "thanksgiving": "Thanksgiving Break",
            "christmas": "Christmas Break",
            "spring": "Spring Break",
            "summer": "Summer Break",
        },
        "noschool": "No School",
        "regular": "School Day",
        "spo_weekend": "Dad Weekend (SPO)",
        "thanksgiving_first_half": "Dad - TG 1st half",
        "thanksgiving_second_half": "Mom - TG 2nd half",
        "christmas_first_half": "Dad - Xmas 1st half",
        "christmas_second_half": "Mom - Xmas 2nd half",
        "spring_break": "Spring Break",
        "summer_dad_30_days": "Dad Summer (Jul 1-30)",
        "summer_mom_before_dad": "Mom Summer (before Dad)",
        "summer_mom_after_dad": "Mom Summer (after Dad)",
        "summer_remainder": "Mom Summer (remainder)",
        "summer_possessory": "Dad Summer (possessory)",
        "noschool_day": "No School",
        "regular_school_day": "School Day",
        "fathers_day": "Father's Day Weekend",
        "mothers_day": "Mother's Day Weekend",
        "thursday": "Thursday (Dad)",
        "weekend": "Dad Weekend",
        "default_custody": "Mom (default)",
        "spring_break": "Spring Break",
        "thanksgiving": "Thanksgiving",
        "christmas": "Christmas",
    },
    "cn": {
        "title": "抚养权日历",
        "dad": "爸爸",
        "mom": "妈妈",
        "today": "Today",
        "prev_month": "上月",
        "next_month": "下月",
        "mode_spo": "标准抚养令",
        "mode_espo": "扩展抚养令",
        "lang_en": "EN",
        "lang_cn": "CN",
        "weekdays": ["周日","周一","周二","周三","周四","周五","周六"],
        "months": ["一月","二月","三月","四月","五月","六月",
                   "七月","八月","九月","十月","十一月","十二月"],
        "breaks": {
            "thanksgiving": "感恩节假期",
            "christmas": "圣诞假期",
            "spring": "春假",
            "summer": "暑假",
        },
        "noschool": "No School",
        "regular": "上课日",
        "spo_weekend": "爸爸周末",
        "thanksgiving_first_half": "爸爸 - 感恩节前半",
        "thanksgiving_second_half": "妈妈 - 感恩节后半",
        "christmas_first_half": "爸爸 - 圣诞前半",
        "christmas_second_half": "妈妈 - 圣诞后半",
        "spring_break": "春假",
        "summer_dad_30_days": "爸爸暑假(7月1-30日)",
        "summer_mom_before_dad": "妈妈暑假(Dad前)",
        "summer_mom_after_dad": "妈妈暑假(Dad后)",
        "summer_remainder": "妈妈暑假(剩余)",
        "summer_possessory": "爸爸暑假",
        "noschool_day": "休息日",
        "regular_school_day": "上课日",
        "fathers_day": "父亲节周末",
        "mothers_day": "母亲节周末",
        "thursday": "周四(爸爸)",
        "weekend": "爸爸周末",
        "default_custody": "妈妈(默认)",
        "thanksgiving": "感恩节",
        "christmas": "圣诞节",
    }
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Custody Calendar -- {district}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; min-height: 100vh; }}
  .toolbar {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 12px 20px; background: #fff; border-bottom: 1px solid #ddd; position: sticky; top: 0; z-index: 100; }}
  .toolbar h1 {{ font-size: 1.1rem; margin-right: auto; }}
  button {{ padding: 6px 14px; border: 1px solid #aaa; border-radius: 6px; background: #fff; cursor: pointer; font-size: 0.9rem; }}
  button:hover {{ background: #eee; }}
  button.active {{ background: #333; color: #fff; border-color: #333; }}
  .cal-nav {{ display: flex; align-items: center; gap: 8px; margin: 16px 20px 0; }}
  .cal-nav span {{ font-size: 1.1rem; font-weight: 600; min-width: 200px; text-align: center; }}
  .calendar-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; padding: 12px 20px 24px; }}
  .month-box {{ background: #fff; border-radius: 10px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
  .month-title {{ text-align: center; font-weight: 600; margin-bottom: 8px; color: #333; font-size: 0.95rem; }}
  .day-headers {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; margin-bottom: 4px; }}
  .dh {{ text-align: center; font-size: 0.75rem; color: #888; padding: 2px; }}
  .days-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; }}
  .day {{ aspect-ratio: 1; display: flex; align-items: center; justify-content: center; font-size: 0.8rem; border-radius: 4px; cursor: default; position: relative; min-height: 32px; color: #333; }}
  .day.empty {{ background: transparent; }}
  .day.dad {{ background: #dbeafe; color: #1e40af; }}
  .day.mom {{ background: #fce7f3; color: #9d174d; }}
  .day.today {{ outline: 2px solid #333; outline-offset: -2px; font-weight: 700; }}
  .day:hover .tooltip {{ opacity: 1; visibility: visible; transform: translateY(0); }}
  .tooltip {{ position: absolute; bottom: 110%; left: 50%; transform: translateX(-50%) translateY(4px); background: #333; color: #fff; padding: 6px 10px; border-radius: 6px; font-size: 0.7rem; white-space: nowrap; z-index: 200; opacity: 0; visibility: hidden; transition: 0.15s; pointer-events: none; text-align: center; }}
  .tooltip::after {{ content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%); border: 5px solid transparent; border-top-color: #333; }}
  .legend {{ display: flex; gap: 20px; justify-content: center; padding: 8px; font-size: 0.85rem; }}
  .legend span {{ display: flex; align-items: center; gap: 6px; }}
  .legend .dad-swatch {{ width: 14px; height: 14px; border-radius: 3px; background: #dbeafe; border: 1px solid #1e40af; }}
  .legend .mom-swatch {{ width: 14px; height: 14px; border-radius: 3px; background: #fce7f3; border: 1px solid #9d174d; }}
  .footer {{ text-align: center; padding: 16px; color: #888; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="toolbar">
  <h1 id="title">{title}</h1>
  <button id="langToggle">CN</button>
  <button id="espoBtn" class="active">ESPO</button>
  <button id="spoBtn">SPO</button>
</div>
<div class="cal-nav">
  <button id="prevBtn">&lt;</button>
  <span id="curRange"></span>
  <button id="nextBtn">&gt;</button>
</div>
<div class="legend">
  <span><div class="dad-swatch"></div> {dad}</span>
  <span><div class="mom-swatch"></div> {mom}</span>
</div>
<div class="calendar-grid" id="calendar"></div>
<div class="footer">TX Sec.153.314 -- {district}</div>
<script>
const I18N = {i18n_json};
const ESPO_INTERVALS = {espo_intervals_json};
const SPO_INTERVALS = {spo_intervals_json};
let lang = 'en';
let mode = 'espo'; // default to ESPO
let displayedYear = new Date().getFullYear();
let displayedMonth = new Date().getMonth();

document.getElementById('espoBtn').onclick = () => {{
  mode = 'espo';
  document.getElementById('espoBtn').classList.add('active');
  document.getElementById('spoBtn').classList.remove('active');
  displayAllMonths();
}};
document.getElementById('spoBtn').onclick = () => {{
  mode = 'spo';
  document.getElementById('spoBtn').classList.add('active');
  document.getElementById('espoBtn').classList.remove('active');
  displayAllMonths();
}};

function getActiveIntervals() {{
  return mode === 'espo' ? ESPO_INTERVALS : SPO_INTERVALS;
}}

function queryCustodian(d) {{
  const target = new Date(d);
  const intervals = getActiveIntervals();
  for (const iv of intervals) {{
    const s = new Date(iv.start);
    const e = new Date(iv.end);
    if (s <= target && target <= e) return iv.custodian;
    if (s > target) break;
  }}
  return null;
}}

function queryLabel(d) {{
  const target = new Date(d);
  const intervals = getActiveIntervals();
  for (const iv of intervals) {{
    const s = new Date(iv.start);
    const e = new Date(iv.end);
    if (s <= target && target <= e) return iv.reason;
    if (s > target) break;
  }}
  return null;
}}

function fmtDate(d) {{ return d.toISOString().slice(0, 10); }}

function displayAllMonths() {{
  const container = document.getElementById('calendar');
  container.innerHTML = '';

  // Determine the display range: from Aug of the prior school year through Dec after current school year
  // This ensures we see Aug previous year → current month → Aug next year
  const now = new Date();
  const nowYear = now.getFullYear();
  const nowMonth = now.getMonth(); // 0-indexed (March = 2)

  // School years run Aug–Jul. Figure out which school year we're in.
  // If nowMonth >= 7 (Aug–Dec), current school year started this August
  // If nowMonth < 7 (Jan–Jul), current school year started last August
  let currentSchoolYearStart;
  if (nowMonth >= 7) {{
    currentSchoolYearStart = nowYear;
  }} else {{
    currentSchoolYearStart = nowYear - 1;
  }}

  // Show: Aug of the school year BEFORE current + all of current school year
  // e.g., if current SY starts Aug 2025, show Aug 2024 through Aug 2026
  const displayStart = new Date(currentSchoolYearStart - 1, 7, 1);   // Aug of prior year
  const displayEnd   = new Date(currentSchoolYearStart + 1, 11, 31); // Dec of following year

  const monthsToShow = [];
  let cur = new Date(displayStart);
  while (cur <= displayEnd) {{
    monthsToShow.push({{ year: cur.getFullYear(), month: cur.getMonth() }});
    cur.setMonth(cur.getMonth() + 1);
  }}

  for (const m of monthsToShow) {{ renderMonth(m.year, m.month); }}
}}

function renderMonth(year, month) {{
  const container = document.getElementById('calendar');
  // NOTE: container.innerHTML is NOT cleared here — displayAllMonths() clears once before looping
  const t = I18N[lang];
  document.getElementById('curRange').textContent = t.months[month] + ' ' + year;

  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startPad = firstDay.getDay();

  const monthDiv = document.createElement('div');
  monthDiv.className = 'month-box';

  const title = document.createElement('div');
  title.className = 'month-title';
  title.textContent = t.months[month] + ' ' + year;
  monthDiv.appendChild(title);

  const dhDiv = document.createElement('div');
  dhDiv.className = 'day-headers';
  t.weekdays.forEach(w => {{
    const d = document.createElement('div');
    d.className = 'dh';
    d.textContent = w;
    dhDiv.appendChild(d);
  }});
  monthDiv.appendChild(dhDiv);

  const grid = document.createElement('div');
  grid.className = 'days-grid';

  for (let i = 0; i < startPad; i++) {{
    const cell = document.createElement('div');
    cell.className = 'day empty';
    grid.appendChild(cell);
  }}

  const today = new Date();
  for (let d = 1; d <= lastDay.getDate(); d++) {{
    const cell = document.createElement('div');
    const cellDate = new Date(year, month, d);
    const dateStr = fmtDate(cellDate);
    const custodian = queryCustodian(dateStr);
    const reason = queryLabel(dateStr);

    cell.className = 'day';
    if (custodian) cell.classList.add(custodian);
    if (reason) cell.classList.add('reason-' + reason);
    if (year === today.getFullYear() && month === today.getMonth() && d === today.getDate()) {{
      cell.classList.add('today');
    }}
    cell.textContent = d;

    const tip = document.createElement('div');
    tip.className = 'tooltip';
    if (custodian) {{
      const who = t[custodian];
      const what = reason ? (t[reason] || reason) : who;
      tip.textContent = who + ': ' + what;
    }} else {{
      tip.textContent = dateStr;
    }}
    cell.appendChild(tip);
    grid.appendChild(cell);
  }}

  monthDiv.appendChild(grid);
  container.appendChild(monthDiv);
}}

document.getElementById('prevBtn').onclick = () => {{
  window.scrollTo({{ top: 0, behavior: 'smooth'}});
}};
document.getElementById('nextBtn').onclick = () => {{
  window.scrollTo({{ top: document.body.scrollHeight, behavior: 'smooth'}});
}};
document.getElementById('langToggle').onclick = () => {{
  lang = lang === 'en' ? 'cn' : 'en';
  document.getElementById('title').textContent = I18N[lang].title;
  renderMonth(displayedYear, displayedMonth);
}};
document.getElementById('modeToggle').onclick = () => {{
  mode = mode === 'espo' ? 'spo' : 'espo';
  displayAllMonths();
}};

displayAllMonths();
// Ensure ESPO mode is active on load
document.getElementById('espoBtn').classList.add('active');
document.getElementById('spoBtn').classList.remove('active');
mode = 'espo';
</script>
</body>
</html>
"""

class HTMLBuilder:
    def __init__(self, district, espo_intervals, spo_intervals=None):
        self.district = district
        self.espo_intervals = espo_intervals
        self.spo_intervals = spo_intervals or espo_intervals

    def build(self, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        html = HTML_TEMPLATE.format(
            district=self.district,
            title=I18N["en"]["title"],
            dad=I18N["en"]["dad"],
            mom=I18N["en"]["mom"],
            espo_intervals_json=json.dumps(self.espo_intervals, ensure_ascii=False),
            spo_intervals_json=json.dumps(self.spo_intervals, ensure_ascii=False),
            i18n_json=json.dumps(I18N, ensure_ascii=False)
        )
        with open(dest, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Generated: {dest}")
