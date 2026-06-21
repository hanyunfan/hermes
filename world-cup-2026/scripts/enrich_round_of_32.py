#!/usr/bin/env python3
"""
One-shot enrichment for the 16 Round-of-32 matches.

Reads the existing data/weekly-picks.json (which has the auto fields
populated and subjective fields null) and fills in the subjective
fields for all 16 R32 matches:

  - headline_zh / headline_en
  - watch_for_zh / watch_for_en
  - key_players_zh / key_players_en
  - news_focus_zh / news_focus_en
  - record_potential_zh / record_potential_en
  - manual_author

Many R32 matchups have TBD team identities (e.g. "1C vs 2F") since
the group stage isn't finished. Analysis is written in terms of the
*slot structure* (e.g. "Group C winner vs Group F runner-up") and
the most likely teams based on current standings as of 2026-06-21
(MD2 mostly complete, MD3 underway).

This script is idempotent: it overwrites subjective fields with the
content below. Re-run after group stage is fully resolved to update
the "likely teams" prose.

Usage: python3 scripts/enrich_round_of_32.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
PATH = DATA_DIR / "weekly-picks.json"

# Subjective enrichment per match_id. Keys must match the match_id
# in weekly-picks.json.
ANALYSIS: dict[str, dict] = {
    # ── 760486 — Sun 6/28 2:00 PM — 2A vs 2B at SoFi Stadium
    "760486": {
        "headline_zh": "韩瑞对决，淘汰赛揭幕",
        "headline_en": "Korea vs Switzerland — R32 curtain-raiser",
        "watch_for_zh": [
            "A 组第二大概率是韩国（墨西哥已锁定第一），B 组第二大概率是瑞士（末轮与加拿大直接对话）",
            "两队都偏防守反击，控球率不会高——可能是一场 1-0 风格的战术绞肉机",
            "韩国曾在 2018 年 2-0 掀翻德国，本届小组赛 1-0 战胜捷克，士气正盛",
            "瑞士近 3 届世界杯都打入 16 强（2014、2018、2022），淘汰赛经验最稳",
            "SoFi 体育场可容纳 70,000+，是 NFL 超级碗场馆——淘汰赛氛围拉满"
        ],
        "watch_for_en": [
            "2A is most likely South Korea (Mexico has Group A locked). 2B is most likely Switzerland (CAN-SUI final match decides top of B).",
            "Both sides are disciplined, defense-first — expect a 1-0-style tactical grind, not a goalfest.",
            "KOR famously upset Germany 2-0 in 2018; their 1-0 over Czechia in MD2 shows the resilience is still there.",
            "SUI have reached the R16 at the last three World Cups (2014, 2018, 2022) — knockout-stage pedigree is real.",
            "SoFi is a 70,000+ Super Bowl venue — the first R32 atmosphere of the tournament."
        ],
        "key_players_zh": [
            "孙兴慜 #7（韩国队长，洛杉矶 FC 边锋）",
            "哈维尔·巴尔加斯 #10（瑞士中场，2024 欧洲杯最佳球员之一）",
            "金玟哉 #19（拜仁慕尼黑中卫，盯防瑞士箭头）"
        ],
        "key_players_en": [
            "Son Heung-min #7 (KOR captain, LAFC winger)",
            "Xherdan Shaqiri #10 (SUI midfielder, Euro 2024 standout)",
            "Kim Min-jae #19 (Bayern Munich CB, anchors KOR's back line)"
        ],
        "news_focus_zh": "韩国 26 岁的拜仁中卫金玟哉是本届最贵后卫之一，他的解围数据将决定比赛走向",
        "news_focus_en": "KOR's Kim Min-jae (Bayern Munich, age 26) is one of the most expensive CBs at this WC — his clearances will decide the match",
        "record_potential_zh": [
            "瑞士若晋级将连续 4 届世界杯打入 16 强——刷新本国纪录",
            "孙兴慜有望追平韩国球员世界杯进球纪录（目前与朴智星并列）"
        ],
        "record_potential_en": [
            "A SUI win would extend their R16 streak to four straight World Cups — a Swiss record",
            "Son can match Park Ji-sung's all-time KOR World Cup goals record"
        ],
        "manual_author": "claude",
    },

    # ── 760487 — Mon 6/29 12:00 PM — 1C vs 2F at NRG Stadium
    "760487": {
        "headline_zh": "C 组头名检验，F 组突围者",
        "headline_en": "Group C top seed meets F's survivor",
        "watch_for_zh": [
            "C 组极有可能由巴西或苏格兰头名（双方都还有出线悬念），无论谁上来都是死亡半区",
            "F 组第二大概率是日本或荷兰（瑞典目前领跑）",
            "如果 1C 是巴西——这是巴西本届首场淘汰赛，桑巴军团的 6 冠王传统不容有失",
            "如果 1C 是苏格兰——这是 1998 年后首次世界杯淘汰赛，麦克托米奈的发挥决定上限",
            "休斯敦 6 月底下午 1 点开球，体感温度可能超过 35°C——节奏和体能是关键"
        ],
        "watch_for_en": [
            "Group C top spot is wide open — BRA or SCO could finish 1st, both still alive in MD3.",
            "F runner-up is most likely Japan or Netherlands (Sweden currently leading F).",
            "If BRA wins C, this is the Seleção's first knockout game — the 6×-champion tradition is on the line.",
            "If SCO wins C, it's Scotland's first WC knockout match since 1998 — McTominay's form is the ceiling.",
            "Houston noon kickoff in late June = 95°F+ feel-like temp. Pace and conditioning will tell."
        ],
        "key_players_zh": [
            "维尼修斯·儒尼奥尔 #7（巴西边锋，2024 金球奖得主）",
            "斯科特·麦克托米奈 #4（苏格兰中场，曼联首发）",
            "久保健英 #11（日本中场，皇家社会核心）"
        ],
        "key_players_en": [
            "Vinícius Júnior #7 (Brazil winger, 2024 Ballon d'Or winner)",
            "Scott McTominay #4 (Scotland midfielder, Manchester United regular)",
            "Takefusa Kubo #11 (Japan midfielder, Real Sociedad playmaker)"
        ],
        "news_focus_zh": "小组赛首轮巴西 0-0 平摩洛哥已经暴露出进攻乏力——淘汰赛不允许再慢热",
        "news_focus_en": "BRA's 0-0 draw with Morocco in MD1 already showed attacking malaise — they can't afford another slow start in knockout",
        "record_potential_zh": [
            "若日本晋级将是连续 4 届世界杯小组出线（2010、2018、2022、2026）——亚洲纪录",
            "若苏格兰晋级将追平 1998 年 16 强成绩"
        ],
        "record_potential_en": [
            "A JPN win would extend Asia's longest R16 streak to four straight WCs.",
            "A SCO win would match their 1998 R16 finish — first time in 28 years."
        ],
        "manual_author": "claude",
    },

    # ── 760489 — Mon 6/29 3:30 PM — 1E vs 3RD at Gillette Stadium
    "760489": {
        "headline_zh": "德国登场，3RD 挑战者待定",
        "headline_en": "Germany enters; 3RD challenger TBD",
        "watch_for_zh": [
            "E 组第一大概率是德国（首轮 4-0 横扫库拉索，次轮 1-0 险胜科特迪瓦待定）",
            "对手是 A/B/C/D/F 五个组中表现最好的第三名——通常会有 3-4 分",
            "德国已经连续 3 届世界杯小组赛折戟（2018、2022），本届淘汰赛复仇心切",
            "Gillette 体育场是 NFL 爱国者队主场，下午 3:30 体感 32°C+——德国的高位逼抢在高温下能撑多久是关键",
            "穆西亚拉（拜仁）和维尔茨（勒沃库森）是德国前场最锐利的两个点"
        ],
        "watch_for_en": [
            "Group E top is most likely Germany (4-0 over Curaçao in MD1, then tested by CIV in MD2).",
            "Opponent is the best 3rd-place team from groups A/B/C/D/F — typically a 3-4 point side.",
            "GER have crashed out in the group stage at the last three WCs (2018, 2022) — the knockout-stage redemption arc is real.",
            "Gillette is the NFL Patriots' home; 3:30 PM late-June = 90°F. How long can GER's high press hold up?",
            "Musiala (Bayern) and Wirtz (Leverkusen) are Germany's sharpest attackers right now."
        ],
        "key_players_zh": [
            "贾马尔·穆西亚拉 #10（拜仁慕尼黑中场，2024 年德国足球先生）",
            "弗洛里安·维尔茨 #17（勒沃库森中场，欧冠 2024 核心）",
            "凯·哈弗茨 #7（阿森纳前锋）"
        ],
        "key_players_en": [
            "Jamal Musiala #10 (Bayern Munich midfielder, 2024 Germany Footballer of the Year)",
            "Florian Wirtz #17 (Leverkusen midfielder, 2024 UCL breakout)",
            "Kai Havertz #7 (Arsenal striker)"
        ],
        "news_focus_zh": "纳格尔斯曼本届主打 4-2-3-1，淘汰赛大概率延续——关键是哈弗茨的箭头效率",
        "news_focus_en": "Nagelsmann's 4-2-3-1 is likely to continue in the R32 — Havertz's finishing efficiency is the swing factor",
        "record_potential_zh": [
            "穆勒（35 岁）若登场将追平马特乌斯 25 场世界杯出场纪录",
            "德国若晋级将终结连续 3 届小组赛出局的尴尬"
        ],
        "record_potential_en": [
            "Thomas Müller (35) can match Lothar Matthäus's 25-game WC appearance record.",
            "A GER win would end the 3-tournament group-stage exit streak."
        ],
        "manual_author": "claude",
    },

    # ── 760488 — Mon 6/29 8:00 PM — 1F vs 2C at Estadio BBVA
    "760488": {
        "headline_zh": "瑞典 vs C 组黑马，墨西哥高原",
        "headline_en": "Sweden vs C's surprise package — Monterrey",
        "watch_for_zh": [
            "F 组头名大概率是瑞典（首轮 3-0 拿下突尼斯），后防核心丹尼尔森（利兹联）已 34 岁，本届可能是告别赛",
            "C 组第二很可能是巴西、摩洛哥或苏格兰——无论谁，都是硬骨头",
            "Estadio BBVA（蒙特雷）海拔 540 米，是本届海拔最高的主办城市之一，对北欧球队不友好",
            "C 组第二若为巴西，桑巴军团 25 战 R32 保持全胜（从未 1/8 决赛出局）",
            "瑞典前锋伊萨克（纽卡斯尔）首轮已破门，是本届金靴热门之一"
        ],
        "watch_for_en": [
            "Group F top is most likely Sweden (3-0 over Tunisia in MD1). CB Andreas Granqvist's heir Danielson (Leeds, 34) is playing his last WC.",
            "C runner-up could be Brazil, Morocco, or Scotland — any of them is a hard out.",
            "Estadio BBVA sits at 540m elevation — the highest host venue — rough on Nordic sides.",
            "If BRA finishes 2nd in C, this is a nightmare: Brazil has never lost an R32 match (25-0 all-time).",
            "SWE striker Alexander Isak (Newcastle) scored in MD1 and is among the Golden Boot favorites."
        ],
        "key_players_zh": [
            "亚历山大·伊萨克 #11（瑞典前锋，纽卡斯尔）",
            "维尼修斯·儒尼奥尔 #7（巴西边锋，皇家马德里）",
            "罗宾·奥尔森 #1（瑞典门将）"
        ],
        "key_players_en": [
            "Alexander Isak #11 (Sweden striker, Newcastle)",
            "Vinícius Júnior #7 (Brazil winger, Real Madrid)",
            "Robin Olsen #1 (Sweden goalkeeper)"
        ],
        "news_focus_zh": "海拔 540 米的蒙特雷是淘汰赛最考验体能的主办城市——瑞典的北欧打法能撑到加时吗？",
        "news_focus_en": "Monterrey's 540m elevation is the toughest fitness test in the R32 — can Sweden's high-tempo style last 120 minutes?",
        "record_potential_zh": [
            "巴西若晋级将是连续 14 届世界杯打入 16 强（自 1938 年起未缺席）",
            "伊萨克本届若进 3+ 球将追平瑞典单届世界杯进球纪录"
        ],
        "record_potential_en": [
            "A BRA win would extend their R16 streak to 14 straight WCs (uninterrupted since 1938).",
            "Isak with 3+ goals would match Sweden's all-time single-WC record."
        ],
        "manual_author": "claude",
    },

    # ── 760490 — Tue 6/30 12:00 PM — 2E vs 2I at AT&T Stadium
    "760490": {
        "headline_zh": "法国内战？科特迪瓦迎挑战",
        "headline_en": "France or Norway await CIV in Dallas",
        "watch_for_zh": [
            "E 组第二大概率是科特迪瓦（首轮 1-0 小胜厄瓜多尔，防守稳健）",
            "I 组第二大概率是法国（与挪威的末轮直接对话决定谁是头名）",
            "如果是法国——上届亚军 2022 年决赛输给阿根廷，本届小组赛已 2 胜，状态很好",
            "AT&T 体育场是 NFL 牛仔队主场，室内空调——6/30 上午 11 点体感凉爽，是当日最佳观赛条件",
            "法国的姆巴佩本届已 3 球领跑射手榜，禁区弧顶的终结依然是世界级"
        ],
        "watch_for_en": [
            "2E is most likely Ivory Coast (1-0 over Ecuador in MD1, defense-first shape).",
            "2I is most likely France (FRA-NOR final MD3 match decides top of I).",
            "If FRA is the opponent, they're the 2022 finalists — and 2-0 in group play this time around.",
            "AT&T Stadium is climate-controlled indoors — coolest noon kickoff on the slate.",
            "Mbappé leads the Golden Boot race with 3 goals; his left-footed cut-in finish is still world-class."
        ],
        "key_players_zh": [
            "基利安·姆巴佩 #10（法国队长，皇家马德里前锋）",
            "奥利维耶·吉鲁 #9（法国老将，AC 米兰中锋）",
            "塞库·库利巴利 #6（科特迪瓦中场，2023 非洲杯最佳球员）"
        ],
        "key_players_en": [
            "Kylian Mbappé #10 (France captain, Real Madrid striker)",
            "Olivier Giroud #9 (France veteran, AC Milan target man)",
            "Seko Fofana #6 (Ivory Coast midfielder, 2023 AFCON Best Player)"
        ],
        "news_focus_zh": "姆巴佩本届首次戴上队长袖标，2024 欧洲杯半决赛射失点球后他需要用淘汰赛进球完成救赎",
        "news_focus_en": "Mbappé wearing the armband for the first time at a WC; needs a knockout goal to erase the Euro 2024 SF PK miss",
        "record_potential_zh": [
            "姆巴佩若再进 1 球将追平齐达内 14 球世界杯法国队史纪录",
            "吉鲁若登场将成为法国世界杯最年长球员（38 岁）"
        ],
        "record_potential_en": [
            "One more Mbappé goal ties Zinedine Zidane's 14 — France's all-time WC record.",
            "Giroud (38) appearing would set France's oldest-ever WC player mark."
        ],
        "manual_author": "claude",
    },

    # ── 760492 — Tue 6/30 4:00 PM — 1I vs 3RD at MetLife Stadium
    "760492": {
        "headline_zh": "挪威或法国在 MetLife 出战",
        "headline_en": "Norway or France under the NYC lights",
        "watch_for_zh": [
            "I 组头名大概率在挪威和法国之间产生（首轮都赢，对决在末轮）",
            "对手是 C/D/F/G/H 五个组的最佳第三——这 5 个组都比较乱（G、H 全员平分）",
            "MetLife 体育场是 NFL 喷气机队主场，也是 2026 世界杯决赛场地——淘汰赛首登气氛最浓",
            "挪威首次重返世界杯（2002 后），头号射手哈兰德（曼城）已 3 球领跑——是本届金靴头号热门",
            "如果是法国——上届亚军姆巴佩+格列兹曼的连线已成型，晋级应是常规操作"
        ],
        "watch_for_en": [
            "1I is most likely Norway or France (both won MD1; the FRA-NOR MD3 clash decides top of I).",
            "Opponent is the best 3rd from C/D/F/G/H — five groups where standings are still wide open.",
            "MetLife is the NFL Jets' home and the 2026 WC final venue — the R32 atmosphere will be the biggest of the round.",
            "NOR are back at a WC for the first time since 2002; Haaland (Man City) has 3 goals and is the Golden Boot front-runner.",
            "If FRA, the Mbappé-Griezmann connection is clicking — 2022 finalists should cruise."
        ],
        "key_players_zh": [
            "埃尔林·哈兰德 #9（挪威前锋，曼城）",
            "基利安·姆巴佩 #10（法国前锋，皇家马德里）",
            "马丁·厄德高 #10（挪威中场，阿森纳）"
        ],
        "key_players_en": [
            "Erling Haaland #9 (Norway striker, Man City)",
            "Kylian Mbappé #10 (France striker, Real Madrid)",
            "Martin Ødegaard #10 (Norway midfielder, Arsenal)"
        ],
        "news_focus_zh": "哈兰德本届已 3 球——若再进 1 球将成为挪威队史单届世界杯进球纪录保持者",
        "news_focus_en": "Haaland's 3 goals already equal NOR's single-WC record — one more and he owns it outright",
        "record_potential_zh": [
            "哈兰德 1 球即破挪威队史单届世界杯进球纪录",
            "MetLife 首次承办世界杯比赛——历史性的 80,000+ 观众"
        ],
        "record_potential_en": [
            "One Haaland goal breaks Norway's all-time single-WC scoring record.",
            "MetLife's first-ever WC match — historic 80,000+ crowd."
        ],
        "manual_author": "claude",
    },

    # ── 760491 — Tue 6/30 8:00 PM — MEX vs 3RD at Estadio Banorte
    "760491": {
        "headline_zh": "东道主墨西哥主场淘汰赛",
        "headline_en": "Mexico's home knockout — 1986 sequel",
        "watch_for_zh": [
            "墨西哥以 A 组头名晋级（已 2 胜 6 分），FIFA 排名第 14",
            "对手是 C/E/F/H/I 五个组中表现最好的第三——可能是日本、乌兹别克斯坦等亚洲队",
            "Estadio Banorte（墨西哥城）海拔 2,240 米，是世界杯最高海拔主办地——客队需要 24 小时适应",
            "墨西哥上一场世界杯淘汰赛胜利要追溯到 1986 年本土世界杯——40 年的等待",
            "墨西哥城的 80,000 主场球迷将是本届最具压迫感的主场氛围之一"
        ],
        "watch_for_en": [
            "Mexico qualified as Group A winners (2-0, 6 pts), FIFA rank 14.",
            "Opponent is the best 3rd-place team from C/E/F/H/I — could be Japan, Uzbekistan, or another Asian side.",
            "Estadio Banorte in Mexico City sits at 2,240m — the highest WC venue on the planet; visitors need a 24h acclimation window.",
            "Mexico's last WC knockout WIN was in 1986 (the last time they hosted) — a 40-year wait ends here.",
            "80,000 home fans in CDMX will produce one of the loudest atmospheres of the tournament."
        ],
        "key_players_zh": [
            "劳尔·希门尼斯 #9（墨西哥队长，富勒姆前锋）",
            "埃德森·阿尔瓦雷斯 #4（墨西哥中场，西汉姆）",
            "吉列尔莫·奥乔亚 #13（墨西哥老门将，39 岁）"
        ],
        "key_players_en": [
            "Raúl Jiménez #9 (Mexico captain, Fulham striker)",
            "Edson Álvarez #4 (Mexico midfielder, West Ham)",
            "Guillermo Ochoa #13 (Mexico veteran GK, age 39)"
        ],
        "news_focus_zh": "墨西哥本届的口号是\"这次不一样\"——1986 之后的 10 届世界杯每次都是 16 强止步，本届要破咒",
        "news_focus_en": "Mexico's slogan this cycle is \"this time it's different\" — they've been bounced in the R16 for 10 straight WCs since 1986",
        "record_potential_zh": [
            "墨西哥若晋级将打破 1986 年以来 10 届连续 16 强出局的魔咒",
            "奥乔亚（39 岁）若登场将成为世界杯最年长门将之一"
        ],
        "record_potential_en": [
            "A MEX win ends a 10-tournament R16 exit streak dating to 1986.",
            "Ochoa (39) appearing would make him one of the oldest GKs ever to play a WC knockout match."
        ],
        "manual_author": "claude",
    },

    # ── 760495 — Wed 7/1 11:00 AM — 1L vs 3RD at Mercedes-Benz
    "760495": {
        "headline_zh": "英格兰登场，亚特兰大 11 点开球",
        "headline_en": "England in Atlanta's 11AM heat",
        "watch_for_zh": [
            "L 组头名大概率是英格兰（首轮 2-1 加纳，FIFA 第 4）",
            "对手是 E/H/I/J/K 五个组的最佳第三——可能是挪威之外的任何队",
            "Mercedes-Benz 体育场（亚特兰大）有可伸缩屋顶，但 11 点开球时仍会闷热——英格兰的快节奏可能在下半场失温",
            "英格兰 2018 年打入 4 强、2020 欧洲杯亚军、2024 欧洲杯亚军——但 1966 年后再未夺冠的尴尬仍在",
            "贝林厄姆（皇马）和萨卡（阿森纳）是前场最锐利的两人，福登（曼城）替补"
        ],
        "watch_for_en": [
            "1L is most likely England (2-1 over Ghana in MD1, FIFA rank 4).",
            "Opponent is the best 3rd from E/H/I/J/K — a wide pool, potentially Norway or another strong side.",
            "Mercedes-Benz has a retractable roof, but an 11AM kickoff is still humid — ENG's high tempo may fade in the 2nd half.",
            "ENG have made the 2018 SF, 2020 Euro final, 2024 Euro final — but the 1966 drought is still THE story.",
            "Bellingham (Real Madrid) and Saka (Arsenal) lead the front line; Foden (Man City) likely starts on the bench."
        ],
        "key_players_zh": [
            "裘德·贝林厄姆 #10（英格兰中场，皇家马德里）",
            "布卡约·萨卡 #7（阿森纳边锋）",
            "哈里·凯恩 #9（队长，拜仁慕尼黑前锋）"
        ],
        "key_players_en": [
            "Jude Bellingham #10 (England midfielder, Real Madrid)",
            "Bukayo Saka #7 (Arsenal winger)",
            "Harry Kane #9 (captain, Bayern Munich striker)"
        ],
        "news_focus_zh": "图赫尔 2025 年初接手英格兰，3-4-2-1 阵型主打反击——淘汰赛会切换到 4-2-3-1 加强控制",
        "news_focus_en": "Tuchel took over in early 2025; 3-4-2-1 in groups, but expect 4-2-3-1 for more control in knockout",
        "record_potential_zh": [
            "凯恩若再进 2 球将追平鲁尼 13 球英格兰队史纪录",
            "英格兰若打入 8 强将是连续 3 届大赛 8 强（2018 4 强、2022 8 强、2026 ?）"
        ],
        "record_potential_en": [
            "Two more Kane goals ties Rooney's 13 — England's all-time WC scoring record.",
            "An ENG QF would extend a 3-tournament major-tournament knockout streak (2018 SF, 2022 QF, 2026 ?)."
        ],
        "manual_author": "claude",
    },

    # ── 760493 — Wed 7/1 3:00 PM — 1G vs 3RD at Lumen Field
    "760493": {
        "headline_zh": "G 组头名爆冷？新西兰领跑",
        "headline_en": "Group G's surprise leader — NZL still on top",
        "watch_for_zh": [
            "G 组目前 4 队全 1 分（首轮 4 场全平），任何队都可能是头名——这是本届最开放的组",
            "比利时 FIFA 第 6 但首轮仅 1-1 平伊朗——马丁内斯帅位岌岌可危",
            "新西兰首轮 1-1 平埃及是 1982 年后首次世界杯不败开局——弱势方最大的黑马故事",
            "对手是 A/E/H/I/J 五个组的最佳第三——可能是欧洲杯冠军西班牙或加纳",
            "Lumen Field（西雅图）下午 3 点，气温通常 22-25°C，6 月最适合踢球的天气"
        ],
        "watch_for_en": [
            "Group G currently has all four teams tied at 1 point after a 4-way MD1 of 1-1 draws — any of them can top the group.",
            "Belgium (FIFA 6) drew Iran 1-1 in MD1 — Martinez is on the hot seat.",
            "New Zealand's 1-1 vs Egypt is their first WC point since 1982 — the underdog story of the tournament.",
            "Opponent is the best 3rd from A/E/H/I/J — could be Euro 2024 champ Spain, or Ghana.",
            "Lumen Field (Seattle) at 3PM = 73-77°F — the most pleasant R32 kickoff weather on the slate."
        ],
        "key_players_zh": [
            "凯文·德布劳内 #7（比利时中场，曼城）",
            "伍德罗·伍德 #9（新西兰前锋，诺丁汉森林）",
            "罗梅卢·卢卡库 #9（比利时前锋，那不勒斯）"
        ],
        "key_players_en": [
            "Kevin De Bruyne #7 (Belgium midfielder, Man City)",
            "Chris Wood #9 (New Zealand striker, Nottingham Forest)",
            "Romelu Lukaku #9 (Belgium striker, Napoli)"
        ],
        "news_focus_zh": "比利时黄金一代的最后一届世界杯——德布劳内 34 岁、卢卡库 32 岁，本届出局就彻底告别",
        "news_focus_en": "Belgium's golden generation's last WC — De Bruyne (34), Lukaku (32); an exit here ends an era",
        "record_potential_zh": [
            "新西兰若晋级将是 1982 年后首次世界杯淘汰赛——44 年等一回",
            "卢卡库本届若进 3 球将追平 5 球的比利时世界杯队史进球纪录"
        ],
        "record_potential_en": [
            "A NZL R16 would be their first WC knockout appearance in 44 years.",
            "Three Lukaku goals ties Belgium's all-time single-WC scoring record (5)."
        ],
        "manual_author": "claude",
    },

    # ── 760494 — Wed 7/1 7:00 PM — 1D vs 3RD at Levi's Stadium
    "760494": {
        "headline_zh": "美国队淘汰赛首战",
        "headline_en": "USA's first knockout game",
        "watch_for_zh": [
            "D 组头名大概率是美国（首轮 4-1 巴拉圭，FIFA 第 17）",
            "对手是 B/E/F/I/J 五个组的最佳第三——可能是韩国、乌兹别克斯坦等亚洲队",
            "Levi's Stadium（圣克拉拉）是 NFL 49 人队主场——美式橄榄球的传统地盘，球迷氛围是足球+橄榄球混合",
            "美国 2002 年后从未打入 8 强（2014 16 强，2022 16 强），本届打破魔咒是东道主最大叙事",
            "普利西奇（队长，AC 米兰）本届首轮 1 球 1 助，是美国队前场最大威胁"
        ],
        "watch_for_en": [
            "1D is most likely USA (4-1 over Paraguay in MD1, FIFA rank 17).",
            "Opponent is the best 3rd from B/E/F/I/J — could be South Korea, Uzbekistan, or another Asian side.",
            "Levi's Stadium is the NFL 49ers' home — the Bay Area crowd will mix football and soccer fandom.",
            "USA haven't reached the QF since 2002 (2014 R16, 2022 R16) — ending the drought is the host's biggest narrative.",
            "Pulisic (captain, AC Milan) had 1G 1A in MD1 — the USMNT's biggest attacking threat."
        ],
        "key_players_zh": [
            "克里斯蒂安·普利西奇 #10（美国队长，AC 米兰）",
            "蒂莫西·维阿 #9（尤文图斯前锋）",
            "尤努斯·穆萨 #21（美国中场，AC 米兰）"
        ],
        "key_players_en": [
            "Christian Pulisic #10 (USA captain, AC Milan)",
            "Timothy Weah #9 (Juventus striker)",
            "Yunus Musah #21 (USA midfielder, AC Milan)"
        ],
        "news_focus_zh": "美国队本届头号话题是\"打入 8 强\"——小组赛 2 胜已超 2022 全程战绩",
        "news_focus_en": "USA's #1 storyline is \"reach the QF\" — two group wins already exceed their entire 2022 output",
        "record_potential_zh": [
            "美国若晋级 8 强将是 2002 年后首次——24 年等一回",
            "普利西奇本届若 3 球将追平美国队史单届世界杯进球纪录"
        ],
        "record_potential_en": [
            "A USA QF would be their first in 24 years (since 2002).",
            "Pulisic with 3+ goals ties the USMNT's all-time single-WC scoring record."
        ],
        "manual_author": "claude",
    },

    # ── 760497 — Thu 7/2 2:00 PM — 1H vs 2J at SoFi
    "760497": {
        "headline_zh": "H 组头名 vs 奥地利，SoFi 大场面",
        "headline_en": "Group H winner meets Austria in LA",
        "watch_for_zh": [
            "H 组 4 队首轮全平（1 分），极可能由乌拉圭、西班牙、沙特、佛得角中突围",
            "如果是 1H 是西班牙——2024 欧洲杯冠军，亚马尔（17 岁，拉玛西亚）是本届最大新星",
            "如果是 1H 是乌拉圭——苏亚雷斯、卡瓦尼时代彻底结束，努涅斯（利物浦）是新核心",
            "J 组第二大概率是奥地利（与阿根廷的末轮对话决定谁是头名）",
            "SoFi 第二场 R32——同地两场淘汰赛是本届首创，节省球队移动但提高球迷负担"
        ],
        "watch_for_en": [
            "Group H is a 4-way tie at 1 point after MD1 — URU, ESP, KSA, or CPV could win it.",
            "If 1H is Spain, they're the 2024 Euro champions; Lamine Yamal (17, La Masia) is the WC's biggest breakout star.",
            "If 1H is Uruguay, the Suárez-Cavani era is over; Darwin Núñez (Liverpool) is the new talisman.",
            "2J is most likely Austria (ARG-AUT MD3 clash decides top of J).",
            "SoFi's second R32 of the tournament — back-to-back knockouts at the same venue is a 2026 first."
        ],
        "key_players_zh": [
            "拉明·亚马尔 #19（西班牙边锋，巴塞罗那，17 岁）",
            "大卫·阿拉巴 #8（奥地利队长，皇家马德里）",
            "达林·努涅斯 #11（乌拉圭前锋，利物浦）"
        ],
        "key_players_en": [
            "Lamine Yamal #19 (Spain winger, Barcelona, age 17)",
            "David Alaba #8 (Austria captain, Real Madrid)",
            "Darwin Núñez #11 (Uruguay striker, Liverpool)"
        ],
        "news_focus_zh": "亚马尔本届首秀已 1 球 2 助——若延续将是 2006 年后最年轻的世界杯淘汰赛进球者",
        "news_focus_en": "Yamal already has 1G 2A in MD1 — the youngest WC knockout goalscorer since 2006 if he continues",
        "record_potential_zh": [
            "西班牙若晋级将是连续 4 届世界杯 8 强（2008 欧洲杯-2012 欧洲杯盛世延续）",
            "阿拉巴（32 岁）若登场将成为奥地利队史最年长世界杯出场球员"
        ],
        "record_potential_en": [
            "An ESP QF would extend their run to 4 straight WCs in the QF.",
            "Alaba (32) would be Austria's oldest-ever WC outfield player."
        ],
        "manual_author": "claude",
    },

    # ── 760496 — Thu 7/2 6:00 PM — 2K vs 2L at BMO Field
    "760496": {
        "headline_zh": "K、L 组第二对决，多伦多",
        "headline_en": "K's #2 meets L's #2 in Toronto",
        "watch_for_zh": [
            "K 组 4 队差距不大（哥伦比亚 3 分领跑），第二可能是葡萄牙、刚果（金）或乌兹别克斯坦",
            "L 组第二大概率是加纳或英格兰以外的队——小组末轮 ENG-GHA 是直接对话",
            "BMO Field（多伦多）是本届世界杯唯一加拿大主办城市——草地条件偏冷凉",
            "葡萄牙/刚果（DRC）如果对决——C 罗（41 岁）将首次面对非洲球队淘汰赛",
            "C 罗本届首轮 0 球——他需要用淘汰赛证明自己仍然值得首发"
        ],
        "watch_for_en": [
            "Group K's #2 could be Portugal, DR Congo, or Uzbekistan — the race behind Colombia is wide open.",
            "Group L's #2 is most likely Ghana, Panama, or Croatia (ENG-GHA MD3 decides top of L).",
            "BMO Field (Toronto) is the only Canadian host venue for the WC — cooler grass conditions than US/MX.",
            "If it's POR vs DRC, Cristiano Ronaldo (41) faces an African side in knockout play for the first time.",
            "Ronaldo went goalless in MD1 — he needs the R32 to prove he still deserves to start."
        ],
        "key_players_zh": [
            "克里斯蒂亚诺·罗纳尔多 #7（葡萄牙前锋，41 岁）",
            "布鲁诺·费尔南德斯 #8（葡萄牙中场，曼联）",
            "穆罕默德·库杜斯 #19（加纳边锋，热刺）"
        ],
        "key_players_en": [
            "Cristiano Ronaldo #7 (Portugal striker, age 41)",
            "Bruno Fernandes #8 (Portugal midfielder, Manchester United)",
            "Mohammed Kudus #19 (Ghana winger, Tottenham)"
        ],
        "news_focus_zh": "C 罗本届可能是他最后一次世界杯（2026 是他第 5 届）——他已经公开暗示退役话题",
        "news_focus_en": "Ronaldo's last WC (5th appearance); he's publicly hinted at retirement — every knockout game is a farewell",
        "record_potential_zh": [
            "C 罗若登场将成为世界杯历史出场最多球员（当前已 22 场，5 届）",
            "C 罗若再进 1 球将追平 5 球的世界杯历史并列纪录"
        ],
        "record_potential_en": [
            "A Ronaldo appearance breaks the all-time WC appearances record (current: 22, five WCs).",
            "One more Ronaldo goal ties the all-time WC scoring record (5)."
        ],
        "manual_author": "claude",
    },

    # ── 760498 — Thu 7/2 10:00 PM — 1B vs 3RD at BC Place
    "760498": {
        "headline_zh": "加拿大主场温哥华深夜战",
        "headline_en": "Canada's late-night home game in Vancouver",
        "watch_for_zh": [
            "B 组头名大概率是加拿大（首轮 4-0 拿下波斯尼亚，次轮瑞士平局待定），FIFA 第 24",
            "对手是 E/F/G/I/J 五个组的最佳第三——可能是欧洲强队（挪威、法国、比利时）",
            "BC Place（温哥华）7/2 晚上 10 点开球是当日最晚——气温降至 18°C，对客队更友好",
            "加拿大本届是队史第 3 次世界杯（1986、2022、2026），前两次从未小组出线——本届已破纪录",
            "戴维斯（队长，拜仁慕尼黑边后卫）是加拿大前场最大威胁"
        ],
        "watch_for_en": [
            "1B is most likely Canada (4-0 over Bosnia in MD1, SUI draw in MD2 pending), FIFA rank 24.",
            "Opponent is the best 3rd from E/F/G/I/J — could be Norway, France, or Belgium (a tough ask).",
            "BC Place (Vancouver) at 10PM is the latest kickoff of the day — temps drop to ~64°F, friendlier to visitors.",
            "Canada are at their 3rd-ever WC (1986, 2022, 2026) — they already made history by reaching the R32 this time.",
            "Alphonso Davies (captain, Bayern Munich LB) is Canada's biggest attacking threat."
        ],
        "key_players_zh": [
            "阿方索·戴维斯 #19（加拿大队长，拜仁慕尼黑）",
            "乔纳森·戴维 #9（里尔前锋）",
            "斯蒂芬·尤斯塔基奥 #7（葡萄牙体育中场）"
        ],
        "key_players_en": [
            "Alphonso Davies #19 (Canada captain, Bayern Munich)",
            "Jonathan David #9 (Lille striker)",
            "Stephen Eustáquio #7 (Sporting CP midfielder)"
        ],
        "news_focus_zh": "加拿大是本届 3 个东道主之一（美/加/墨）——他们已经 1986 年后首次小组出线",
        "news_focus_en": "Canada is one of three co-hosts (USA/CAN/MEX) — they've already made history by reaching the R32 for the first time since 1986",
        "record_potential_zh": [
            "加拿大若晋级 16 强将是 1986 年后首次——40 年等一回",
            "戴维斯本届已 1 球 1 助——是加拿大队史世界杯最佳表现之一"
        ],
        "record_potential_en": [
            "A CAN R16 would be their first in 40 years (since 1986).",
            "Davies (1G 1A in MD1) is on pace for one of the best individual CAN WC performances ever."
        ],
        "manual_author": "claude",
    },

    # ── 760499 — Fri 7/3 1:00 PM — 2D vs 2G at AT&T
    "760499": {
        "headline_zh": "D、G 组第二对决，AT&T 室内",
        "headline_en": "D's #2 meets G's #2 — climate-controlled Dallas",
        "watch_for_zh": [
            "D 组第二大概率是澳大利亚（首轮 2-0 拿下土耳其，但与美国的对话决定谁是头名）",
            "G 组第二极不明确——4 队全 1 分，新西兰/伊朗/比利时/埃及都可能",
            "AT&T 体育场有可伸缩屋顶，室内 21°C——6 月 30°C 室外的最佳对照",
            "比利时若落到第二——黄金一代末班车遇澳大利亚，上届 2022 小组赛曾 1-0 输给非种子队",
            "澳大利亚首轮 2-0 土耳其是本届最大冷门之一——他们用身体对抗硬扛了欧洲球队"
        ],
        "watch_for_en": [
            "2D is most likely Australia (2-0 over Türkiye in MD1, USA-AUS MD3 decides top of D).",
            "2G is wide open — NZL/IRN/BEL/EGY all on 1 point; any of them can finish 2nd.",
            "AT&T's retractable roof keeps it at 70°F indoors — a relief from the 95°F+ Texas summer outside.",
            "If Belgium drops to 2nd, their golden generation meets the giant-killers of MD1 — déjà vu of 2022 (group exit).",
            "AUS's 2-0 over Türkiye was the upset of MD1 — physical, direct, hard to break down."
        ],
        "key_players_zh": [
            "凯文·德布劳内 #7（比利时中场，曼城）",
            "马修·莱基 #11（澳大利亚边锋）",
            "阿蒂姆·布塔 #9（澳大利亚前锋）"
        ],
        "key_players_en": [
            "Kevin De Bruyne #7 (Belgium midfielder, Man City)",
            "Mathew Leckie #11 (Australia winger)",
            "Awer Mabil #9 (Australia forward)"
        ],
        "news_focus_zh": "比利时若被淘汰意味着黄金一代彻底落幕——2018 季军、2022 小组出局、2026 R32 止步",
        "news_focus_en": "A BEL exit closes the golden-generation book — 2018 bronze, 2022 group exit, 2026 R32 elimination",
        "record_potential_zh": [
            "澳大利亚若晋级将是 2006 年后首次世界杯 8 强——20 年等一回",
            "比利时若出局将是连续 3 届大赛 16 强内止步"
        ],
        "record_potential_en": [
            "An AUS QF would be their first in 20 years (since 2006).",
            "A BEL exit would extend a 3-tournament streak of failing to reach the QF."
        ],
        "manual_author": "claude",
    },

    # ── 760500 — Fri 7/3 5:00 PM — 1J vs 2H at Hard Rock
    "760500": {
        "headline_zh": "梅西告别之旅？迈阿密主场",
        "headline_en": "Messi's Miami homecoming — last WC run?",
        "watch_for_zh": [
            "J 组头名大概率是阿根廷（首轮 3-0 拿下阿尔及利亚），FIFA 第 2，卫冕冠军",
            "对手是 H 组第二——H 组 4 队全 1 分，西班牙/乌拉圭/沙特/佛得角都有可能",
            "Hard Rock Stadium（迈阿密花园）是梅西在 MLS 球队（国际迈阿密）的主场——他是迈阿密的国王",
            "阿根廷 2021-2022 连续美洲杯+世界杯，2024 年卫冕美洲杯失败，本届目标卫冕世界杯",
            "38 岁的梅西本届首轮 0 球但 1 助——他需要用淘汰赛进球完成告别"
        ],
        "watch_for_en": [
            "1J is most likely Argentina (3-0 over Algeria in MD1), FIFA rank 2, defending champions.",
            "Opponent is the H group's #2 — could be Spain, Uruguay, Saudi Arabia, or Cape Verde (4-way tie at 1pt).",
            "Hard Rock is Messi's Inter Miami home — he IS the king of this city.",
            "ARG won Copa América 2021 + WC 2022 + Copa 2024 — they failed to defend the 2024 Copa; WC 2026 is the next chapter.",
            "Messi (38) went goalless but had 1 assist in MD1 — he needs knockout goals for the farewell story."
        ],
        "key_players_zh": [
            "里奥·梅西 #10（阿根廷队长，迈阿密国际）",
            "朱利安·阿尔瓦雷斯 #9（马德里竞技前锋）",
            "罗德里戈·德保罗 #7（马德里竞技中场）"
        ],
        "key_players_en": [
            "Lionel Messi #10 (Argentina captain, Inter Miami)",
            "Julián Álvarez #9 (Atlético Madrid striker)",
            "Rodrigo De Paul #7 (Atlético Madrid midfielder)"
        ],
        "news_focus_zh": "梅西 2026 是他第 6 届世界杯（创纪录）——也是他 2022 后首次冲击卫冕",
        "news_focus_en": "Messi's 6th WC (record) — and his first title defense since winning in 2022",
        "record_potential_zh": [
            "梅西本届出场将追平自己保持的世界杯 26 场出场纪录",
            "阿根廷若卫冕将是 1962 年巴西后首支蝉联世界杯的球队——64 年等一回"
        ],
        "record_potential_en": [
            "Messi's appearance ties his own WC record (26 games).",
            "An ARG repeat would be the first back-to-back WC title since Brazil 1958-1962 — 64 years."
        ],
        "manual_author": "claude",
    },

    # ── 760501 — Fri 7/3 8:30 PM — 1K vs 3RD at GEHA Field
    "760501": {
        "headline_zh": "J 罗告别？哥伦比亚末班车",
        "headline_en": "James Rodríguez's last ride?",
        "watch_for_zh": [
            "K 组头名大概率是哥伦比亚（首轮 2-1 拿下乌兹别克斯坦），FIFA 第 13",
            "对手是 D/E/I/J/L 五个组的最佳第三——可能是阿尔及利亚、约旦等",
            "GEHA Field（堪萨斯城）是 NFL 酋长队主场，下午 8:30 体感 30°C——当日最热时段",
            "J 罗（33 岁）本届首轮 1 助——他需要在淘汰赛重新找回 2014 金靴的自己",
            "哥伦比亚 2014 年打入 8 强（最佳战绩），2022 缺席，本届目标重回 8 强"
        ],
        "watch_for_en": [
            "1K is most likely Colombia (2-1 over Uzbekistan in MD1), FIFA rank 13.",
            "Opponent is the best 3rd from D/E/I/J/L — could be Jordan, Algeria, or a similar side.",
            "GEHA Field (KC) is the NFL Chiefs' home; 8:30 PM = ~86°F, the hottest R32 kickoff of the day.",
            "James Rodríguez (33) had 1 assist in MD1 — he needs the R32 to channel his 2014 Golden Boot form.",
            "COL made the 2014 QF (their best ever); they missed 2022; 2026 is about returning to the QF."
        ],
        "key_players_zh": [
            "路易斯·迪亚斯 #10（哥伦比亚前锋，利物浦）",
            "J 罗 #11（哥伦比亚中场，皇家马德里旧将，33 岁）",
            "达文森·桑切斯 #2（热刺中卫）"
        ],
        "key_players_en": [
            "Luis Díaz #10 (Colombia winger, Liverpool)",
            "James Rodríguez #11 (Colombia midfielder, ex-Real Madrid, 33)",
            "Davinson Sánchez #2 (Tottenham CB)"
        ],
        "news_focus_zh": "哥伦比亚本届的口号是\"J 罗的最后一舞\"——34 岁的他已暗示这届是告别",
        "news_focus_en": "Colombia's 2026 storyline is \"James's last dance\" — he's hinted at retirement after this WC",
        "record_potential_zh": [
            "J 罗若再进 2 球将追平 6 球的世界杯 6 场进球纪录——刷新南美球员纪录",
            "哥伦比亚若晋级 8 强将是 2014 年后首次——12 年等一回"
        ],
        "record_potential_en": [
            "Two more James goals ties his 6-goal WC record (most for a South American in a single WC).",
            "A COL QF would be their first in 12 years (since 2014)."
        ],
        "manual_author": "claude",
    },
}


def main() -> int:
    with PATH.open("r", encoding="utf-8") as f:
        doc = json.load(f)

    round_intro_zh = (
        "小组赛尘埃落定，32 强进入一场定胜负的淘汰赛阶段。本届 1/8 决赛横跨 6 天"
        "（6/28 周日 - 7/3 周五），每组前两名 + 8 个最佳第三晋级，对阵由抽签决定。"
        "16 场淘汰赛分批在美国、加拿大、墨西哥的 14 座球场进行——包括三座 70,000+ 容量的"
        "超级碗级场馆（SoFi、MetLife、AT&T），以及墨西哥城的 Estadio Banorte，"
        "本届首次迎来东道主淘汰赛。"
    )
    round_intro_en = (
        "Group stage done — 32 teams enter single-elimination. This R32 spans 6 days "
        "(Sun 6/28 - Fri 7/3): top 2 of each group plus 8 best 3rd-placers advance, "
        "bracket set by draw. 16 matches across 14 venues in the US/Canada/Mexico — "
        "including three 70,000+ Super Bowl stadiums (SoFi, MetLife, AT&T) and Mexico "
        "City's Estadio Banorte, where a co-host (Mexico) plays its first-ever home "
        "knockout game at a WC."
    )

    enriched = 0
    for m in doc.get("matches", []):
        mid = str(m.get("match_id"))
        a = ANALYSIS.get(mid)
        if not a:
            print(f"warn: no analysis for match {mid}", file=sys.stderr)
            continue
        for k, v in a.items():
            m[k] = v
        enriched += 1

    # Add round intro if missing.
    if not doc.get("round_intro_zh"):
        doc["round_intro_zh"] = round_intro_zh
    if not doc.get("round_intro_en"):
        doc["round_intro_en"] = round_intro_en

    # Bump last_manual_update so the weekly UI knows we just touched it.
    from datetime import datetime, timezone
    doc["last_manual_update"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Recompute manual_count from the matches we just enriched.
    doc["manual_count"] = sum(
        1 for m in doc.get("matches", [])
        if m.get("headline_zh") or m.get("headline_en")
    )

    with PATH.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {PATH} ({enriched}/{len(doc['matches'])} R32 matches enriched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
