#!/usr/bin/env python3
"""
One-shot enrichment for all knockout-stage weekly picks:
  - Round of 16 (8 matches)
  - Quarterfinals (4 matches)
  - Semifinals (2 matches)
  - Final + 3rd-place match (2 matches)

Reads data/weekly-picks.json (which already has the auto fields
populated by build_weekly_picks.py) and fills in subjective fields
for every knockout match.

Idempotent — re-run to refresh content; otherwise the
build_weekly_picks.py "preserve manual" path keeps whatever is
on disk.

Usage: python3 scripts/enrich_knockout_picks.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "weekly-picks.json"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ────────────────────────────────────────────────────────────
# Round intros
# ────────────────────────────────────────────────────────────
ROUND_INTROS = {
    "round-of-16-2026-07-04-2026-07-07": {
        "round_intro_zh": (
            "16 强开打，8 场定胜负定 8 个 8 强名额。本届 1/8 决赛横跨 4 天（7/4 周六 - 7/7 周二），"
            "上半区 M89-M92 在 7/4-7/5 集中打完，下半区 M93-M96 在 7/6-7/7 收尾。"
            "上半区已经决出两场结果：法国 4-1 轻取巴拉圭，摩洛哥 2-1 力克加拿大——"
            "这两支队伍的 QF 对决将是本届淘汰赛第一场有完整故事线的 1/4 决赛。\n\n"
            "本周 8 场 1/8 决赛里最不能错过的有 4 场：Brazil vs Norway（7/5 周日 3 PM CT，"
            "巴西本届首次硬仗）、Mexico vs England（7/5 周日 7 PM CT，东道主墨西哥迎战欧洲劲旅）、"
            "Portugal vs Spain（7/6 周一 2 PM CT，伊比利亚德比）、Argentina vs Egypt（7/7 周二 11 AM CT，"
            "卫冕冠军登场）。"
        ),
        "round_intro_en": (
            "The R16 is here — 8 single-elimination matches, 4 days (Sat 7/4 - Tue 7/7). "
            "The upper half (M89-M92) wraps 7/4-7/5; the lower half (M93-M96) finishes 7/6-7/7. "
            "Two upper-half results are in: France 4-1 over Paraguay and Morocco 2-1 over Canada — "
            "those two meet in the QF, the first knockout game with a fully-formed storyline.\n\n"
            "Of the 8 R16 matches, four you can't miss: Brazil vs Norway (Sun 3 PM CT, Brazil's "
            "first real test), Mexico vs England (Sun 7 PM CT, host Mexico vs European power), "
            "Portugal vs Spain (Mon 2 PM CT, Iberian derby), and Argentina vs Egypt (Tue 11 AM CT, "
            "the champions' first appearance)."
        ),
        "manual_note_zh": "排序按推荐分降序。7/5 下午（CT）发出，已完赛比赛的赛前预测保留供参考。",
        "manual_note_en": "Sorted by recommendation score, descending. Issued Sun 5 Jul PM CT; pre-game analysis kept for finished matches as reference.",
    },
    "quarterfinals-2026-07-09-2026-07-11": {
        "round_intro_zh": (
            "1/4 决赛，4 场定 4 强。本届 QF 横跨 3 天（7/9 周四 - 7/11 周六），"
            "上半区两场 QF 集中在 7/9-7/10，下半区两场在 7/11 集中打完。\n\n"
            "上半区 QF 已确认：France vs Morocco（7/9 周四 3 PM CT，Foxborough）"
            "——法国本届首次硬仗 + 摩洛哥本届最大黑马，胜者预定 SF-1 席位。\n\n"
            "本周 4 场 QF 里最值得收看的：France vs Morocco（已经成型的对决）、"
            "Brazil/Norway vs Mexico/England（7/11 周六 4 PM CT，Miami）"
            "——上半区第二场 QF，胜者是上半区 SF-1 还是下半区 SF-2 取决于这一场。"
        ),
        "round_intro_en": (
            "Quarterfinals — 4 matches decide the final 4. The QF window is 3 days "
            "(Thu 7/9 - Sat 7/11). Both upper-half QFs are 7/9-7/10; both lower-half QFs "
            "are 7/11.\n\n"
            "Upper-half QF is locked in: France vs Morocco (Thu 7/9 3 PM CT, Foxborough) — "
            "France's first knockout test + Morocco's biggest WC run ever. Winner takes SF-1.\n\n"
            "Of the 4 QFs, two to plan around: France vs Morocco (now a real game with a "
            "storyline), and the Brazil/Norway vs Mexico/England clash (Sat 7/11 4 PM CT, "
            "Miami) — winner of this QF is the upper-half SF-1 candidate from that side."
        ),
        "manual_note_zh": "排序按推荐分降序。7/5 下午（CT）发出。",
        "manual_note_en": "Sorted by recommendation score, descending. Issued Sun 5 Jul PM CT.",
    },
    "semifinals-2026-07-14-2026-07-15": {
        "round_intro_zh": (
            "半决赛，2 场定决赛名额。本届 SF 横跨 2 天（7/14 周二 - 7/15 周三），都在美国境内："
            "SF-1 在 AT&T 体育场（阿灵顿，德州）7/14 周二 2 PM CT 开球，"
            "SF-2 在 Mercedes-Benz 体育场（亚特兰大）7/15 周三 2 PM CT 开球。\n\n"
            "本周 2 场 SF 都是 4 强对决——上半区 SF-1 由上半区两场 QF 胜者产生，"
            "下半区 SF-2 由下半区两场 QF 胜者产生。两场胜者会师 7/19 决赛（MetLife 体育场）。"
        ),
        "round_intro_en": (
            "Semifinals — 2 matches decide the Final. Both games in the US: "
            "SF-1 at AT&T Stadium (Arlington, TX) Tue 7/14 2 PM CT, "
            "SF-2 at Mercedes-Benz Stadium (Atlanta, GA) Wed 7/15 2 PM CT.\n\n"
            "SF-1 = upper half (QF-1 + QF-2 winners); SF-2 = lower half (QF-3 + QF-4 winners). "
            "Both winners advance to the 7/19 Final at MetLife Stadium."
        ),
        "manual_note_zh": "排序按推荐分降序。7/5 下午（CT）发出，胜者尚未产生。",
        "manual_note_en": "Sorted by recommendation score, descending. Issued Sun 5 Jul PM CT; SF matchups pending QF results.",
    },
    "final-2026-07-19-2026-07-19": {
        "round_intro_zh": (
            "决赛周末。3rd Place 7/18 周六 4 PM CT 在 Hard Rock 体育场（迈阿密），"
            "Final 7/19 周日 2 PM CT 在 MetLife 体育场（新泽西）——"
            "48 队 104 场比赛的最终章。\n\n"
            "Final 是 4 年一届的全球最大单一体育赛事，本届首次 48 队赛制；"
            "MetLife 体育场容量 82,500，是 NFL 巨人队和喷气机队主场，"
            "也是 2014 超级碗 XLVIII 场地——巴西 7-1 德国的惨案就发生在这里。"
            "3rd Place 决赛在 Hard Rock（迈阿密海豚队主场）举行，是 SF 败者的最后一场。"
        ),
        "round_intro_en": (
            "Final weekend. 3rd-place match Sat 7/18 4 PM CT at Hard Rock Stadium (Miami); "
            "the Final itself Sun 7/19 2 PM CT at MetLife Stadium (East Rutherford, NJ) — "
            "the closing chapter of 104 matches across 48 teams.\n\n"
            "The Final is the largest single-sport event on the planet, held every 4 years. "
            "MetLife (capacity 82,500) hosts NFL's Giants and Jets and was the site of Super Bowl "
            "XLVIII — the famous 7-1 Brazil-Germany semifinal in 2014. The 3rd-place match is the "
            "losers' last game, at Hard Rock (Miami Dolphins' NFL home)."
        ),
        "manual_note_zh": "排序按推荐分降序。7/5 下午（CT）发出，参赛队尚未产生。",
        "manual_note_en": "Sorted by recommendation score, descending. Issued Sun 5 Jul PM CT; finalists pending SF results.",
    },
}


# ────────────────────────────────────────────────────────────
# Per-match enrichment
# ────────────────────────────────────────────────────────────
ANALYSIS: dict[str, dict] = {
    # ───── Round of 16 ─────
    # 760502 — Sat 7/4 12:00 PM CT — Canada vs Morocco (FINAL: Morocco 2-1)
    "760502": {
        "headline_zh": "摩洛哥继续黑马之旅，加拿大北美内战梦碎",
        "headline_en": "Morocco's giant-killing run continues; Canada's co-host dream ends",
        "watch_for_zh": [
            "摩洛哥本届 5 战 4 胜 1 平不败——小组赛 1-0 阿根廷 + 1-0 巴西 + 0-0 法国 + 16 强 2-1 加拿大",
            "加拿大本届首次打入 16 强（A 组第二 4 分），戴维斯领衔的反击线是最大看点",
            "Achraf Hakimi #2（巴黎圣日耳曼）本届已进 3 球，是摩洛哥进攻核心"
        ],
        "watch_for_en": [
            "Morocco went 5 games unbeaten (W4 D1) at this WC — beat ARG 1-0, BRA 1-0, FRA 0-0, CAN 2-1",
            "Canada (Group A runner-up, 4 pts) made the R16 for the first time since 1986",
            "Achraf Hakimi #2 (PSG) is Morocco's offensive engine — 3 goals at this WC"
        ],
        "key_players_zh": [
            "阿什拉夫·哈基米 #2（摩洛哥 / 巴黎圣日耳曼）",
            "索菲安·阿姆拉巴特 #4（摩洛哥 / 佛罗伦萨）",
            "阿方索·戴维斯 #19（加拿大队长 / 拜仁慕尼黑）"
        ],
        "key_players_en": [
            "Achraf Hakimi #2 (Morocco / PSG)",
            "Sofyan Amrabat #4 (Morocco / Fiorentina)",
            "Alphonso Davies #19 (Canada captain / Bayern Munich)"
        ],
        "news_focus_zh": "摩洛哥本届 5 场不败 + 3 胜欧洲/南美传统强队，是本届最大黑马",
        "news_focus_en": "Morocco's 5-game unbeaten run includes 3 wins over European/South American powers — the story of the tournament",
        "record_potential_zh": [
            "摩洛哥晋级将是 1986 年后首次非洲球队打入 8 强",
            "Hakimi 若再进 1 球追平摩洛哥队史单届世界杯进球纪录（5 球，1966 年个人）"
        ],
        "record_potential_en": [
            "A Morocco QF would be the first African team in the QF since 2010 (Ghana)",
            "One more Hakimi goal ties the Morocco single-WC record (5, set in 1966)"
        ],
        "manual_author": "claude",
    },
    # 760503 — Sat 7/4 4:00 PM CT — Paraguay vs France (FINAL: France 4-1)
    "760503": {
        "headline_zh": "Mbappé 帽子戏法，法国 4-1 巴拉圭晋级",
        "headline_en": "Mbappé hat trick sends France past Paraguay 4-1",
        "watch_for_zh": [
            "Mbappé #10 本场帽子戏法（3 球），本届 5 球领跑金靴榜",
            "巴拉圭本届黑马成色受检——首次面对 FIFA #3 法国",
            "法国本届进攻端 Mbappé + 格里兹曼 + 登贝莱三叉戟成型"
        ],
        "watch_for_en": [
            "Mbappé #10 netted a hat trick (3 goals), now leads the Golden Boot race at 5",
            "Paraguay (Group D 3rd, 4 pts) faced FIFA #3 France for the first time",
            "France's Mbappé-Griezmann-Dembélé front three is firing on all cylinders"
        ],
        "key_players_zh": [
            "基利安·姆巴佩 #10（法国队长 / 皇家马德里，5 球金靴榜首）",
            "安托万·格里兹曼 #7（法国 / 马德里竞技）",
            "奥斯曼·登贝莱 #11（法国 / 巴黎圣日耳曼）"
        ],
        "key_players_en": [
            "Kylian Mbappé #10 (France captain / Real Madrid, 5 goals, Golden Boot leader)",
            "Antoine Griezmann #7 (France / Atlético Madrid)",
            "Ousmane Dembélé #11 (France / PSG)"
        ],
        "news_focus_zh": "法国连续 4 届世界杯打入 8 强——Mbappé 时代正式接过齐达内/亨利火炬",
        "news_focus_en": "France reached the QF for the 4th straight WC — the Mbappé era takes over from Zidane/Henry",
        "record_potential_zh": [
            "Mbappé 本届若再进 1 球追平 1986 年莱因克尔 6 球的当届最佳",
            "法国连续 4 届 8 强是 1998-2014 黄金一代的延续"
        ],
        "record_potential_en": [
            "One more Mbappé goal ties the 1986 Lineker-era top-scorer mark of 6",
            "France's 4-straight QF streak continues the 1998-2014 golden generation"
        ],
        "manual_author": "claude",
    },
    # 760504 — Sun 7/5 3:00 PM CT — Brazil vs Norway
    "760504": {
        "headline_zh": "巴西 vs 挪威——维尼修斯 vs 哈兰德的世界杯首秀",
        "headline_en": "Brazil vs Norway — Vinícius vs Haaland's WC knockout bow",
        "watch_for_zh": [
            "挪威本届小组赛 1-0 意大利 + 3-2 法国——首次打入 16 强，2026 最大黑马之一",
            "Erling Haaland #9（曼城）本届已进 3 球，淘汰赛首秀受关注",
            "巴西本届 5 球分布在 5 个不同球员——多点开花让挪威防线难以针对性布防",
            "挪威 2002 年后首次 16 强（24 年等一回），本届靠团队防守 + 反击偷分"
        ],
        "watch_for_en": [
            "Norway beat Italy 1-0 and France 3-2 in the group — first R16 since 2002 (24 years)",
            "Erling Haaland #9 (Man City) has 3 goals; his knockout debut is the story",
            "Brazil's 5 group goals came from 5 different scorers — too many threats to mark",
            "Norway's identity is compact defending + counter-attack; this is Brazil's biggest contrast"
        ],
        "key_players_zh": [
            "埃尔林·哈兰德 #9（挪威 / 曼城，3 球）",
            "马丁·厄德高 #10（挪威队长 / 阿森纳）",
            "维尼修斯·儒尼奥尔 #7（巴西 / 皇家马德里）",
            "罗德里戈 #10（巴西 / 皇家马德里）"
        ],
        "key_players_en": [
            "Erling Haaland #9 (Norway / Man City, 3 goals)",
            "Martin Ødegaard #10 (Norway captain / Arsenal)",
            "Vinícius Júnior #7 (Brazil / Real Madrid)",
            "Rodrygo #10 (Brazil / Real Madrid)"
        ],
        "news_focus_zh": "维尼修斯 vs 哈兰德——两位 25 岁以下最贵球员的世界杯首次正面对决",
        "news_focus_en": "Vini vs Haaland — the two most valuable U-25 players face off for the first time at a WC",
        "record_potential_zh": [
            "挪威晋级将是 1998 年后首次 8 强——28 年等一回",
            "哈兰德若再进 2 球追平挪威队史单届世界杯进球纪录（5 球）"
        ],
        "record_potential_en": [
            "A Norway QF would be their first since 1998 — a 28-year wait",
            "Two more Haaland goals tie Norway's single-WC record (5)"
        ],
        "manual_author": "claude",
    },
    # 760505 — Sun 7/5 7:00 PM CT — Mexico vs England
    "760505": {
        "headline_zh": "墨西哥主场迎战英格兰——东道主 vs 欧洲劲旅",
        "headline_en": "Mexico host England at altitude — the co-host's biggest test",
        "watch_for_zh": [
            "墨西哥本届小组赛 3 胜（A 组头名 9 分），3 场全胜创队史首次",
            "墨西哥本届 6 进球由 6 个不同球员攻入——多点开花",
            "英格兰本届小组赛 7 进球，Harry Kane #9 已进 3 球",
            "Estadio Banorte 在墨西哥城海拔 2,240 米——高原效应是英格兰最大挑战"
        ],
        "watch_for_en": [
            "Mexico went 9/9 in the group — 3 wins for the first time ever",
            "Mexico's 6 goals came from 6 different scorers — too many threats for England",
            "England scored 7 group goals; Kane #9 (Bayern) has 3",
            "Estadio Banorte sits at 2,240 m altitude — Mexico's biggest home advantage"
        ],
        "key_players_zh": [
            "哈里·凯恩 #9（英格兰队长 / 拜仁慕尼黑，3 球）",
            "裘德·贝林厄姆 #10（英格兰 / 皇家马德里）",
            "吉列尔莫·奥乔亚 #13（墨西哥老门将 / 39 岁）"
        ],
        "key_players_en": [
            "Harry Kane #9 (England captain / Bayern Munich, 3 goals)",
            "Jude Bellingham #10 (England / Real Madrid)",
            "Guillermo Ochoa #13 (Mexico veteran GK, 39)"
        ],
        "news_focus_zh": "墨西哥城海拔 2,240 米——英格兰本届最大体能挑战",
        "news_focus_en": "Mexico City sits at 2,240 m altitude — England's biggest physical challenge of the tournament",
        "record_potential_zh": [
            "墨西哥晋级将是 1986 后首次作为东道主打入 8 强",
            "Ochoa 若零封将是 39 岁零封世界杯的最大年龄门将纪录"
        ],
        "record_potential_en": [
            "A Mexico QF would be their first as host since 1986",
            "An Ochoa clean sheet would set the record for oldest WC shutout GK (39)"
        ],
        "manual_author": "claude",
    },
    # 760506 — Mon 7/6 2:00 PM CT — Portugal vs Spain
    "760506": {
        "headline_zh": "伊比利亚德比——葡萄牙 vs 西班牙，史上第 5 次世界杯正赛",
        "headline_en": "Iberian derby — Portugal vs Spain, the 5th WC meeting ever",
        "watch_for_zh": [
            "两队此前 4 次世界杯交锋（2018 小组赛 3-3 平局最经典），本届是淘汰赛首次",
            "Cristiano Ronaldo #7（41 岁）本届第 6 届世界杯出场——史上唯一",
            "Lamine Yamal #19（西班牙，18 岁）本届已进 4 球，是金靴候选",
            "AT&T 体育场（容纳 80,000）是 NFL 牛仔队主场——空调开足"
        ],
        "watch_for_en": [
            "4 prior WC meetings (2018 3-3 draw the classic); this is the first in the knockout",
            "Cristiano Ronaldo #7 (41) plays his 6th WC — the only player ever to do so",
            "Lamine Yamal #19 (Spain, 18) has 4 goals — Golden Boot contender",
            "AT&T Stadium (capacity 80,000) is the Cowboys' home — AC stays on full"
        ],
        "key_players_zh": [
            "克里斯蒂亚诺·罗纳尔多 #7（葡萄牙 / 41 岁，第 6 届世界杯）",
            "布鲁诺·费尔南德斯 #8（葡萄牙 / 曼联）",
            "拉明·亚马尔 #19（西班牙 / 巴塞罗那，4 球）",
            "罗德里 #16（西班牙 / 曼城，2024 金球奖）"
        ],
        "key_players_en": [
            "Cristiano Ronaldo #7 (Portugal / 41, 6th WC)",
            "Bruno Fernandes #8 (Portugal / Manchester United)",
            "Lamine Yamal #19 (Spain / Barcelona, 4 goals)",
            "Rodri #16 (Spain / Man City, 2024 Ballon d'Or)"
        ],
        "news_focus_zh": "Ronaldo 41 岁 + Yamal 18 岁——世界杯史上最大年龄差对决之一",
        "news_focus_en": "Ronaldo at 41 vs Yamal at 18 — one of the largest age gaps in WC knockout history",
        "record_potential_zh": [
            "Ronaldo 第 6 届世界杯出场是史上唯一",
            "Yamal 若再进 1 球追平西班牙队史单届世界杯进球纪录（5 球，大卫·比利亚 2010）"
        ],
        "record_potential_en": [
            "Ronaldo's 6th WC is unique in history",
            "One more Yamal goal ties Spain's single-WC record (5, Villa 2010)"
        ],
        "manual_author": "claude",
    },
    # 760507 — Mon 7/6 7:00 PM CT — United States vs Belgium
    "760507": {
        "headline_zh": "美国本土出击 vs 比利时黄金一代",
        "headline_en": "USA on home soil vs Belgium's golden generation",
        "watch_for_zh": [
            "美国本届小组赛 2 胜 1 平不败（D 组头名 7 分）——首次以头名身份打入 16 强",
            "美国 3 场 7 进球由 5 个不同球员攻入——Pulisic + Balogun 双前锋组合",
            "比利时本届 6 分（E 组头名）——黄金一代谢幕赛，Doku + Lukaku 双前锋",
            "Lumen Field（西雅图，海鹰队 NFL 主场）容纳 69,000——美国本届最大上座"
        ],
        "watch_for_en": [
            "USA went unbeaten (2W 1D, 7 pts) — first-ever top-seed R16",
            "USA's 7 group goals from 5 scorers — Pulisic + Balogun front two",
            "Belgium (Group E top, 6 pts) is the golden generation's last WC",
            "Lumen Field (Seattle, NFL Seahawks) holds 69,000 — USA's biggest crowd of the tournament"
        ],
        "key_players_zh": [
            "克里斯蒂安·普利西奇 #10（美国队长 / AC 米兰，2 球）",
            "富尔金·巴洛贡 #19（美国 / 兰斯，2 球）",
            "凯文·德布劳内 #7（比利时队长 / 曼城）",
            "罗梅卢·卢卡库 #9（比利时 / 那不勒斯，2 球）"
        ],
        "key_players_en": [
            "Christian Pulisic #10 (USA captain / AC Milan, 2 goals)",
            "Folarin Balogun #19 (USA / Reims, 2 goals)",
            "Kevin De Bruyne #7 (Belgium captain / Man City)",
            "Romelu Lukaku #9 (Belgium / Napoli, 2 goals)"
        ],
        "news_focus_zh": "美国本届首次以 D 组头名打入 16 强——东道主历史性突破",
        "news_focus_en": "USA's first-ever Group D top seed finish — a historic breakthrough for the co-hosts",
        "record_potential_zh": [
            "美国若晋级将是 2002 后首次 8 强——24 年等一回",
            "Pulisic 若再进 1 球追平美国队史单届世界杯进球纪录（5 球，1930）"
        ],
        "record_potential_en": [
            "A USA QF would be their first since 2002 — a 24-year wait",
            "One more Pulisic goal ties the USA single-WC record (5, 1930)"
        ],
        "manual_author": "claude",
    },
    # 760509 — Tue 7/7 11:00 AM CT — Argentina vs Egypt
    "760509": {
        "headline_zh": "卫冕冠军登场——阿根廷 vs 埃及",
        "headline_en": "Champions arrive — Argentina vs Egypt, Messi's farewell tour begins",
        "watch_for_zh": [
            "阿根廷本届小组赛 3 场不败（J 组头名 7 分），Messi #10 已进 2 球",
            "埃及本届小组赛 1-0 比利时 + 0-0 英格兰 + 2-1 新西兰——6 分晋级",
            "Mohamed Salah #11（利物浦）本届首秀受关注——埃及头号球星",
            "Mercedes-Benz 体育场（亚特兰大）容纳 71,000——美国本土阿根廷球迷重镇"
        ],
        "watch_for_en": [
            "Argentina went unbeaten (7 pts, Group J top); Messi #10 has 2 goals",
            "Egypt beat Belgium 1-0 and held England 0-0 — first R32 since 2014",
            "Mohamed Salah #11 (Liverpool) makes his knockout debut — Egypt's superstar",
            "Mercedes-Benz Stadium (Atlanta, NFL Falcons) holds 71,000 — Argentina's US stronghold"
        ],
        "key_players_zh": [
            "莱昂内尔·梅西 #10（阿根廷队长 / 国际迈阿密，2 球）",
            "朱利安·阿尔瓦雷斯 #9（阿根廷 / 马德里竞技，2 球）",
            "穆罕默德·萨拉赫 #11（埃及 / 利物浦）"
        ],
        "key_players_en": [
            "Lionel Messi #10 (Argentina captain / Inter Miami, 2 goals)",
            "Julián Álvarez #9 (Argentina / Atlético Madrid, 2 goals)",
            "Mohamed Salah #11 (Egypt / Liverpool)"
        ],
        "news_focus_zh": "Messi 告别赛——5 年前阿根廷夺冠，这一次卫冕之旅从 16 强起步",
        "news_focus_en": "Messi's farewell tour begins — Argentina's title defense starts in the R16",
        "record_potential_zh": [
            "Messi 第 6 届世界杯出场追平马特乌斯纪录",
            "阿根廷若卫冕将是 1962 巴西后首支蝉联世界杯的球队"
        ],
        "record_potential_en": [
            "Messi's 6th WC ties Matthäus's record",
            "An ARG repeat would be the first back-to-back title since 1962 (Brazil)"
        ],
        "manual_author": "claude",
    },
    # 760508 — Tue 7/7 3:00 PM CT — Switzerland vs Colombia
    "760508": {
        "headline_zh": "瑞士 vs 哥伦比亚——J 组的逆袭",
        "headline_en": "Switzerland vs Colombia — the Group J shocker rematch",
        "watch_for_zh": [
            "瑞士本届小组赛 2-1 塞尔维亚 + 1-0 喀麦隆——B 组头名 7 分",
            "哥伦比亚本届 1-0 巴西 + 2-1 阿尔及利亚——K 组头名 7 分，J 路由迪亚斯领衔",
            "两队曾在 2018 小组赛 0-0 平局，本届淘汰赛是首次交锋",
            "BC Place（温哥华，加拿大）容纳 54,000——加拿大本土瑞士 / 哥伦比亚球迷混居"
        ],
        "watch_for_en": [
            "Switzerland beat Serbia 2-1 and Cameroon 1-0 (Group B top, 7 pts)",
            "Colombia beat Brazil 1-0 and Algeria 2-1 (Group K top, 7 pts); Luis Díaz leads",
            "2018 group meeting was 0-0; this is the first knockout clash",
            "BC Place (Vancouver, BC) holds 54,000 — mixed Swiss/Colombian crowds in Canada"
        ],
        "key_players_zh": [
            "路易斯·迪亚斯 #7（哥伦比亚 / 利物浦，3 球）",
            "哈梅斯·罗德里格斯 #10（哥伦比亚 / 巴列卡诺）",
            "格拉尼特·扎卡 #10（瑞士队长 / 勒沃库森）",
            "布雷尔·恩博洛 #7（瑞士 / 摩纳哥，2 球）"
        ],
        "key_players_en": [
            "Luis Díaz #7 (Colombia / Liverpool, 3 goals)",
            "James Rodríguez #10 (Colombia / Rayo Vallecano)",
            "Granit Xhaka #10 (Switzerland captain / Bayer Leverkusen)",
            "Breel Embolo #7 (Switzerland / Monaco, 2 goals)"
        ],
        "news_focus_zh": "哥伦比亚本届击败巴西是本届最大冷门之一——1/8 决赛对瑞士是成色检验",
        "news_focus_en": "Colombia's 1-0 win over Brazil was the upset of the group stage — the Switzerland test confirms their form",
        "record_potential_zh": [
            "哥伦比亚若晋级将是 2014 后首次 8 强",
            "Díaz 若再进 1 球追平哥伦比亚队史单届世界杯进球纪录（6 球，Valderrama 时代个人）"
        ],
        "record_potential_en": [
            "A Colombia QF would be their first since 2014",
            "One more Díaz goal ties the Colombia single-WC record (6)"
        ],
        "manual_author": "claude",
    },

    # ───── Quarterfinals ─────
    # 760510 — Thu 7/9 3:00 PM CT — France vs Morocco (upper QF slot 1)
    "760510": {
        "headline_zh": "法国 vs 摩洛哥——2022 半决赛重演",
        "headline_en": "France vs Morocco — the 2022 semifinal rematch",
        "watch_for_zh": [
            "两队 2022 卡塔尔世界杯半决赛 2-0 法国胜，本届 1/4 决赛再次相遇",
            "Mbappé #10 本届 5 球领跑金靴——已 1 球领先第 2 名",
            "摩洛哥本届 5 场不败 + 3 胜欧洲/南美强队——本届最大黑马",
            "法国本届 4 场比赛进 9 球，进攻端 Mbappé-Griezmann-Dembélé 三叉戟成型"
        ],
        "watch_for_en": [
            "2022 WC semifinal: France 2-0 Morocco. Same matchup in the QF 4 years later",
            "Mbappé #10 leads the Golden Boot at 5 — 1 ahead of #2",
            "Morocco went 5 unbeaten (W4 D1), beating ARG, BRA, FRA-draw — biggest WC story",
            "France scored 9 in 4 matches; the Mbappé-Griezmann-Dembélé front three is firing"
        ],
        "key_players_zh": [
            "基利安·姆巴佩 #10（法国 / 皇家马德里，5 球金靴榜首）",
            "安托万·格里兹曼 #7（法国 / 马德里竞技）",
            "阿什拉夫·哈基米 #2（摩洛哥 / 巴黎圣日耳曼，3 球）",
            "索菲安·阿姆拉巴特 #4（摩洛哥 / 佛罗伦萨）"
        ],
        "key_players_en": [
            "Kylian Mbappé #10 (France / Real Madrid, 5 goals, Golden Boot leader)",
            "Antoine Griezmann #7 (France / Atlético Madrid)",
            "Achraf Hakimi #2 (Morocco / PSG, 3 goals)",
            "Sofyan Amrabat #4 (Morocco / Fiorentina)"
        ],
        "news_focus_zh": "Mbappé vs Hakimi——巴黎圣日耳曼队友的国家队对决",
        "news_focus_en": "Mbappé vs Hakimi — PSG teammates facing off at the international level",
        "record_potential_zh": [
            "Mbappé 若再进 1 球追平 1986 莱因克尔 6 球当届最佳",
            "摩洛哥若晋级将是 1986 后首次非洲球队打入 4 强"
        ],
        "record_potential_en": [
            "One more Mbappé goal ties 1986 Lineker's 6-goal tournament-best",
            "A Morocco SF would be the first African SF since 2014 (Algeria)"
        ],
        "manual_author": "claude",
    },
    # 760511 — Fri 7/10 2:00 PM CT — lower-half QF (R16-5 W vs R16-6 W)
    "760511": {
        "headline_zh": "下半区 QF——伊比利亚双雄 + 美国 + 比利时之胜者",
        "headline_en": "Lower-half QF — Iberian derby winner vs USA/Belgium winner",
        "watch_for_zh": [
            "本场胜者是 Portugal/Spain 胜者 vs USA/Belgium 胜者",
            "如果 Portugal/Span 胜者晋级，将代表西班牙或葡萄牙重返 SF——两队 2010 后都未进 SF",
            "如果 USA/Belgium 胜者晋级，将是美国历史性突破或比利时黄金一代谢幕演出",
            "SoFi 体育场（洛杉矶英格尔伍德）容纳 70,000——本届最大 QF 场地之一"
        ],
        "watch_for_en": [
            "Winner of Portugal/Spain vs winner of USA/Belgium",
            "An Iberian winner would be Spain/Portugal's first SF since 2010/2006",
            "A USA winner would be a historic breakthrough; a Belgium winner would be the golden generation's final bow",
            "SoFi Stadium (Inglewood, LA) holds 70,000 — one of the largest QF venues"
        ],
        "key_players_zh": [
            "等待 R16 胜者后填入具体球员"
        ],
        "key_players_en": [
            "Pending R16 results"
        ],
        "news_focus_zh": "本场胜者直接晋级 SF——下半区决赛门票",
        "news_focus_en": "Winner advances to SF — the lower-half final ticket",
        "record_potential_zh": [
            "葡萄牙若晋级将是 2006 后首次 SF",
            "美国若晋级将是队史首次 SF——历史性突破",
            "西班牙若晋级将是 2012 后首次 SF",
            "比利时若晋级将是 1986 后首次 SF"
        ],
        "record_potential_en": [
            "A POR SF would be their first since 2006",
            "A USA SF would be the country's first ever — historic",
            "An ESP SF would be their first since 2012",
            "A BEL SF would be their first since 1986"
        ],
        "manual_author": "claude",
    },
    # 760512 — Sat 7/11 4:00 PM CT — upper-half QF slot 2 (R16-3 W vs R16-4 W)
    "760512": {
        "headline_zh": "上半区第二场 QF——巴西/挪威 vs 墨西哥/英格兰之胜者",
        "headline_en": "Upper-half second QF — Brazil/Norway vs Mexico/England winner",
        "watch_for_zh": [
            "本场胜者是 Brazil/Norway 胜者 vs Mexico/England 胜者",
            "如果是巴西晋级，将是巴西连续 14 届世界杯打入 8 强",
            "如果是墨西哥晋级，将是 1986 后首次作为东道主打入 8 强",
            "如果是英格兰晋级，将是 2018 后首次打入 8 强（2018 是殿军）",
            "Hard Rock 体育场（迈阿密）容纳 65,000——拉美球迷重镇"
        ],
        "watch_for_en": [
            "Winner of Brazil/Norway vs winner of Mexico/England",
            "A BRA QF appearance extends their streak to 14 straight WCs",
            "A MEX QF would be their first as host since 1986",
            "An ENG QF would be their first since 2018 (4th place)",
            "Hard Rock Stadium (Miami) holds 65,000 — Latin American stronghold"
        ],
        "key_players_zh": [
            "等待 R16 胜者后填入具体球员"
        ],
        "key_players_en": [
            "Pending R16 results"
        ],
        "news_focus_zh": "本场胜者晋级上半区 SF——若对法国，将是 2018 决赛重演（巴西/克罗地亚实际是 2002）",
        "news_focus_en": "Winner advances to upper-half SF — could meet France (2022 final rematch territory)",
        "record_potential_zh": [
            "巴西连续 14 届世界杯打入 8 强（自 1938 起未缺席）",
            "墨西哥若晋级将是 1986 后首次作为东道主打入 8 强",
            "挪威若晋级将是 1998 后首次 8 强"
        ],
        "record_potential_en": [
            "Brazil would extend their streak to 14 straight WCs",
            "A MEX QF would be their first as host since 1986",
            "A NOR QF would be their first since 1998"
        ],
        "manual_author": "claude",
    },
    # 760513 — Sat 7/11 9:00 PM CT — lower-half QF slot 2 (R16-7 W vs R16-8 W)
    "760513": {
        "headline_zh": "下半区 QF——阿根廷/埃及 vs 瑞士/哥伦比亚之胜者",
        "headline_en": "Lower-half QF — Argentina/Egypt vs Switzerland/Colombia winner",
        "watch_for_zh": [
            "本场胜者是 Argentina/Egypt 胜者 vs Switzerland/Colombia 胜者",
            "如果是阿根廷晋级，将是卫冕冠军首次打入 8 强（2022 决赛胜者）",
            "如果是瑞士晋级，将是 1954 后首次打入 8 强（瑞士曾主办 1954 世界杯）",
            "GEHA Field at Arrowhead 体育场（堪萨斯城）容纳 76,000——NFL 酋长队主场"
        ],
        "watch_for_en": [
            "Winner of Argentina/Egypt vs winner of Switzerland/Colombia",
            "An ARG QF would be the champions' first knockout test",
            "A SUI QF would be their first since 1954 — when they hosted the WC",
            "GEHA Field at Arrowhead Stadium (Kansas City) holds 76,000 — NFL Chiefs' home"
        ],
        "key_players_zh": [
            "等待 R16 胜者后填入具体球员"
        ],
        "key_players_en": [
            "Pending R16 results"
        ],
        "news_focus_zh": "卫冕冠军 vs 冷门制造机——下半区剧情核心",
        "news_focus_en": "Champions vs giant-killers — the lower-half story arc",
        "record_potential_zh": [
            "阿根廷若晋级将追平意大利 / 德国连续 3 届打入 8 强的纪录",
            "瑞士若晋级将是 1954 后首次 8 强——72 年等一回",
            "埃及若晋级将是 1934 后首次 8 强——92 年等一回"
        ],
        "record_potential_en": [
            "An ARG QF would extend their streak to 3 straight",
            "A SUI QF would be their first since 1954 — a 72-year wait",
            "An EGY QF would be their first since 1934 — a 92-year wait"
        ],
        "manual_author": "claude",
    },

    # ───── Semifinals ─────
    # 760514 — Tue 7/14 2:00 PM CT — QF-1 W vs QF-2 W (upper SF)
    "760514": {
        "headline_zh": "上半区 SF——法国/Morocco 胜者 vs 巴西/Mexico/England/Norway 胜者",
        "headline_en": "Upper-half SF — France/Morocco winner vs Brazil/Mexico/England/Norway winner",
        "watch_for_zh": [
            "上半区 SF 由 QF-1（France/Morocco）胜者 vs QF-2（Brazil/Mexico/England/Norway）胜者组成",
            "AT&T 体育场（阿灵顿，德州）容纳 80,000——本届最大 SF 场地",
            "胜者晋级 7/19 MetLife 决赛"
        ],
        "watch_for_en": [
            "Upper-half SF: QF-1 winner (France or Morocco) vs QF-2 winner (BRA/MEX/ENG/NOR)",
            "AT&T Stadium (Arlington, TX) holds 80,000 — the largest SF venue",
            "Winner advances to the 7/19 Final at MetLife Stadium"
        ],
        "key_players_zh": [
            "等待 QF 胜者后填入"
        ],
        "key_players_en": [
            "Pending QF results"
        ],
        "news_focus_zh": "上半区决赛门票——胜者进 MetLife 决赛",
        "news_focus_en": "Upper-half final ticket — winner goes to MetLife",
        "record_potential_zh": [
            "摩洛哥若晋级将是首支非洲球队打入世界杯决赛",
            "墨西哥若晋级将是 1986 后首次世界杯决赛"
        ],
        "record_potential_en": [
            "A Morocco final would be the first African team in a WC final",
            "A Mexico final would be their first since 1986 (as host)"
        ],
        "manual_author": "claude",
    },
    # 760515 — Wed 7/15 2:00 PM CT — QF-3 W vs QF-4 W (lower SF)
    "760515": {
        "headline_zh": "下半区 SF——伊比利亚/USA/Belgium 胜者 vs 阿根廷/Egypt/Switzerland/Colombia 胜者",
        "headline_en": "Lower-half SF — Iberian/USA/Belgium winner vs Argentina/Egypt/Switzerland/Colombia winner",
        "watch_for_zh": [
            "下半区 SF 由 QF-3（Iberian/USA/Belgium）胜者 vs QF-4（Argentina/Egypt/Switzerland/Colombia）胜者组成",
            "Mercedes-Benz 体育场（亚特兰大）容纳 71,000——美国南部 SF 场地",
            "胜者晋级 7/19 MetLife 决赛"
        ],
        "watch_for_en": [
            "Lower-half SF: QF-3 winner (Iberian/USA/Belgium) vs QF-4 winner (ARG/EGY/SUI/COL)",
            "Mercedes-Benz Stadium (Atlanta) holds 71,000 — the southern SF venue",
            "Winner advances to the 7/19 Final at MetLife Stadium"
        ],
        "key_players_zh": [
            "等待 QF 胜者后填入"
        ],
        "key_players_en": [
            "Pending QF results"
        ],
        "news_focus_zh": "下半区决赛门票——胜者进 MetLife 决赛",
        "news_focus_en": "Lower-half final ticket — winner goes to MetLife",
        "record_potential_zh": [
            "葡萄牙若晋级将是 2006 后首次 SF",
            "美国若晋级将是队史首次 SF——历史性突破"
        ],
        "record_potential_en": [
            "A POR SF would be their first since 2006",
            "A USA SF would be the country's first ever — historic"
        ],
        "manual_author": "claude",
    },

    # ───── 3rd-place + Final ─────
    # 760516 — Sat 7/18 4:00 PM CT — 3rd-place match (SF losers)
    "760516": {
        "headline_zh": "三四名决赛——SF 败者的最后一场",
        "headline_en": "3rd-place match — the SF losers' last dance",
        "watch_for_zh": [
            "SF 败者争夺本届世界杯第三名",
            "Hard Rock 体育场（迈阿密）容纳 65,000——NFL 海豚队主场",
            "3rd-place 决赛传统上是 high-scoring（双方放松防守），本届预计开放进攻"
        ],
        "watch_for_en": [
            "SF losers compete for 3rd place",
            "Hard Rock Stadium (Miami, NFL Dolphins) holds 65,000",
            "3rd-place matches are traditionally high-scoring (relaxed defenses)"
        ],
        "key_players_zh": [
            "等待 SF 败者后填入"
        ],
        "key_players_en": [
            "Pending SF results"
        ],
        "news_focus_zh": "世界杯 3rd-place 决赛传统上是 high-scoring——双方都没有晋级压力",
        "news_focus_en": "WC 3rd-place matches are traditionally high-scoring — no advancement pressure",
        "record_potential_zh": [
            "3rd-place 决赛史上最高比分 1958 法国 6-3 德国"
        ],
        "record_potential_en": [
            "All-time 3rd-place scoring record: 1958 France 6-3 Germany"
        ],
        "manual_author": "claude",
    },
    # 760517 — Sun 7/19 2:00 PM CT — Final
    "760517": {
        "headline_zh": "决赛——4 年一届，48 队 104 场比赛的最终章",
        "headline_en": "The Final — the closing chapter of 104 matches across 48 teams",
        "watch_for_zh": [
            "MetLife 体育场（新泽西）容纳 82,500——NFL 巨人队和喷气机队主场",
            "MetLife 是 2014 超级碗 XLVIII 场地——巴西 7-1 德国的惨案就发生在这里",
            "48 队赛制首届世界杯决赛——史上参赛队伍最多的决赛",
            "胜者成为世界杯冠军，举起 FIFA 世界杯奖杯"
        ],
        "watch_for_en": [
            "MetLife Stadium (East Rutherford, NJ) holds 82,500 — NFL Giants & Jets home",
            "MetLife hosted Super Bowl XLVIII in 2014 — the famous 7-1 Brazil-Germany semifinal",
            "First 48-team WC final in history — the largest-ever final",
            "Winner lifts the FIFA World Cup trophy as world champions"
        ],
        "key_players_zh": [
            "等待 SF 胜者后填入"
        ],
        "key_players_en": [
            "Pending SF results"
        ],
        "news_focus_zh": "世界杯冠军——足球世界的最高荣誉",
        "news_focus_en": "World Cup champion — the highest honor in football",
        "record_potential_zh": [
            "Mbappé 若决赛进球将成为世界杯决赛最年轻帽子戏法球员（若再进 2 球）",
            "阿根廷若卫冕将是 1962 巴西后首支蝉联世界杯的球队",
            "法国若夺冠将是 2018-2022-2026 三届中两次夺冠的球队（与 1998-2002 巴西 / 1958-1962 巴西同档）"
        ],
        "record_potential_en": [
            "Mbappé with 2+ final goals would be the youngest WC final hat-trick scorer",
            "An ARG repeat would be the first back-to-back title since 1962 (Brazil)",
            "A FRA title would be 2-of-3 (matching Brazil 1958-1962 and 1998-2002)"
        ],
        "manual_author": "claude",
    },
}


def main() -> int:
    with PATH.open(encoding="utf-8") as f:
        doc = json.load(f)

    rounds = doc.get("rounds") or []
    enriched = 0
    for r in rounds:
        rid = r["round_id"]
        if rid in ROUND_INTROS:
            for k, v in ROUND_INTROS[rid].items():
                r[k] = v
        for m in r.get("matches", []):
            mid = m["match_id"]
            if mid in ANALYSIS:
                for k, v in ANALYSIS[mid].items():
                    m[k] = v
                enriched += 1

    # ────────────────────────────────────────────────────────────
    # Add a 3rd-place match round if not already present.
    # The 3rd-place match uses stage_slug "3rd-place-match" which is
    # not generated by build_weekly_picks.py --stage=final. Inject it
    # into a separate round called "Final Weekend" so it shows up in
    # the weekly picks UI.
    # ────────────────────────────────────────────────────────────
    existing_ids = {r["round_id"] for r in rounds}
    if "final-weekend-2026-07-18-2026-07-19" not in existing_ids:
        # Pull the 3rd-place match from matches.json
        matches_doc_path = ROOT / "data" / "matches.json"
        with matches_doc_path.open(encoding="utf-8") as f:
            matches_doc = json.load(f)
        third = None
        for day in matches_doc.get("days", []):
            for m in day.get("matches", []):
                if m.get("stage_slug") == "3rd-place-match":
                    third = m
                    break
            if third:
                break
        if third:
            # Auto-populated skeleton (mirrors build_weekly_picks.py output)
            tpl = {
                "round_id": "final-weekend-2026-07-18-2026-07-19",
                "stage_slug": "3rd-place-match",
                "round_label": {"zh": "决赛周末", "en": "Final Weekend"},
                "round_date_range": ["2026-07-18", "2026-07-19"],
                "match_count": 1,
                "manual_count": 0,
                "last_manual_update": None,
                "round_intro_zh": None,
                "round_intro_en": None,
                "manual_note_zh": None,
                "manual_note_en": None,
                "generated_at": NOW,
                "matches": [{
                    "match_id": third["id"],
                    "kickoff_utc": third["kickoff_utc"],
                    "kickoff_local": third.get("kickoff_local", ""),
                    "kickoff_local_date": third.get("kickoff_local_date", ""),
                    "kickoff_time": third.get("kickoff_time", ""),
                    "kickoff_weekday": third.get("kickoff_weekday", ""),
                    "stage": third.get("stage", "3rd Place Match"),
                    "stage_slug": "3rd-place-match",
                    "venue": (third.get("venue") or {}).get("name", "") if isinstance(third.get("venue"), dict) else third.get("venue", ""),
                    "venue_city": (third.get("venue") or {}).get("city", "") if isinstance(third.get("venue"), dict) else "",
                    "espn_url": third.get("espn_url", ""),
                    "fox_url": third.get("fox_url", ""),
                    "home": third.get("home", {}),
                    "away": third.get("away", {}),
                    "stakes_kind": "knockout",
                    "stakes_score_auto": 3,
                    "stakes_verdict_auto": "lively",
                    "stakes_narrative_zh": "三四名决赛，淘汰赛败者的最后一场。",
                    "stakes_narrative_en": "Third-place match — the loser's last dance.",
                    "verdict": "lively",
                    "score": 3,
                    "headline_zh": None,
                    "headline_en": None,
                    "watch_for_zh": [],
                    "watch_for_en": [],
                    "key_players_zh": [],
                    "key_players_en": [],
                    "news_focus_zh": None,
                    "news_focus_en": None,
                    "record_potential_zh": [],
                    "record_potential_en": [],
                    "why_skip_zh": None,
                    "why_skip_en": None,
                    "verdict_override": None,
                    "score_override": None,
                }],
            }
            rounds.append(tpl)

    # Re-apply enrichment to newly-added round (3rd-place match)
    for r in rounds:
        for m in r.get("matches", []):
            mid = m["match_id"]
            if mid in ANALYSIS:
                for k, v in ANALYSIS[mid].items():
                    m[k] = v
                enriched += 1

    # Update manual_count + last_manual_update per round
    for r in rounds:
        manual_count = sum(
            1 for m in r.get("matches", [])
            if m.get("headline_zh") or m.get("watch_for_zh") or m.get("news_focus_zh")
        )
        r["manual_count"] = manual_count
        if manual_count > 0:
            r["last_manual_update"] = NOW

    doc["rounds"] = rounds
    doc["generated_at"] = NOW

    with PATH.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote {PATH} (enriched {enriched} matches across {len(rounds)} rounds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())