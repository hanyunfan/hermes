#!/usr/bin/env python3
"""
Enrich the group-stage MD3 weekly-picks round with manual analysis.

Idempotent: re-running overwrites the manual fields of every match in
the MD3 round with the canonical analysis below. The auto fields
(stakes_*, score, verdict) are preserved from build_weekly_picks.py.

Manual enrichment workflow:
  1. python3 scripts/build_weekly_picks.py   (refresh auto fields)
  2. python3 scripts/enrich_md3_picks.py     (apply this analysis)
  3. Commit + push

Why a separate script: the CI runs build_weekly_picks.py every 30 min
and preserves manual fields per match_id. The enrichment here is the
"curated" layer on top — easier to maintain as a standalone file than
baking the long analysis dicts into the build script.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
PICK_PATH = DATA_DIR / "weekly-picks.json"

ROUND_ID = "group-stage-md3-2026-06-24-2026-06-27"

ROUND_INTRO_ZH = (
    "小组赛第三轮是出线日。48 支球队里 16 支已经提前回家（B/C 两组全部结束，"
    "再加上其他 8 个小组的末位），剩下 32 支里的 16 支今晚就要知道是走是留。"
    "本周 16 场里有 6 场是真正的「必看」——胜者拿头名/晋级，败者回家或跌入死亡半区；"
    "另外 8 场是「可看可不看」，主队已经锁头名但仍有名将告别或东道主谢幕的剧情线；"
    "2 场可以跳过（双方都已出局或一方锁头名对方已出局）。\n\n"
    "最具看点的 5 场：Uruguay vs Spain（H 组头名之争，乌拉圭非赢不可，"
    "Suarez 最后一届）、Norway vs France（I 组头名之争，"
    "Haaland vs Mbappé 新双骄对决）、Colombia vs Portugal（K 组头名之争，"
    "J 罗告别 vs C 罗告别巡演）、Japan vs Sweden（F 组第二之争，"
    "瑞典非赢不可）、Paraguay vs Australia（D 组第二之争，胜者晋级）。\n\n"
    "另外 4 场因为没有 top-10 球队被本 digest 砍掉但同样精彩："
    "Egypt vs Iran（6/26 10pm CT 萨拉赫的出线悬念）、"
    "Croatia vs Ghana（6/27 4pm CT 魔笛最后一届生死战）、"
    "Korea vs South Africa（6/24 8pm CT 韩国出线生死战，已完赛）、"
    "Czechia vs Mexico（6/24 8pm CT 捷克背水一战，已完赛）。"
)

ROUND_INTRO_EN = (
    "Matchday 3 is decision day. 16 of the 48 teams are already out "
    "(all of B and C, plus 8 group-stage dead lasts), and the other "
    "16 will know their fate tonight. Of the 16 picks this round, "
    "6 are real must-watches where the winner advances or locks the "
    "top seed; 8 are lively, often because the locked team still has "
    "a farewell storyline (Suarez, Modric, Messi, etc.); and 2 are "
    "skippable dead rubbers.\n\n"
    "Top 5: Uruguay vs Spain (H top spot, Uruguay must win, Suarez's "
    "last dance), Norway vs France (I top spot, Haaland vs Mbappé), "
    "Colombia vs Portugal (K top spot, James vs Ronaldo farewell "
    "tours), Japan vs Sweden (F #2 spot, Sweden must win), Paraguay "
    "vs Australia (D #2 spot, winner takes all).\n\n"
    "Four more matches didn't make the top-16 cap but are still "
    "worth a look: Egypt vs Iran (6/26 10pm CT, Salah's lifeline), "
    "Croatia vs Ghana (6/27 4pm CT, Modric's likely last World Cup "
    "match), Korea vs South Africa (6/24 8pm CT, Korea's lifeline — "
    "now final), and Czechia vs Mexico (6/24 8pm CT, Czechia's last "
    "stand — now final)."
)

MANUAL_NOTE_ZH = (
    "排序按推荐分降序。6/25 早（CT）发出的版本，赛果随时更新。"
    "前 2 场（MAR/HAI、SCO/BRA，6/24 5pm CT）已完赛，结果在比分卡上。"
    "CZE-MEX、RSA-KOR（6/24 8pm CT）已被自动脚本的 top-16 淘汰——见本 digest 的引言部分。"
)

MANUAL_NOTE_EN = (
    "Sorted by analyst score. Issued early 6/25 CT — the first two "
    "picks (MAR/HAI, SCO/BRA, 6/24 5pm CT) are final; live scores on "
    "the match cards. CZE-MEX and RSA-KOR (6/24 8pm CT) were cut by "
    "the top-16 cap once the data refresh put Group A in mp=3 — see "
    "the round intro for the dropped-list context."
)

# (match_id) -> manual analysis dict
# verdict: must / lively / skip
# score: 1-5
ANALYSIS = {
    "760464": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "摩洛哥冲头名",
        "headline_en": "Morocco chasing the top seed",
        "watch_for_zh": [
            "摩洛哥 7 分已锁定 C 组晋级，本场不败即可保第二，赢则有望反超巴西拿头名",
            "海地 0 分 3 战全败已出局，本场是荣誉之战",
            "摩洛哥 2022 年闯入四强，本届想避开死亡半区必须争 1",
        ],
        "watch_for_en": [
            "Morocco already qualified from C on 7 pts; a draw locks 2nd, a win could leapfrog Brazil for 1st",
            "Haiti is 0-3 and out — playing for pride in their first WC since 1974",
            "Morocco's 2022 semifinal run means they're a tier-2 threat; the top seed matters for the R32 draw",
        ],
        "key_players_zh": [
            "阿什拉夫·哈基米 #2 (巴黎圣日耳曼边后卫)",
            "布拉欣·迪亚兹 #17 (皇家马德里攻击中场)",
            "杜杰兰·斯瓦伊尔斯 (海地门将，本届 3 场 17 扑救)",
        ],
        "key_players_en": [
            "Achraf Hakimi #2 (PSG right-back, set-piece taker)",
            "Brahim Díaz #17 (Real Madrid attacking midfielder)",
            "Johny Placide (HAI GK, 17 saves through 3 group games)",
        ],
        "news_focus_zh": "摩洛哥本届 3 战不败，已成为非洲足球新门面",
        "news_focus_en": "Morocco unbeaten through 3 — Africa's new standard-bearer after the 2022 semifinal run",
        "record_potential_zh": [
            "摩洛哥若不败即创非洲球队小组赛不败纪录（2014 尼日利亚 3 战 2 胜 1 负）",
        ],
        "record_potential_en": [
            "An unbeaten group stage would be the first by an African team in the modern 3-game format",
        ],
    },
    "760465": {
        "verdict": "skip",
        "score": 1,
        "headline_zh": "走过场：苏巴走过场",
        "headline_en": "Dead rubber: Brazil, Scotland gone",
        "watch_for_zh": [
            "巴西已锁 C 组头名，可能轮换主力",
            "苏格兰 3 分已无出线可能（摩洛哥 7 分压死）",
            "唯一看点：内马尔最后一届世界杯？",
        ],
        "watch_for_en": [
            "Brazil locked 1st in C; will likely rest starters",
            "Scotland out — Morocco's 7 pts means no path to advance",
            "Only storyline: is this Neymar's last World Cup?",
        ],
        "key_players_zh": [
            "维尼修斯·儒尼奥尔 #10 (皇家马德里边锋)",
            "罗德里戈 #11 (皇家马德里前锋)",
        ],
        "key_players_en": [
            "Vinícius Júnior #10 (Real Madrid LW, tournament top-3 chance)",
            "Rodrygo #11 (Real Madrid, likely starts if Neymar rests)",
        ],
        "news_focus_zh": "巴西本届前两场 1 胜 1 平，状态慢热但仍以头名出线",
        "news_focus_en": "Brazil started slow (1W-1D) but still topped C",
        "record_potential_zh": [
            "若内马尔出场，34 岁将是其最后一届世界杯",
        ],
        "record_potential_en": [
            "If Neymar plays, this is his World Cup farewell at 34",
        ],
        "why_skip_zh": "双方都已无晋级压力，巴西大概率轮换主力",
        "why_skip_en": "Both sides have nothing to play for; Brazil will likely rotate",
    },
    "760468": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "德国大轮换，厄瓜多尔冲第二",
        "headline_en": "Germany rotates, Ecuador chases #2",
        "watch_for_zh": [
            "德国 6 分已锁 E 组头名，预计大轮换——哈弗茨、穆西亚拉可能首发休息",
            "厄瓜多尔 1 分需赢 + 科特迪瓦输才能晋级，命运半在自己手里",
            "德国本届前 2 场 9 球火力恐怖，本场是走过程还是继续刷数据？",
        ],
        "watch_for_en": [
            "Germany locked 1st in E; Havertz/Musiala likely rest",
            "Ecuador (1 pt) needs a win AND a CIV loss to advance",
            "Germany scored 9 in 2 group games — do they keep foot on the gas?",
        ],
        "key_players_zh": [
            "弗洛里安·维尔茨 #17 (拜仁慕尼黑中场，本届 3 球)",
            "贾马尔·穆西亚拉 #10 (拜仁慕尼黑中场)",
            "埃内尔·瓦伦西亚 #13 (厄瓜多尔前锋，本届 2 球)",
        ],
        "key_players_en": [
            "Florian Wirtz #17 (Bayern midfielder, 3 goals in group)",
            "Jamal Musiala #10 (Bayern midfielder, possible rest)",
            "Enner Valencia #13 (Ecuador striker, 2 goals)",
        ],
        "news_focus_zh": "德国本届火力全开，但轮换深度才是 32 强赛的关键",
        "news_focus_en": "Germany's firepower is proven; depth matters more once the knockouts start",
        "record_potential_zh": [
            "维尔茨追平/打破德国球员单届小组赛进球纪录（克洛泽 2006 5 球）",
        ],
        "record_potential_en": [
            "Wirtz could match/break Klose's 2006 German WC group-stage record (5)",
        ],
    },
    "760469": {
        "verdict": "must",
        "score": 5,
        "headline_zh": "D 组第二名之争",
        "headline_en": "Group D's #2 spot on the line",
        "watch_for_zh": [
            "巴拉圭 3 分 vs 澳大利亚 3 分——直接对话，胜者拿 D 组第二",
            "美国已锁 1 名，巴拉圭和澳大利亚争另一张门票",
            "巴拉圭本届首战 1-0 输土耳其，4-1 输美国——本场是非赢不可的背水一战",
        ],
        "watch_for_en": [
            "Paraguay (3) vs Australia (3) — winner takes D's #2 spot, period",
            "USA locked 1st; this is the actual qualifier",
            "Paraguay lost to Turkey 0-1 and USA 1-4 — backs-against-the-wall",
        ],
        "key_players_zh": [
            "米格尔·阿尔米隆 #10 (纽卡斯尔联中场，巴拉圭核心)",
            "加斯顿·阿尔德里特 (澳大利亚门将，本届 12 扑救)",
            "马丁·博伊尔 (澳大利亚前锋，本届 1 球)",
        ],
        "key_players_en": [
            "Miguel Almirón #10 (Newcastle midfielder, talisman)",
            "Mathew Leckie (Australia winger, 1 goal)",
            "Mathew Ryan (Australia GK, 12 saves through group play)",
        ],
        "news_focus_zh": "澳大利亚是 2026 世界杯唯一来自亚足联的南半球球队",
        "news_focus_en": "Australia is the only AFC team from the Southern Hemisphere at this WC",
        "record_potential_zh": [
            "阿尔米隆有望追平/打破巴拉圭单届世界杯进球纪录",
        ],
        "record_potential_en": [
            "Almirón could match/break Paraguay's single-WC goal record",
        ],
    },
    "760470": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "东道主小组赛谢幕",
        "headline_en": "Co-host's group-stage curtain call",
        "watch_for_zh": [
            "美国 6 分已锁 D 组头名，本场预计大轮换——普利西奇可能休息",
            "土耳其 0 分 2 战全败已出局，本场荣誉之战",
            "SoFi 球场（10 万座位）爆满，东道主气氛拉满",
        ],
        "watch_for_en": [
            "USA locked 1st in D; Pulisic likely rests",
            "Turkey is 0-2 and out — playing for pride in front of 70k+ at SoFi",
            "Co-host's final group match — atmosphere will be electric",
        ],
        "key_players_zh": [
            "克里斯蒂安·普利西奇 #10 (AC 米兰边锋，美国队长)",
            "费卡约·图兰 #10 (土耳其老将，本届表现一般)",
            "克里斯蒂安·沙欣 (土耳其中场，可能首发)",
        ],
        "key_players_en": [
            "Christian Pulisic #10 (AC Milan, captain, possible rest)",
            "Hakan Çalhanoğlu #10 (Inter Milan, Turkey's only creative spark)",
            "Arda Güler #8 (Real Madrid, Turkey's young hope)",
        ],
        "news_focus_zh": "美国 6 分创历届小组赛最佳战绩，东道主效应显现",
        "news_focus_en": "USA's 6-pt group is the best in their WC history — the co-host bump is real",
        "record_potential_zh": [
            "若美国赢或平，6 分将创美国队历届小组赛最高分纪录",
        ],
        "record_potential_en": [
            "A win/draw locks USA's best-ever group-stage haul (6+ pts)",
        ],
    },
    "760471": {
        "verdict": "must",
        "score": 5,
        "headline_zh": "F 组头名之争",
        "headline_en": "Group F top-spot showdown",
        "watch_for_zh": [
            "日本 4 分不败即可锁 F 组第二，赢则反超荷兰拿头名",
            "瑞典 3 分必须赢才能晋级（且希望荷兰不胜，但概率低）",
            "日本本届逼平荷兰 + 2-0 胜突尼斯，状态爆表",
            "瑞典 5-1 大胜突尼斯后状态同样恐怖，3 分是必须",
        ],
        "watch_for_en": [
            "Japan (4) just needs a draw to lock 2nd; a win leapfrogs the Dutch",
            "Sweden (3) must win to advance (and hope NED-TUN goes their way)",
            "Japan held the Dutch 1-1 and beat Tunisia 2-0 — confident",
            "Sweden demolished Tunisia 5-1 — both teams in form",
        ],
        "key_players_zh": [
            "久保建英 #11 (皇家社会中场，本届 1 球 2 助攻)",
            "远藤航 #6 (利物浦中场，日本队长)",
            "亚历山大·伊萨克 #11 (纽卡斯尔前锋，瑞典头号射手)",
        ],
        "key_players_en": [
            "Takefusa Kubo #11 (Real Sociedad, 1G-2A so far)",
            "Wataru Endo #6 (Liverpool captain, defensive anchor)",
            "Alexander Isak #11 (Newcastle, Sweden's top scorer)",
        ],
        "news_focus_zh": "日本连续 4 届小组出线，本场争头名避开死亡半区",
        "news_focus_en": "Japan has made the R16 in 3 of the last 4 WCs; top seed matters for the bracket",
        "record_potential_zh": [
            "若久保建英再助攻，将追平日本单届世界杯助攻纪录（本田圭佑 2010 3 助攻）",
        ],
        "record_potential_en": [
            "Kubo could match Honda's 2010 single-WC assist record (3) for Japan",
        ],
    },
    "760472": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "荷兰锁头名，突尼斯谢幕",
        "headline_en": "Netherlands seals top seed, Tunisia bows out",
        "watch_for_zh": [
            "荷兰 4 分不败即可锁 F 组头名，赢则几乎肯定 1 名",
            "突尼斯 0 分 2 战全败已出局，2026 世界杯的告别战",
            "荷兰本届首战 1-1 平日本，第二战 4-0 大胜突尼斯——但本场是不同对手",
        ],
        "watch_for_en": [
            "Netherlands (4) just needs a draw to lock F's 1st seed",
            "Tunisia is 0-2 and out — group-stage farewell",
            "Netherlands held Japan 1-1 in MD1, demolished Tunisia 4-0 in MD2 — back-to-back group games vs Tunisia = weird",
        ],
        "key_players_zh": [
            "科迪·加克波 #11 (利物浦前锋，本届 2 球)",
            "维吉尔·范迪克 #4 (利物浦后卫，荷兰队长)",
            "约迪·德克特拉雷 (比利时/荷兰血统，本场未进大名单)",
        ],
        "key_players_en": [
            "Cody Gakpo #11 (Liverpool LW, 2 goals in group)",
            "Virgil van Dijk #4 (Liverpool captain)",
            "Xavi Simons #7 (RB Leipzig, Dutch creator)",
        ],
        "news_focus_zh": "荷兰本届目标至少 8 强——小组头名是必需",
        "news_focus_en": "Netherlands' floor this WC is the QF — top seed keeps them in the easier half",
        "record_potential_zh": [
            "加克波有望追平荷兰单届小组赛进球纪录（范佩西 2014 3 球）",
        ],
        "record_potential_en": [
            "Gakpo could match van Persie's 3-goal Dutch WC group-stage record (2014)",
        ],
    },
    "760473": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "E 组第二之争",
        "headline_en": "Ecuador chases, CIV locks 2nd",
        "watch_for_zh": [
            "科特迪瓦 3 分不败即可锁 E 组第二，赢则反超德国可能？不行——德国已锁 1",
            "库拉索 1 分 1 平 1 负已无晋级可能（厄瓜多尔 1 分但有净胜球优势）",
            "库拉索本届是 32 强里人口最少的国家（15 万）",
        ],
        "watch_for_en": [
            "CIV (3) just needs a draw to lock 2nd; a win locks 2nd outright",
            "Curaçao (1 pt) is out — ECU has GD advantage",
            "Curaçao is the smallest nation (pop. 150k) ever to play in a WC",
        ],
        "key_players_zh": [
            "塞科·福法纳 #4 (皇家马德里/布莱顿中场，本届 1 球)",
            "西蒙·德尔弗 (库拉索中场，本届唯一进球)",
        ],
        "key_players_en": [
            "Youssouf Fofana #4 (Real Madrid midfielder, possible rest)",
            "Janghyun Lee (Curaçao's veteran creator)",
        ],
        "news_focus_zh": "科特迪瓦是非洲冠军，本场锁定出线是最低要求",
        "news_focus_en": "CIV is the AFCON champion; anything less than qualification is a failure",
        "record_potential_zh": [
            "库拉索若再进球，将创队史世界杯进球纪录（目前与首届世界杯预选赛进球数持平）",
        ],
        "record_potential_en": [
            "Another goal for Curaçao would set their all-time WC record",
        ],
    },
    "760474": {
        "verdict": "skip",
        "score": 1,
        "headline_zh": "I 组走过场：塞伊双双出局",
        "headline_en": "Group I dead rubber: SEN/IRQ both out",
        "watch_for_zh": [
            "塞内加尔 0 分 + 伊拉克 0 分，I 组双双出局，本场是荣誉之战",
            "塞内加尔本届首战 0-2 输法国，次战 1-3 输挪威——本场避免 0 分收官",
            "伊拉克本届首战 1-2 输挪威，次战 0-1 输法国——本场避免 0 分收官",
        ],
        "watch_for_en": [
            "Senegal (0) + Iraq (0) — both already eliminated from I, playing for pride",
            "Senegal lost 0-2 to France and 1-3 to Norway — try to avoid zero-point group",
            "Iraq lost 1-2 to Norway and 0-1 to France — same, try to avoid zero-point group",
        ],
        "key_players_zh": [
            "塞迪奥·马内 #10 (沙特/塞内加尔前锋，本届表现一般)",
            "阿巴斯·阿萨德 (伊拉克中场)",
        ],
        "key_players_en": [
            "Sadio Mané #10 (Al-Nassr, Senegal captain, quiet group)",
            "Mohanad Ali (Iraq striker, AFCON veteran)",
        ],
        "news_focus_zh": "塞内加尔是 2024 非洲杯冠军，本届小组赛表现令人失望",
        "news_focus_en": "Senegal is the 2024 AFCON champion — group-stage exit is a real disappointment",
        "record_potential_zh": [],
        "record_potential_en": [],
        "why_skip_zh": "双方都已无晋级可能，本场不影响任何出线走势",
        "why_skip_en": "Neither side can advance; result has zero impact on the bracket",
    },
    "760475": {
        "verdict": "must",
        "score": 5,
        "headline_zh": "I 组头名之争：哈兰德 vs 姆巴佩",
        "headline_en": "Group I top seed: Haaland vs Mbappé",
        "watch_for_zh": [
            "挪威 6 分 vs 法国 6 分——直接对话决出 I 组头名",
            "两队都已提前出线（塞内加尔 0 分、伊拉克 0 分双双出局），本场是荣誉之战",
            "哈兰德 vs 姆巴佩：2026 年足坛最贵对决，新双骄的首次世界杯正面对话",
            "I 组头名意味着 32 强赛避开 H 组头名（西班牙/乌拉圭），抽到死亡半区的概率小一半",
        ],
        "watch_for_en": [
            "Norway (6) vs France (6) — straight up, winner takes I's 1st seed",
            "Both already qualified (Senegal and Iraq are 0-3)",
            "Haaland vs Mbappé: the first WC head-to-head for the new rivalry",
            "I's 1st seed avoids H's 1st (Spain or Uruguay) in the R32 draw — half the death-bracket risk",
        ],
        "key_players_zh": [
            "埃尔林·哈兰德 #9 (曼城前锋，本届 3 球)",
            "马丁·厄德高 #10 (阿森纳中场，挪威队长)",
            "基利安·姆巴佩 #10 (皇家马德里前锋，法国队长)",
            "奥雷连·楚阿梅尼 #8 (皇家马德里中场)",
        ],
        "key_players_en": [
            "Erling Haaland #9 (Man City, 3 goals in group)",
            "Martin Ødegaard #10 (Arsenal captain, creator)",
            "Kylian Mbappé #10 (Real Madrid, France captain)",
            "Aurélien Tchouaméni #8 (Real Madrid anchor)",
        ],
        "news_focus_zh": "哈兰德与姆巴佩 2018-2026 8 年来首次世界杯正面对话",
        "news_focus_en": "First-ever WC head-to-head between Haaland and Mbappé — 8 years in the making",
        "record_potential_zh": [
            "姆巴佩有望追平/打破法国单届世界杯进球纪录（方丹 1958 13 球）——难度大，但每进一球都是历史",
            "哈兰德追平挪威单届世界杯进球纪录（目前 3 球，纪录由 1998 弗洛/2002 卡尔斯特罗姆 共同保持）",
        ],
        "record_potential_en": [
            "Mbappé chases Fontaine's 13-goal French WC record (tough, but each goal is history)",
            "Haaland would tie Norway's single-WC goal record with another (3, shared 1998 Flo / 2002 Kärström)",
        ],
    },
    "760478": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "H 组黑马突围战",
        "headline_en": "Group H dark-horse chase",
        "watch_for_zh": [
            "佛得角 2 分需赢 + 乌拉圭输才能晋级——长局",
            "沙特 1 分本场是出线的最后希望（需赢 + 净胜球 + URU 大输）",
            "佛得角是非洲区预选赛黑马，本场是队史首次世界杯正赛末轮",
        ],
        "watch_for_en": [
            "Cape Verde (2) needs a win AND a URU loss to advance — long shot",
            "Saudi Arabia (1) needs a win + GD + URU blowout to advance — even longer shot",
            "Cape Verde is the WC debutant; their first-ever group-stage finale",
        ],
        "key_players_zh": [
            "瑞·洛德 (佛得角前锋，本届 1 球)",
            "萨利姆·阿尔-达瓦萨里 #10 (沙特前锋，本届 1 球)",
        ],
        "key_players_en": [
            "Ryan Mendes (Cape Verde forward, 1 goal)",
            "Salem Al-Dawsari #10 (Al-Hilal, Saudi Arabia's captain)",
        ],
        "news_focus_zh": "佛得角 100 万人口首次参加世界杯，已是史上最小参赛国之一",
        "news_focus_en": "Cape Verde (pop. 600k) is one of the smallest nations ever at a WC",
        "record_potential_zh": [
            "佛得角若晋级，将创人口最小晋级 32 强纪录",
        ],
        "record_potential_en": [
            "Cape Verde advancing would set the population record for R32",
        ],
    },
    "760477": {
        "verdict": "must",
        "score": 5,
        "headline_zh": "比利时出线生死战",
        "headline_en": "Belgium's lifeline",
        "watch_for_zh": [
            "比利时 2 分需赢才能保出线希望（且需埃及不胜伊朗）",
            "新西兰 1 分已无晋级可能，但这是新西兰 16 年来首次参加世界杯",
            "比利时黄金一代告别赛？德布劳内、阿扎尔最后一届",
        ],
        "watch_for_en": [
            "Belgium (2) needs a win AND an Egypt loss to advance",
            "New Zealand (1) is out — but their 1st WC appearance since 2010 is already a win",
            "Golden Generation farewell? De Bruyne and Lukaku are 34 and 32 respectively",
        ],
        "key_players_zh": [
            "凯文·德布劳内 #7 (曼城中场，比利时队长)",
            "罗梅卢·卢卡库 #9 (那不勒斯前锋，本届 1 球)",
            "扬·维尔通根 (新西兰后卫，本届场均 4.5 解围)",
        ],
        "key_players_en": [
            "Kevin De Bruyne #7 (Man City captain, 33)",
            "Romelu Lukaku #9 (Napoli, 1 goal — could carry team)",
            "Liberato Cacace (NZL LB, defensive workhorse)",
        ],
        "news_focus_zh": "比利时本届小组 2 平 1 负概率较低——黄金一代是否已过巅峰？",
        "news_focus_en": "Belgium's 2 draws already look shaky — is the golden generation past it?",
        "record_potential_zh": [
            "德布劳内追平/超越比利时单届世界杯助攻纪录（德利 1986 4 助攻）",
        ],
        "record_potential_en": [
            "De Bruyne could match/break Jan Ceulemans' 4-assist Belgian WC record (1986)",
        ],
    },
    "760479": {
        "verdict": "must",
        "score": 5,
        "headline_zh": "H 组头名之争：乌拉圭非赢不可",
        "headline_en": "Uruguay must win to advance",
        "watch_for_zh": [
            "乌拉圭 2 分 vs 西班牙 4 分——乌拉圭非赢不可，平局就可能回家（取决于 CPV 结果）",
            "西班牙不败即可锁 H 组头名，赢则 1 名",
            "路易斯·苏亚雷斯最后一届世界杯——本场是告别战？",
            "西班牙本届首战 0-0 平佛得角暴露问题，进攻端过于依赖 16 岁亚马尔",
        ],
        "watch_for_en": [
            "Uruguay (2) must WIN to advance; a draw could see them out if Cape Verde wins",
            "Spain (4) just needs a draw to lock H's 1st seed",
            "Luis Suárez's likely WC farewell at 39",
            "Spain drew Cape Verde 0-0 in MD1 — relying too much on 16-year-old Lamine Yamal",
        ],
        "key_players_zh": [
            "路易斯·苏亚雷斯 #9 (迈阿密国际前锋，乌拉圭传奇)",
            "费德里科·巴尔韦德 #15 (皇家马德里中场，本届 1 球)",
            "拉明·亚马尔 #19 (巴塞罗那边锋，西班牙 16 岁天才)",
            "罗德里 #16 (曼城中场，西班牙核心)",
        ],
        "key_players_en": [
            "Luis Suárez #9 (Inter Miami, WC farewell tour)",
            "Federico Valverde #15 (Real Madrid, 1 goal)",
            "Lamine Yamal #19 (Barcelona, 16 — WC's youngest scorer? already 1 goal)",
            "Rodri #16 (Man City, Spain's metronome)",
        ],
        "news_focus_zh": "苏亚雷斯最后一届世界杯 vs 西班牙青年军——新老对决",
        "news_focus_en": "Suárez's farewell vs Spain's teenage sensation — old guard meets new",
        "record_potential_zh": [
            "苏亚雷斯有望追平/打破乌拉圭单届世界杯进球纪录（斯卡罗内 1950 5 球）",
            "亚马尔 16 岁可能成为世界杯历史最年轻进球者",
        ],
        "record_potential_en": [
            "Suárez could match/broke Scarone's 5-goal Uruguayan WC record (1950)",
            "Yamal at 16 could become the youngest WC scorer ever",
        ],
    },
    "760481": {
        "verdict": "must",
        "score": 5,
        "headline_zh": "K 组头名之争：J 罗 vs C 罗",
        "headline_en": "Group K top seed: James vs Ronaldo",
        "watch_for_zh": [
            "哥伦比亚 6 分 vs 葡萄牙 4 分——胜者锁 K 组 1 名",
            "两队都已提前出线（COD 1 分、UZB 0 分双双出局），本场是头名之争",
            "J 罗 vs C 罗——两位世界杯传奇的最后一届？",
            "迈阿密 Hard Rock 球场（10 万座位）——南美 vs 欧洲的伊比利亚德比",
        ],
        "watch_for_en": [
            "Colombia (6) vs Portugal (4) — winner takes K's 1st seed",
            "Both already qualified (Congo DR and Uzbekistan are 1-and-0)",
            "James Rodríguez vs Cristiano Ronaldo — both likely last WC",
            "Hard Rock Stadium, Miami — 65k+ expected, Iberian derby in CONMEBOL territory",
        ],
        "key_players_zh": [
            "詹姆斯·罗德里格斯 #10 (莱昂中场，2014 金靴)",
            "路易斯·迪亚斯 #7 (利物浦边锋，本届 2 球)",
            "克里斯蒂亚诺·罗纳尔多 #7 (利雅得胜利前锋)",
            "布鲁诺·费尔南德斯 #8 (曼联中场)",
        ],
        "key_players_en": [
            "James Rodríguez #10 ( León, 2014 Golden Boot winner — likely last WC)",
            "Luis Díaz #7 (Liverpool, 2 goals in group)",
            "Cristiano Ronaldo #7 (Al-Nassr, 41 — confirmed last WC)",
            "Bruno Fernandes #8 (Man United, Portugal's creator)",
        ],
        "news_focus_zh": "C 罗 41 岁最后一届世界杯——追平/超越国际足联出场纪录（马吉迪 2014 / 5 届）",
        "news_focus_en": "Ronaldo at 41 ties the record for most WC tournaments played (5)",
        "record_potential_zh": [
            "C 罗出场将追平 5 届世界杯纪录（马吉迪 / 墨西哥传奇门将 2014）",
            "J 罗追平/打破哥伦比亚单届世界杯进球纪录",
        ],
        "record_potential_en": [
            "Ronaldo ties the 5-WC appearance record (Cárdenas / Antonio Carbajal)",
            "James could match/break Colombia's single-WC goal record",
        ],
    },
    "760483": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "梅西可能的最后一届小组赛",
        "headline_en": "Messi's possible last WC group game",
        "watch_for_zh": [
            "阿根廷 6 分已锁 J 组头名，可能轮换——但梅西大概率首发谢幕",
            "约旦 0 分 2 战全败已出局，本场是约旦 2026 世界杯的告别战",
            "AT&T 球场（8 万座位）爆满——阿根廷球迷占主导",
        ],
        "watch_for_en": [
            "Argentina (6) locked 1st in J; likely rest starters — but Messi may play for the farewell",
            "Jordan (0) is 0-2 and out — their first WC group-stage appearance since 2014",
            "AT&T Stadium (80k) sold out — Argentina fans dominant",
        ],
        "key_players_zh": [
            "利昂内尔·梅西 #10 (迈阿密国际前锋，阿根廷队长)",
            "朱利安·阿尔瓦雷斯 #9 (马德里竞技前锋)",
            "穆萨·阿尔-塔马里 #7 (摩纳哥边锋，约旦核心)",
        ],
        "key_players_en": [
            "Lionel Messi #10 (Inter Miami, likely last WC)",
            "Julián Álvarez #9 (Atlético Madrid, 1 goal)",
            "Musa Al-Tamari #7 (Monaco winger, Jordan's talisman)",
        ],
        "news_focus_zh": "阿根廷本届已锁 J 组头名，目标是卫冕——本场是走过程",
        "news_focus_en": "Argentina's locked 1st in J — the real tournament starts in the R32",
        "record_potential_zh": [
            "梅西本届 1 球，距离追平/打破世界杯历史最佳射手纪录（克洛泽 16 球）还需 7 球",
            "若梅西出场，将是其 6 届世界杯中的第 5 届出场（与马特乌斯 5 届纪录持平）",
        ],
        "record_potential_en": [
            "Messi is 7 goals behind Klose's all-time WC record (16)",
            "If Messi plays, he ties the record for most WC tournaments played (5, with Matthäus)",
        ],
    },
    "760485": {
        "verdict": "lively",
        "score": 3,
        "headline_zh": "英格兰锁头名，巴拿马谢幕",
        "headline_en": "England seals top seed, Panama bows out",
        "watch_for_zh": [
            "英格兰 4 分不败即可锁 L 组头名，赢则 1 名",
            "巴拿马 0 分 2 战全败已出局——本届首秀",
            "英格兰可能大轮换——凯恩、贝林厄姆可能首发休息",
        ],
        "watch_for_en": [
            "England (4) just needs a draw to lock L's 1st seed",
            "Panama (0) is 0-2 and out — their first WC group stage since 2018",
            "England likely rotate — Kane and Bellingham may sit",
        ],
        "key_players_zh": [
            "哈里·凯恩 #9 (拜仁慕尼黑前锋，英格兰队长)",
            "裘德·贝林厄姆 #10 (皇家马德里中场)",
        ],
        "key_players_en": [
            "Harry Kane #9 (Bayern, possible rest)",
            "Jude Bellingham #10 (Real Madrid, possible rest)",
        ],
        "news_focus_zh": "英格兰本届 1 胜 1 平状态稳定，目标是至少 8 强",
        "news_focus_en": "England's 1W-1D is steady; the goal is at least the QF",
        "record_potential_zh": [
            "若凯恩再进球，追平/超越莱因克尔英格兰世界杯进球纪录（10 球）",
        ],
        "record_potential_en": [
            "Kane is 2 behind Lineker's 10-goal England WC record",
        ],
    },
}


def main() -> int:
    if not PICK_PATH.exists():
        print(f"err: {PICK_PATH} not found", file=sys.stderr)
        return 2
    with PICK_PATH.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    rounds = doc.get("rounds") or []
    target = None
    for r in rounds:
        if r.get("round_id") == ROUND_ID:
            target = r
            break
    if target is None:
        print(f"err: round {ROUND_ID} not in {PICK_PATH}", file=sys.stderr)
        return 3

    target["round_intro_zh"] = ROUND_INTRO_ZH
    target["round_intro_en"] = ROUND_INTRO_EN
    target["manual_note_zh"] = MANUAL_NOTE_ZH
    target["manual_note_en"] = MANUAL_NOTE_EN
    target["last_manual_update"] = (
        datetime.now().astimezone().isoformat(timespec="seconds")
    )

    # Aggregate manual count at envelope level.
    matched = 0
    unmatched = []
    for m in target.get("matches", []):
        mid = str(m.get("match_id"))
        if mid not in ANALYSIS:
            unmatched.append(mid)
            continue
        a = ANALYSIS[mid]
        m["verdict"] = a["verdict"]
        m["score"] = a["score"]
        m["headline_zh"] = a["headline_zh"]
        m["headline_en"] = a["headline_en"]
        m["watch_for_zh"] = a["watch_for_zh"]
        m["watch_for_en"] = a["watch_for_en"]
        m["key_players_zh"] = a["key_players_zh"]
        m["key_players_en"] = a["key_players_en"]
        m["news_focus_zh"] = a["news_focus_zh"]
        m["news_focus_en"] = a["news_focus_en"]
        m["record_potential_zh"] = a["record_potential_zh"]
        m["record_potential_en"] = a["record_potential_en"]
        m["why_skip_zh"] = a.get("why_skip_zh")
        m["why_skip_en"] = a.get("why_skip_en")
        m["verdict_override"] = a["verdict"] if a["verdict"] != m.get("stakes_verdict_auto") else None
        m["score_override"] = a["score"] if a["score"] != m.get("stakes_score_auto") else None
        m["manual_author"] = "claude"
        matched += 1

    target["manual_count"] = sum(
        1 for m in target.get("matches", [])
        if m.get("headline_zh") or m.get("headline_en")
    )
    doc["manual_count"] = sum(
        sum(1 for mm in (r.get("matches") or []) if mm.get("headline_zh") or mm.get("headline_en"))
        for r in rounds
    )

    with PICK_PATH.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(
        f"wrote {PICK_PATH}: enriched {matched}/{len(ANALYSIS)} matches "
        f"in {ROUND_ID}; manual_count={target['manual_count']}"
    )
    if unmatched:
        print(f"warning: digest did not include {len(unmatched)} match(es): {unmatched}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
