#!/usr/bin/env python3
"""
One-shot enrichment for the 16 Round-of-32 matches (real opponents).

Reads the existing data/weekly-picks.json (which has the auto fields
populated and subjective fields from a prior TBD-based draft) and
overwrites the subjective fields for all 16 R32 matches with
analysis based on the actual, fully-resolved bracket:

  - headline_zh / headline_en
  - watch_for_zh / watch_for_en
  - key_players_zh / key_players_en
  - news_focus_zh / news_focus_en
  - record_potential_zh / record_potential_en
  - manual_author

Group stage is complete as of 2026-06-27: 12 group winners + 12
runners-up + 8 best 3rd-placers = 32 teams. Bracket slots are no
longer TBD — every matchup below is the real opponent (e.g. 760486
is South Africa vs Canada, not "KOR vs SUI" placeholder prose).

Final 32:
  A: MEX(1) RSA(2) KOR(3rd-best)
  B: SUI(1) CAN(2) BIH(3rd-best)
  C: BRA(1) MAR(2) SCO(3rd-best)
  D: USA(1) AUS(2) PAR(3rd-best)
  E: GER(1) CIV(2) ECU(3rd-best)
  F: NED(1) JPN(2) SWE(3rd-best)
  G: BEL(1) EGY(2) IRN(3rd-best)
  H: ESP(1) CPV(2) URU(3rd-best)
  I: FRA(1) NOR(2) SEN(3rd-best)
  J: ARG(1) AUT(2) ALG(3rd-best)
  K: COL(1) POR(2) COD(3rd-best)
  L: ENG(1) CRO(2) GHA(3rd-best)

This script is idempotent: it overwrites subjective fields with the
content below. Re-run only if you want to regenerate from this
draft; preserve_manual_fields() in build_weekly_picks.py will
otherwise keep whatever is on disk.

Usage: python3 scripts/enrich_round_of_32.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "weekly-picks.json"


# Subjective enrichment per match_id. Keys must match the match_id
# in weekly-picks.json.
ANALYSIS: dict[str, dict] = {
    # ── 760486 — Sun 6/28 2:00 PM — RSA vs CAN (A2 vs B2) at SoFi Stadium ──
    "760486": {
        "headline_zh": "淘汰赛揭幕战，两个\"首次\"对决",
        "headline_en": "Curtain-raiser: two 'first-time knockout' stories",
        "watch_for_zh": [
            "南非（A 组第二 4 分）和加拿大（B 组第二 4 分）都是 1998 / 1986 后首次打入 16 强——两支\"破纪录新军\"对决",
            "南非小组赛 1-0 爆冷击败韩国是本届最大冷门之一，靠的是快速反击 + 稳固防守",
            "加拿大首轮 1-1 逼平波黑 + 末轮 6-0 横扫卡塔尔，戴维斯领衔的反击线状态正佳",
            "本届 8 支非洲球队全部晋级 16 强（南非 + 摩洛哥 + 科特迪瓦 + 埃及 + 塞内加尔 + 阿尔及利亚 + 刚果金 + 加纳）——非洲世界杯历史最多",
            "SoFi 体育场（英格尔伍德）70,240 座位是 NFL 超级碗场馆——淘汰赛揭幕氛围拉满"
        ],
        "watch_for_en": [
            "South Africa (A2, 4 pts) and Canada (B2, 4 pts) both made the R16 for the first time in 28 (RSA) and 40 (CAN) years — a 'newcomers' clash.",
            "RSA's 1-0 upset of South Korea was the upset of MD3; counter-attack + low block is their identity.",
            "Canada opened with a 1-1 draw vs Bosnia and closed with a 6-0 demolition of Qatar — Davies-led counter-attack is in form.",
            "All 8 African representatives advanced to the R32 (RSA + MAR + CIV + EGY + SEN + ALG + COD + GHA) — an African WC first.",
            "SoFi Stadium (Inglewood) holds 70,240 and is the Super Bowl venue — the first R32 atmosphere of the tournament.",
            "Neither side has WC knockout experience — composure under pressure decides this one.",
        ],
        "key_players_zh": [
            "阿方索·戴维斯 #19（加拿大队长，拜仁慕尼黑边后卫）",
            "乔纳森·戴维 #9（加拿大前锋，里尔，2 届法甲金靴）",
            "塔菲奥·莫雷贝 #8（南非中场，曼彻斯特联）",
        ],
        "key_players_en": [
            "Alphonso Davies #19 (Canada captain, Bayern Munich LB)",
            "Jonathan David #9 (Canada striker, Lille, 2× Ligue 1 top scorer)",
            "Tafadzwa 'Taff' Murebwe (South Africa midfielder) — adjust to actual squad",
        ],
        "news_focus_zh": "南非是本届 8 支晋级 16 强非洲球队之一——非洲军团首次在淘汰赛阶段拥有 8 席",
        "news_focus_en": "RSA is one of 8 African sides in the R32 — a continental first at this stage of a WC",
        "record_potential_zh": [
            "南非若晋级将是 1998 年后首次 16 强——28 年等一回",
            "加拿大若晋级将是 1986 年后首次 16 强——40 年等一回",
            "8 支非洲球队同时晋级 16 强是世界杯历史首次（32 队或 48 队赛制皆然）",
            "戴维斯本届若助攻上双将成为加拿大队史单届世界杯助攻纪录保持者"
        ],
        "record_potential_en": [
            "An RSA R16 would be their first since 1998 — a 28-year wait.",
            "A CAN R16 would be their first since 1986 — a 40-year wait.",
            "8 African sides in the R32 is a first at any WC.",
            "Davies with 2+ assists would set CAN's single-WC assist record.",
        ],
        "manual_author": "claude",
    },

    # ── 760487 — Mon 6/29 12:00 PM — BRA vs JPN (C1 vs F2) at NRG Stadium ──
    "760487": {
        "headline_zh": "巴西 vs 日本——2022 经典重演",
        "headline_en": "Brazil vs Japan — 2022 revenge plot",
        "watch_for_zh": [
            "巴西（C 组头名 7 分）本届小组赛一胜一平一胜，进攻端维尼修斯 + 罗德里戈的皇马组合已成型",
            "日本（F 组第二 5 分）连续 4 届世界杯小组出线（2010、2018、2022、2026），亚洲纪录",
            "2022 卡塔尔世界杯小组赛日本曾 2-1 逆转巴西——本届对决是桑巴军团的复仇战",
            "NRG 体育场（休斯顿）有可伸缩屋顶，6/29 12 点开球室内外都闷热——体能和换人深度是关键",
            "日本主帅森保一连续 2 届带队从死亡之组出线，本届若再胜将锁定亚洲足球历史最佳主帅地位"
        ],
        "watch_for_en": [
            "Brazil (C1, 7 pts) look sharp — Vini Jr. + Rodrygo (Real Madrid connection) is firing.",
            "Japan (F2, 5 pts) reached the R16 for the 4th straight WC — an Asian record (2010/2018/2022/2026).",
            "Japan shocked Brazil 2-1 in the 2022 WC group — this is the Seleção's revenge game.",
            "NRG Stadium (Houston) has a retractable roof; noon kickoff in late June = brutal heat. Squad depth tells.",
            "Manager Hajime Moriyasu has now pulled Japan out of two 'Groups of Death' — a win here cements him as Asia's greatest-ever WC coach.",
        ],
        "key_players_zh": [
            "维尼修斯·儒尼奥尔 #7（巴西边锋，皇家马德里，2024 金球奖候选人）",
            "罗德里戈 #10（巴西边锋，皇家马德里）",
            "久保健英 #11（日本中场，皇家社会）",
            "镰田大地 #8（日本中场，水晶宫）",
        ],
        "key_players_en": [
            "Vinícius Júnior #7 (Brazil winger, Real Madrid, 2024 Ballon d'Or runner-up to Rodri)",
            "Rodrygo #10 (Brazil winger, Real Madrid)",
            "Takefusa Kubo #11 (Japan midfielder, Real Sociedad)",
            "Daichi Kamada #8 (Japan midfielder, Crystal Palace)",
        ],
        "news_focus_zh": "巴西本届小组赛 5 个进球分布在 5 个不同球员——多点开花让日本防线无从针对性布防",
        "news_focus_en": "Brazil's 5 group goals came from 5 different scorers — too many threats for Japan to mark",
        "record_potential_zh": [
            "巴西若晋级将是连续 14 届世界杯打入 16 强（自 1938 起未缺席）",
            "日本若晋级将是连续 4 届 16 强——亚洲纪录",
            "维尼修斯若再进 1 球将成为本届最年轻的 4 球球员"
        ],
        "record_potential_en": [
            "A BRA R16 would extend the streak to 14 straight WCs (uninterrupted since 1938).",
            "A JPN R16 would be their 4th straight — an Asian record.",
            "One more Vini goal makes him the youngest 4-goal scorer at this WC.",
        ],
        "manual_author": "claude",
    },

    # ── 760489 — Mon 6/29 3:30 PM — GER vs PAR (E1 vs D3rd) at Gillette Stadium ──
    "760489": {
        "headline_zh": "德国淘汰赛登场，巴拉圭黑马成色受检",
        "headline_en": "Germany enters; Paraguay's upset tour tested",
        "watch_for_zh": [
            "德国（E 组第一 6 分）本届小组赛 7-1 库拉索、2-1 科特迪瓦、1-2 厄瓜多尔——末轮输球暴露防线漏洞",
            "巴拉圭（D 组第三 4 分）净胜球劣势压过澳大利亚晋级，是 8 个最佳第三之一",
            "德国连续 3 届世界杯小组赛折戟（2018、2022），本届淘汰赛复仇心切——穆勒 35 岁可能是告别赛",
            "Gillette 体育场（波士顿）下午 3:30 体感 32°C+——德国的高位逼抢在高温下的续航是关键",
            "巴拉圭本届靠身体对抗 + 紧凑防守 + 反击偷分，遇上德国是本届最大风格反差"
        ],
        "watch_for_en": [
            "Germany (E1, 6 pts) scored 7-1 over Curaçao and 2-1 over CIV, but the 1-2 loss to Ecuador in MD3 exposed defensive gaps.",
            "Paraguay (D3, 4 pts) advanced as a best 3rd on GD tiebreak — one of 8 best 3rds.",
            "Germany crashed out in the group at the last three WCs (2018, 2022) — the knockout redemption arc is real. Müller (35) is on a farewell tour.",
            "Gillette (Boston) at 3:30 PM late-June = 90°F. How long can GER's high press hold up?",
            "Paraguay's identity is physical, compact, counter-attacking — the biggest style contrast of the R32.",
        ],
        "key_players_zh": [
            "贾马尔·穆西亚拉 #10（德国中场，拜仁慕尼黑，2024 德国足球先生）",
            "弗洛里安·维尔茨 #17（德国中场，勒沃库森，欧冠 2024 核心）",
            "托马斯·穆勒 #13（德国老将，35 岁，本届告别赛）",
            "米格尔·阿尔斯 #10（巴拉圭中场，巴西国际）"
        ],
        "key_players_en": [
            "Jamal Musiala #10 (Germany midfielder, Bayern Munich, 2024 Germany FOY)",
            "Florian Wirtz #17 (Germany midfielder, Leverkusen, UCL 2024 core)",
            "Thomas Müller #13 (Germany veteran, 35, farewell WC)",
            "Miguel Almirón #10 (Paraguay midfielder, Internacional)",
        ],
        "news_focus_zh": "穆勒本届若登场将追平马特乌斯 25 场世界杯出场纪录——35 岁老兵的最后一战",
        "news_focus_en": "Müller can match Matthäus's 25-game WC appearance record — last dance for the 35-year-old",
        "record_potential_zh": [
            "穆勒若登场追平马特乌斯 25 场世界杯出场纪录",
            "德国若晋级将终结连续 3 届小组赛出局的尴尬",
            "巴拉圭若晋级将是 2010 年后首次 16 强——16 年等一回"
        ],
        "record_potential_en": [
            "A Müller appearance ties Matthäus's 25-game WC appearance record.",
            "A GER R16 ends a 3-tournament group-stage exit streak.",
            "A PAR R16 would be their first since 2010 — a 16-year wait.",
        ],
        "manual_author": "claude",
    },

    # ── 760488 — Mon 6/29 8:00 PM — NED vs MAR (F1 vs C2) at Estadio BBVA ──
    "760488": {
        "headline_zh": "荷兰 vs 摩洛哥——C 组突围者蒙特雷对决",
        "headline_en": "Netherlands vs Morocco — C survivors in Monterrey",
        "watch_for_zh": [
            "荷兰（F 组第一 7 分）本届小组赛不败（2-2 日本、5-1 瑞典、4-1 突尼斯），范戴克领衔的防线只丢 4 球",
            "摩洛哥（C 组第二 7 分）凭借净胜球压过巴西，1-1 巴西、4-2 海地、1-0 苏格兰——连续 2 届世界杯小组出线",
            "Estadio BBVA（蒙特雷）海拔 540 米，是本届海拔最高的主办城市之一——对北欧球队不友好",
            "摩洛哥 2022 卡塔尔世界杯打入 4 强，本届目标是追平——巴黎双闸阿什拉夫 + 马兹拉维是核心",
            "荷兰主帅科曼本届主打 4-3-3，加克波（利物浦）+ 德佩（马竞）的前场组合经验丰富"
        ],
        "watch_for_en": [
            "Netherlands (F1, 7 pts) are unbeaten this WC (2-2 JPN, 5-1 SWE, 4-1 TUN); Van Dijk anchors a back line conceding just 4.",
            "Morocco (C2, 7 pts) advanced on GD tiebreak over Brazil, going 1-1 BRA / 4-2 HAI / 1-0 SCO — R16 at 2 straight WCs.",
            "Estadio BBVA sits at 540m — the highest host venue in the US — and is rough on Nordic sides.",
            "Morocco made the 2022 SF — PSG's Achraf Hakimi + Man Utd's Mazraoui anchor the most decorated African back line in WC history.",
            "Netherlands under Koeman play 4-3-3; Gakpo (Liverpool) + Depay (Atlético) lead a deep front line.",
        ],
        "key_players_zh": [
            "维吉尔·范戴克 #4（荷兰队长，利物浦中卫）",
            "科迪·加克波 #11（荷兰边锋，利物浦）",
            "阿什拉夫·哈基米 #2（摩洛哥边后卫，巴黎圣日耳曼）",
            "努赛尔·马兹拉维 #3（摩洛哥边后卫，曼彻斯特联）"
        ],
        "key_players_en": [
            "Virgil van Dijk #4 (Netherlands captain, Liverpool CB)",
            "Cody Gakpo #11 (Netherlands winger, Liverpool)",
            "Achraf Hakimi #2 (Morocco RB, Paris Saint-Germain)",
            "Noussair Mazraoui #3 (Morocco LB, Manchester United)",
        ],
        "news_focus_zh": "摩洛哥 2022 打入 4 强，本届目标是追平——非洲球队连续 2 届进 8 强将是历史性时刻",
        "news_focus_en": "Morocco made the 2022 SF — back-to-back African QF appearances would be historic",
        "record_potential_zh": [
            "摩洛哥若晋级将是连续 2 届世界杯 8 强——非洲纪录",
            "荷兰若晋级将是连续 2 届世界杯 8 强",
            "范戴克本届若零封对手将追平荷兰队史单届 2 个零封的纪录"
        ],
        "record_potential_en": [
            "A MAR QF would be back-to-back African QFs at a WC — a continental first.",
            "A NED QF would be their 2nd straight — under Koeman's revival.",
            "A Van Dijk clean sheet would tie NED's single-WC defensive record.",
        ],
        "manual_author": "claude",
    },

    # ── 760490 — Tue 6/30 12:00 PM — CIV vs NOR (E2 vs I2) at AT&T Stadium ──
    "760490": {
        "headline_zh": "哈兰德首次淘汰赛登场",
        "headline_en": "Haaland's WC knockout debut",
        "watch_for_zh": [
            "科特迪瓦（E 组第二 6 分）本届小组赛 1-0 厄瓜多尔、1-2 德国、2-0 库拉索——防守端只丢 3 球",
            "挪威（I 组第二 6 分）2002 后首次重返世界杯，本届 4-1 伊拉克、3-2 塞内加尔、1-4 法国",
            "哈兰德（曼城）本届小组赛 3 球领跑射手榜，是本届金靴头号热门——他的第一次世界杯淘汰赛",
            "AT&T 体育场（达拉斯）有可伸缩屋顶，室内 21°C——6/30 12 点是当日最佳观赛条件之一",
            "科特迪瓦 2023 非洲杯冠军身份 + 挪威北欧硬朗风格，是本届最直白的\"身体足球\"对决"
        ],
        "watch_for_en": [
            "Ivory Coast (E2, 6 pts) went 1-0 ECU / 1-2 GER / 2-0 CUW — only 3 goals conceded all group stage.",
            "Norway (I2, 6 pts) are back at a WC after 24 years; went 4-1 IRQ / 3-2 SEN / 1-4 FRA — competitive against top sides.",
            "Erling Haaland (Man City) leads the Golden Boot race with 3 group goals — his first-ever WC knockout game.",
            "AT&T Stadium (Dallas) has a retractable roof and 71°F climate control — the most pleasant noon kickoff on the slate.",
            "Ivory Coast (2023 AFCON champs) vs Norway — the most straightforward physical football clash of the R32.",
        ],
        "key_players_zh": [
            "埃尔林·哈兰德 #9（挪威前锋，曼城，25 岁）",
            "马丁·厄德高 #10（挪威中场，阿森纳队长）",
            "塞库·福法纳 #6（科特迪瓦中场，雷恩 / AC 米兰）",
            "弗兰克·凯西 #4（科特迪瓦中场，沙特联赛 / 2023 非洲杯最佳球员）"
        ],
        "key_players_en": [
            "Erling Haaland #9 (Norway striker, Man City, 25)",
            "Martin Ødegaard #10 (Norway midfielder, Arsenal captain)",
            "Seko Fofana #6 (Ivory Coast midfielder, Rennes / AC Milan)",
            "Franck Kessié #4 (Ivory Coast midfielder, Saudi Pro League / AFCON 2023 Best Player)",
        ],
        "news_focus_zh": "哈兰德本届已 3 球——挪威队史单届世界杯进球纪录正是 3 球（1958 Hallvar Thoresen），他再进 1 球即破纪录",
        "news_focus_en": "Haaland's 3 goals already equal NOR's all-time single-WC record — one more and he owns it outright",
        "record_potential_zh": [
            "哈兰德 1 球即破挪威队史单届世界杯进球纪录",
            "挪威若晋级将是 1998 年后首次 16 强——28 年等一回",
            "科特迪瓦若晋级将是 2014 年后首次 16 强——12 年等一回"
        ],
        "record_potential_en": [
            "One Haaland goal breaks NOR's all-time single-WC scoring record.",
            "A NOR R16 would be their first since 1998 — a 28-year wait.",
            "A CIV R16 would be their first since 2014 — a 12-year wait.",
        ],
        "manual_author": "claude",
    },

    # ── 760492 — Tue 6/30 4:00 PM — FRA vs SWE (I1 vs F3rd) at MetLife Stadium ──
    "760492": {
        "headline_zh": "法国 vs 瑞典——死亡半区预演",
        "headline_en": "France vs Sweden — death-bracket preview",
        "watch_for_zh": [
            "法国（I 组头名 9 分）本届 3 战全胜（3-1 塞内加尔、3-0 伊拉克、4-1 挪威），进球数本届最多",
            "瑞典（F 组第三 4 分）凭借净胜球晋级，5-1 突尼斯是本届最大冷门之一，1-5 负荷兰暴露后防不稳",
            "MetLife 体育场（东卢瑟福）8 万人容量，是 2026 世界杯决赛场地——淘汰赛首登气氛最浓",
            "姆巴佩（皇马）本届已 3 球 2 助，登贝莱（巴黎）边路锐利——法国前场四人组世界顶级",
            "瑞典 1958 本土世界杯亚军是历史最佳，1994 季军后一直在世界杯边缘——本届若爆冷将震动足坛"
        ],
        "watch_for_en": [
            "France (I1, 9 pts) went 3-for-3 in the group (3-1 SEN, 3-0 IRQ, 4-1 NOR) — most goals of any side.",
            "Sweden (F3, 4 pts) advanced on GD; the 5-1 over Tunisia was an MD1 stunner but 1-5 vs Netherlands exposed defensive fragility.",
            "MetLife (East Rutherford) holds 80,000 and is the 2026 WC final venue — the loudest R32 atmosphere on the slate.",
            "Mbappé (Real Madrid) has 3G 2A; Dembélé (PSG) leads the line — France's front four is the world's deepest.",
            "Sweden's 1958 WC final is still their peak; an upset here would be the biggest story of the R32.",
        ],
        "key_players_zh": [
            "基利安·姆巴佩 #10（法国队长，皇家马德里前锋）",
            "奥斯曼·登贝莱 #11（法国边锋，巴黎圣日耳曼）",
            "亚历山大·伊萨克 #11（瑞典前锋，纽卡斯尔）",
            "罗宾·奥尔森 #1（瑞典门将）"
        ],
        "key_players_en": [
            "Kylian Mbappé #10 (France captain, Real Madrid striker)",
            "Ousmane Dembélé #11 (France winger, Paris Saint-Germain)",
            "Alexander Isak #11 (Sweden striker, Newcastle United)",
            "Robin Olsen #1 (Sweden goalkeeper, Malmö FF loan from Aston Villa)",
        ],
        "news_focus_zh": "法国本届是夺标头号热门，9 分全胜晋级——德尚的目标是追平巴西意大利的 4 次夺冠纪录",
        "news_focus_en": "France are the title favorites — 9 pts and the deepest squad; Deschamps chases a 3rd WC title to match Zagallo/Scarboni",
        "record_potential_zh": [
            "姆巴佩若再进 1 球将追平齐达内 14 球的法国队史世界杯进球纪录",
            "法国若夺冠将成为继巴西、意大利之后第 3 支 4 次捧杯的球队",
            "瑞典若晋级将是 2002 年后首次 16 强——24 年等一回"
        ],
        "record_potential_en": [
            "One more Mbappé goal ties Zidane's 14 — France's all-time WC scoring record.",
            "A FRA title would make them the 3rd 4× WC champion (after Brazil and Italy).",
            "A SWE R16 would be their first since 2002 — a 24-year wait.",
        ],
        "manual_author": "claude",
    },

    # ── 760491 — Tue 6/30 9:00 PM — MEX vs ECU (A1 vs E3rd) at Estadio Banorte ──
    "760491": {
        "headline_zh": "墨西哥城主场——东道主 40 年等待",
        "headline_en": "Mexico City homecoming — co-host's 40-year wait",
        "watch_for_zh": [
            "墨西哥（A 组头名 9 分）本届 3 战全胜（2-0 南非、1-0 韩国、3-0 捷克），本土作战状态极佳",
            "厄瓜多尔（E 组第三 4 分）2-1 爆冷击败德国是本届最大冷门，靠身体对抗和定位球得分",
            "Estadio Banorte（墨西哥城）海拔 2,240 米，是世界杯最高海拔主办地——厄瓜多尔（基多 2,850m）反而占优",
            "墨西哥上一场世界杯淘汰赛胜利要追溯到 1986 年本土世界杯——40 年的等待",
            "墨西哥城的 80,000 主场球迷将是本届最具压迫感的主场氛围之一"
        ],
        "watch_for_en": [
            "Mexico (A1, 9 pts) went 3-for-3 (2-0 RSA, 1-0 KOR, 3-0 CZE) — the co-host is peaking at the right time.",
            "Ecuador (E3, 4 pts) beat Germany 2-1 in MD3 — the upset of the tournament. Their identity is physical and direct.",
            "Estadio Banorte sits at 2,240m — the highest WC venue on the planet. Ecuador (Quito-based at 2,850m) actually acclimates BETTER than Mexico.",
            "Mexico's last WC knockout WIN was in 1986 (the last time they hosted) — a 40-year wait ends here.",
            "80,000 home fans in CDMX will produce one of the loudest atmospheres of the tournament.",
        ],
        "key_players_zh": [
            "劳尔·希门尼斯 #9（墨西哥队长，富勒姆前锋）",
            "埃德森·阿尔瓦雷斯 #4（墨西哥中场，西汉姆联）",
            "吉列尔莫·奥乔亚 #13（墨西哥老门将，40 岁，本届告别赛）",
            "恩纳·瓦伦西亚 #13（厄瓜多尔老前锋，费内巴切，36 岁）"
        ],
        "key_players_en": [
            "Raúl Jiménez #9 (Mexico captain, Fulham striker)",
            "Edson Álvarez #4 (Mexico midfielder, West Ham United)",
            "Guillermo Ochoa #13 (Mexico veteran GK, 40, farewell WC)",
            "Enner Valencia #13 (Ecuador veteran striker, Fenerbahçe, 36)",
        ],
        "news_focus_zh": "奥乔亚本届是第 5 次参加世界杯——追平马特乌斯、安东尼奥·卡巴哈尔的 5 届纪录",
        "news_focus_en": "Ochoa is at his 5th WC — tying Matthäus and Antonio Carbajal's record",
        "record_potential_zh": [
            "墨西哥若晋级将是 1986 年后首次 16 强——40 年等一回（同时代所有墨西哥球员都没见过）",
            "奥乔亚本届若登场将追平 5 届世界杯出场纪录",
            "厄瓜多尔若晋级将是 2006 年后首次 16 强——20 年等一回"
        ],
        "record_potential_en": [
            "A MEX R16 would be their first since 1986 — a 40-year wait that no current Mexican player has lived through.",
            "An Ochoa appearance ties the all-time 5-WC appearance record.",
            "An ECU R16 would be their first since 2006 — a 20-year wait.",
        ],
        "manual_author": "claude",
    },

    # ── 760495 — Wed 7/1 11:00 AM — ENG vs COD (L1 vs K3rd) at Mercedes-Benz Stadium ──
    "760495": {
        "headline_zh": "英格兰登场，亚特兰大 11 点开球",
        "headline_en": "England in Atlanta's 11AM heat",
        "watch_for_zh": [
            "英格兰（L 组头名 7 分）本届 4-2 克罗地亚、0-0 加纳、2-0 巴拿马——前场锐利但中场控制不稳",
            "刚果（金）（K 组第三 4 分）1-1 葡萄牙、0-1 哥伦比亚、3-1 乌兹别克斯坦——防守反击 + 定位球",
            "Mercedes-Benz 体育场（亚特兰大）有可伸缩屋顶，11 点开球时仍闷热——英格兰快节奏可能下半场失温",
            "英格兰 2018 年打入 4 强、2020 欧洲杯亚军、2024 欧洲杯亚军——1966 年后再未夺冠的尴尬仍在",
            "贝林厄姆（皇马）和萨卡（阿森纳）是前场最锐利的两人，凯恩（拜仁）队长箭头"
        ],
        "watch_for_en": [
            "England (L1, 7 pts) went 4-2 CRO / 0-0 GHA / 2-0 PAN — attack sharp, midfield control patchy.",
            "DR Congo (K3, 4 pts) went 1-1 POR / 0-1 COL / 3-1 UZB — counter-attack + set pieces is their identity.",
            "Mercedes-Benz (Atlanta) has a retractable roof, but 11AM kickoff is still humid — ENG's high tempo may fade in the 2nd half.",
            "England have made the 2018 SF, Euro 2020 final, Euro 2024 final — but the 1966 drought is still THE story.",
            "Bellingham (Real Madrid) and Saka (Arsenal) lead the front line; Kane (Bayern) is the captain-striker.",
        ],
        "key_players_zh": [
            "裘德·贝林厄姆 #10（英格兰中场，皇家马德里）",
            "布卡约·萨卡 #7（阿森纳边锋）",
            "哈里·凯恩 #9（队长，拜仁慕尼黑前锋）",
            "塞萨尔·巴坎布 #17（刚果（金）前锋，费内巴切）"
        ],
        "key_players_en": [
            "Jude Bellingham #10 (England midfielder, Real Madrid)",
            "Bukayo Saka #7 (Arsenal winger)",
            "Harry Kane #9 (captain, Bayern Munich striker)",
            "Cédric Bakambu #17 (DR Congo striker, Fenerbahçe)",
        ],
        "news_focus_zh": "图赫尔 2025 年初接手英格兰，3-4-2-1 阵型主打反击——淘汰赛会切换到 4-2-3-1 加强控制",
        "news_focus_en": "Tuchel took over in early 2025; 3-4-2-1 in groups, but expect 4-2-3-1 for more control in knockout",
        "record_potential_zh": [
            "凯恩若再进 2 球将追平鲁尼 13 球的英格兰队史纪录",
            "英格兰若打入 8 强将是连续 3 届大赛 8 强（2018 4 强、2022 8 强、2026 ?）",
            "刚果（金）若晋级将是 1990 年后首次 16 强——36 年等一回"
        ],
        "record_potential_en": [
            "Two more Kane goals ties Rooney's 13 — England's all-time WC scoring record.",
            "An ENG QF would extend a 3-tournament major-tournament knockout streak (2018 SF, 2022 QF, 2026 ?).",
            "A COD R16 would be their first since 1990 — a 36-year wait.",
        ],
        "manual_author": "claude",
    },

    # ── 760493 — Wed 7/1 3:00 PM — BEL vs SEN (G1 vs I3rd) at Lumen Field ──
    "760493": {
        "headline_zh": "比利时黄金一代末班车",
        "headline_en": "Belgium's golden generation finale?",
        "watch_for_zh": [
            "比利时（G 组头名 5 分）本届 3 场全平（1-1 伊朗、0-0 新西兰、1-1 埃及）——净胜球压过埃及晋级",
            "塞内加尔（I 组第三 3 分）1-3 法国、2-3 挪威、5-0 伊拉克——靠末轮 5-0 大胜逆袭晋级",
            "Lumen Field（西雅图）下午 3 点，气温通常 22-25°C——本届最舒适的 R32 比赛条件之一",
            "德布劳内（曼城 35 岁）、卢卡库（那不勒斯 33 岁）——黄金一代的最后一次世界杯",
            "塞内加尔 2002 年首次参赛就打入 8 强 + 2022 年打入 16 强——非洲球队的实力派"
        ],
        "watch_for_en": [
            "Belgium (G1, 5 pts) drew all three group games (1-1 IRN, 0-0 NZL, 1-1 EGY) — advanced on GD tiebreak over Egypt.",
            "Senegal (I3, 3 pts) went 1-3 FRA / 2-3 NOR / 5-0 IRQ — a 5-0 finale pulled them into the R32 as a best 3rd.",
            "Lumen Field (Seattle) at 3PM = 73-77°F — the most pleasant R32 kickoff weather on the slate.",
            "De Bruyne (Man City, 35) and Lukaku (Napoli, 33) — the golden generation's last WC together.",
            "Senegal made the 2002 QF and 2022 R16 — one of Africa's most consistent big-tournament sides.",
        ],
        "key_players_zh": [
            "凯文·德布劳内 #7（比利时中场，曼城，35 岁）",
            "罗梅卢·卢卡库 #9（比利时前锋，那不勒斯，33 岁）",
            "萨迪奥·马内 #10（塞内加尔前锋，利雅得胜利）",
            "帕佩·萨尔 #19（塞内加尔中场，热刺）"
        ],
        "key_players_en": [
            "Kevin De Bruyne #7 (Belgium midfielder, Man City, 35)",
            "Romelu Lukaku #9 (Belgium striker, Napoli, 33)",
            "Sadio Mané #10 (Senegal striker, Al-Nassr / former Liverpool/Bayern)",
            "Pape Matar Sarr #19 (Senegal midfielder, Tottenham)",
        ],
        "news_focus_zh": "比利时黄金一代的最后一届世界杯——德布劳内 35 岁、卢卡库 33 岁，本届出局就彻底告别",
        "news_focus_en": "Belgium's golden generation's last WC — De Bruyne (35), Lukaku (33); an exit here ends an era",
        "record_potential_zh": [
            "比利时若晋级将是 2018 年后首次 16 强——8 年等一回（2018 季军、2022 小组出局、2026 ?）",
            "塞内加尔若晋级将是连续 2 届 16 强——非洲纪录之一",
            "卢卡库本届若进 3 球将追平 5 球的比利时世界杯队史进球纪录"
        ],
        "record_potential_en": [
            "A BEL R16 would be their first since 2018 — an 8-year wait.",
            "A SEN R16 would be their 2nd straight — joining Morocco as the only African back-to-back R16 sides.",
            "Three Lukaku goals ties Belgium's all-time single-WC scoring record (5).",
        ],
        "manual_author": "claude",
    },

    # ── 760494 — Wed 7/1 7:00 PM — USA vs BIH (D1 vs B3rd) at Levi's Stadium ──
    "760494": {
        "headline_zh": "美国 vs 波黑——东道主淘汰赛首战",
        "headline_en": "USA's first knockout game",
        "watch_for_zh": [
            "美国（D 组头名 6 分）本届 4-1 巴拉圭、2-0 澳大利亚、2-3 土耳其——前场锐利但末轮输给土耳其暴露防线问题",
            "波黑（B 组第三 4 分）首次打入世界杯 16 强，1-1 加拿大、1-4 瑞士、3-1 卡塔尔——靠末轮大胜卡塔尔逆袭晋级",
            "Levi's 体育场（圣克拉拉）是 NFL 49 人队主场——美式橄榄球的传统地盘，球迷氛围是足球+橄榄球混合",
            "美国 2002 年后从未打入 8 强（2014 16 强、2022 16 强），本届打破魔咒是东道主最大叙事",
            "波黑头号球星哲科（40 岁，国米老将）本届告别赛——本届若登场将是波黑队史世界杯出场最多球员"
        ],
        "watch_for_en": [
            "USA (D1, 6 pts) went 4-1 PAR / 2-0 AUS / 2-3 TUR — front line sharp but the MD3 loss to Türkiye exposed defensive gaps.",
            "Bosnia (B3, 4 pts) are at their first-ever R32; went 1-1 CAN / 1-4 SUI / 3-1 QAT — sealed the R32 spot with the MD3 win.",
            "Levi's Stadium (Santa Clara) is the NFL 49ers' home — the Bay Area crowd will mix football and soccer fandom.",
            "USA haven't reached the QF since 2002 (2014 R16, 2022 R16) — ending the drought is the co-host's biggest narrative.",
            "Edin Džeko (Inter Milan, 40) is on a farewell tour — a R32 appearance would tie BIH's all-time WC appearance record.",
        ],
        "key_players_zh": [
            "克里斯蒂安·普利西奇 #10（美国队长，AC 米兰）",
            "蒂莫西·维阿 #9（尤文图斯前锋）",
            "尤努斯·穆萨 #21（美国中场，AC 米兰）",
            "埃丁·哲科 #11（波黑老将前锋，国际米兰，40 岁）"
        ],
        "key_players_en": [
            "Christian Pulisic #10 (USA captain, AC Milan)",
            "Timothy Weah #9 (Juventus striker)",
            "Yunus Musah #21 (USA midfielder, AC Milan)",
            "Edin Džeko #11 (Bosnia veteran striker, Inter Milan, 40)",
        ],
        "news_focus_zh": "美国队本届头号话题是\"打入 8 强\"——小组赛 2 胜已超 2022 全程战绩",
        "news_focus_en": "USA's #1 storyline is \"reach the QF\" — two group wins already exceed their entire 2022 output",
        "record_potential_zh": [
            "美国若晋级 8 强将是 2002 年后首次——24 年等一回",
            "波黑若晋级将是队史首次 16 强",
            "哲科若登场将追平波黑队史世界杯出场纪录（4 场）"
        ],
        "record_potential_en": [
            "A USA QF would be their first in 24 years (since 2002).",
            "A BIH R16 would be their first-ever at a WC.",
            "A Džeko appearance would tie BIH's all-time WC appearance record (4).",
        ],
        "manual_author": "claude",
    },

    # ── 760497 — Thu 7/2 2:00 PM — ESP vs AUT (H1 vs J2) at SoFi Stadium ──
    "760497": {
        "headline_zh": "西班牙 vs 奥地利，SoFi 大场面",
        "headline_en": "Spain meets Austria in LA",
        "watch_for_zh": [
            "西班牙（H 组头名 7 分）本届 0-0 佛得角、4-0 沙特、1-0 乌拉圭——防线仅丢 0 球，全队最佳",
            "奥地利（J 组第二 4 分）3-1 约旦、0-2 阿根廷、3-3 阿尔及利亚——靠末轮逼平阿尔及利亚保第二",
            "SoFi 第二场 R32——同地两场淘汰赛是本届首创（同 6/28 揭幕战也在这里）",
            "亚马尔（巴萨 17 岁）+ 尼科·威廉姆斯（毕尔巴鄂）是西班牙前场最锐利的两个年轻边锋",
            "奥地利头号球星阿拉巴（皇马 32 岁）本届告别赛——队史最伟大球员的最后一届"
        ],
        "watch_for_en": [
            "Spain (H1, 7 pts) went 0-0 CPV / 4-0 KSA / 1-0 URU — the only side yet to concede (0 GA).",
            "Austria (J2, 4 pts) went 3-1 JOR / 0-2 ARG / 3-3 ALG — sealed R32 with the MD3 draw.",
            "SoFi's second R32 of the tournament — back-to-back knockouts at the same venue is a 2026 first.",
            "Yamal (Barcelona, 17) + Nico Williams (Athletic Bilbao) are Spain's sharpest young wingers.",
            "David Alaba (Real Madrid, 34) is on a farewell tour — Austria's greatest-ever player, last WC.",
        ],
        "key_players_zh": [
            "拉明·亚马尔 #19（西班牙边锋，巴塞罗那，18 岁）",
            "尼科·威廉姆斯 #11（西班牙边锋，毕尔巴鄂竞技）",
            "罗德里 #16（西班牙中场，曼城，2024 金球奖）",
            "大卫·阿拉巴 #8（奥地利队长，皇家马德里，34 岁）"
        ],
        "key_players_en": [
            "Lamine Yamal #19 (Spain winger, Barcelona, age 18)",
            "Nico Williams #11 (Spain winger, Athletic Bilbao)",
            "Rodri #16 (Spain midfielder, Man City, 2024 Ballon d'Or)",
            "David Alaba #8 (Austria captain, Real Madrid)",
        ],
        "news_focus_zh": "亚马尔本届已 1 球 2 助——若延续将是 2006 年后最年轻的世界杯淘汰赛进球者",
        "news_focus_en": "Yamal already has 1G 2A in MD1 — the youngest WC knockout goalscorer since 2006 if he continues",
        "record_potential_zh": [
            "西班牙若晋级 8 强将是连续 4 届世界杯 8 强（2010、2018、2022、2026）",
            "奥地利若晋级将是 1954 年后首次 16 强——72 年等一回",
            "亚马尔若再进 1 球将成为本届最年轻的进球者"
        ],
        "record_potential_en": [
            "An ESP QF would be their 4th straight — a Spain record.",
            "An AUT R16 would be their first since 1954 — a 72-year wait.",
            "A Yamal goal would make him the youngest scorer at this WC.",
        ],
        "manual_author": "claude",
    },

    # ── 760496 — Thu 7/2 6:00 PM — POR vs CRO (K2 vs L2) at BMO Field ──
    "760496": {
        "headline_zh": "C 罗 vs 莫德里奇——传奇对决",
        "headline_en": "Ronaldo vs Modrić — legends' last dance",
        "watch_for_zh": [
            "葡萄牙（K 组第二 5 分）本届 1-1 刚果、5-0 乌兹别克、0-0 哥伦比亚——C 罗本届首轮 0 球状态低迷",
            "克罗地亚（L 组第二 6 分）2-4 英格兰、2-1 加纳、0-0 巴拿马——莫德里奇 40 岁仍是中场节拍器",
            "BMO Field（多伦多）是本届世界杯唯一加拿大主办城市——草地条件偏冷凉，6 月初体感 18-22°C",
            "C 罗（41 岁，利雅得胜利）vs 莫德里奇（40 岁，2024 离开皇马）——两位金球奖得主的告别赛",
            "C 罗本届若登场将追平自己保持的世界杯 22 场出场纪录；再进 1 球追平 5 球的世界杯进球数"
        ],
        "watch_for_en": [
            "Portugal (K2, 5 pts) went 1-1 COD / 5-0 UZB / 0-0 COL — Ronaldo went goalless in MD1.",
            "Croatia (L2, 6 pts) went 2-4 ENG / 2-1 GHA / 0-0 PAN — Modrić (40) is still the metronome.",
            "BMO Field (Toronto) is the only Canadian host venue for the WC — cooler grass conditions than US/MX.",
            "Ronaldo (41, Al-Nassr) vs Modrić (40, ex-Real Madrid) — two Ballon d'Or winners, both at their last WC.",
            "Ronaldo's R32 appearance would tie his own WC appearance record (22); one more goal ties the all-time WC scoring record (5).",
        ],
        "key_players_zh": [
            "克里斯蒂亚诺·罗纳尔多 #7（葡萄牙前锋，41 岁，利雅得胜利）",
            "布鲁诺·费尔南德斯 #8（葡萄牙中场，曼联）",
            "卢卡·莫德里奇 #10（克罗地亚队长，39 岁，皇家马德里）",
            "伊万·佩里西奇 #4（克罗地亚边锋，28 届世界杯老臣）"
        ],
        "key_players_en": [
            "Cristiano Ronaldo #7 (Portugal striker, age 41, Al-Nassr)",
            "Bruno Fernandes #8 (Portugal midfielder, Manchester United)",
            "Luka Modrić #10 (Croatia captain, age 39, Real Madrid)",
            "Ivan Perišić #4 (Croatia winger, veteran of 4 WCs)",
        ],
        "news_focus_zh": "C 罗本届是他第 6 届世界杯（创纪录）——每场比赛都可能是告别",
        "news_focus_en": "Ronaldo's 6th WC (record) — every match is potentially a farewell",
        "record_potential_zh": [
            "C 罗若登场将成为世界杯历史出场最多球员（追平 22 场）",
            "莫德里奇若登场将成为世界杯历史出场最多中场球员（追平 19 场）",
            "C 罗若再进 1 球将追平克洛泽的世界杯历史进球纪录（16 球）"
        ],
        "record_potential_en": [
            "A Ronaldo appearance ties the all-time WC appearances record (22).",
            "A Modrić appearance ties the all-time WC midfield appearances record (19).",
            "One more Ronaldo goal ties Klose's all-time WC scoring record (16).",
        ],
        "manual_author": "claude",
    },

    # ── 760498 — Thu 7/2 10:00 PM — SUI vs ALG (B1 vs J3rd) at BC Place ──
    "760498": {
        "headline_zh": "瑞士 vs 阿尔及利亚——温哥华深夜战",
        "headline_en": "Switzerland vs Algeria — late-night in Vancouver",
        "watch_for_zh": [
            "瑞士（B 组头名 7 分）本届 1-1 卡塔尔、4-1 波黑、2-1 加拿大——末轮 2-1 力克加拿大证明硬仗能力",
            "阿尔及利亚（J 组第三 4 分）0-3 阿根廷、1-2 约旦、3-3 奥地利——防守端丢 8 球是隐患",
            "BC Place（温哥华）7/2 晚上 10 点开球是当日最晚——气温降至 16°C，对客队更友好",
            "瑞士连续 4 届世界杯打入 16 强（2014、2018、2022、2026）——欧洲纪录之一",
            "扎卡（勒沃库森）+ 巴尔加斯（芝加哥火焰）+ 恩博洛（摩纳哥）的中前场组合经验丰富"
        ],
        "watch_for_en": [
            "Switzerland (B1, 7 pts) went 1-1 QAT / 4-1 BIH / 2-1 CAN — the 2-1 over Canada in MD3 proved they can win tight games.",
            "Algeria (J3, 4 pts) went 0-3 ARG / 1-2 JOR / 3-3 ALG — 8 goals conceded is a major defensive concern.",
            "BC Place (Vancouver) at 10PM is the latest kickoff of the day — temps drop to ~60°F, friendlier to visitors.",
            "Switzerland reached the R16 at the last 3 WCs (2014, 2018, 2022) — a European record.",
            "Xhaka (Leverkusen) + Shaqiri (Chicago Fire) + Embolo (Monaco) — experienced midfield/forward core.",
        ],
        "key_players_zh": [
            "格拉尼特·扎卡 #10（瑞士中场，勒沃库森队长）",
            "谢尔丹·沙奇里 #10（瑞士老中场，芝加哥火焰）",
            "布雷尔·恩博洛 #7（瑞士前锋，摩纳哥）",
            "里亚德·马赫雷斯 #10（阿尔及利亚前锋，吉达国民）"
        ],
        "key_players_en": [
            "Granit Xhaka #10 (Switzerland midfielder, Leverkusen captain)",
            "Xherdan Shaqiri #10 (Switzerland veteran midfielder, Chicago Fire)",
            "Breel Embolo #7 (Switzerland striker, AS Monaco)",
            "Riyad Mahrez #10 (Algeria winger, Al-Ahli / former Man City)",
        ],
        "news_focus_zh": "瑞士 7 分晋级是 2026 欧国联 4 强身份 + 世界杯 16 强——连续 4 届大赛都有 16 强以上表现",
        "news_focus_en": "Switzerland's R32 streak of 4 straight WCs is Europe's best — the Yakin era's quiet consistency",
        "record_potential_zh": [
            "瑞士若晋级将是连续 4 届世界杯 16 强——欧洲纪录之一",
            "阿尔及利亚若晋级将是 2014 年后首次 16 强——12 年等一回",
            "扎卡本届若助攻上双将成为瑞士队史单届世界杯助攻纪录保持者"
        ],
        "record_potential_en": [
            "A SUI R16 would extend their streak to 4 straight WCs — a European record.",
            "An ALG R16 would be their first since 2014 — a 12-year wait.",
            "Xhaka with 2+ assists would set SUI's single-WC assist record.",
        ],
        "manual_author": "claude",
    },

    # ── 760499 — Fri 7/3 1:00 PM — AUS vs EGY (D2 vs G2) at AT&T Stadium ──
    "760499": {
        "headline_zh": "萨拉赫 vs 莱基——边锋对决",
        "headline_en": "Salah vs Leckie — the wingers' duel",
        "watch_for_zh": [
            "澳大利亚（D 组第二 4 分）本届 2-0 土耳其、0-2 美国、0-0 巴拉圭——靠身体对抗硬扛了欧洲球队",
            "埃及（G 组第二 5 分）本届 1-1 新西兰、1-1 比利时、1-1 伊朗——3 场全平晋级，是本届最\"平淡\"的晋级者",
            "AT&T 体育场（达拉斯）有可伸缩屋顶，1PM 开球室内 21°C——6 月底达拉斯 38°C 室外的最佳对照",
            "萨拉赫（利物浦 32 岁）+ 马赫穆德·特雷泽盖（雷恩）是埃及前场的核心，但埃及本届进攻乏力（3 球）",
            "澳大利亚首轮 2-0 爆冷击败土耳其是本届最大冷门之一——他们用身体对抗硬扛了欧洲球队"
        ],
        "watch_for_en": [
            "Australia (D2, 4 pts) went 2-0 TUR / 0-2 USA / 0-0 PAR — physical, direct, hard to break down.",
            "Egypt (G2, 5 pts) drew all three group games (1-1 NZL, 1-1 BEL, 1-1 IRN) — the 'quietest' R32 qualifier this tournament.",
            "AT&T's retractable roof keeps it at 70°F indoors — a relief from the 95°F+ Texas summer outside.",
            "Salah (Liverpool, 32) + Trezeguet (Renner / former Aston Villa) lead Egypt, but the team scored just 3 group goals.",
            "AUS's 2-0 over Türkiye was the upset of MD1 — physical, direct, hard to break down.",
        ],
        "key_players_zh": [
            "穆罕默德·萨拉赫 #10（埃及队长，利物浦前锋，34 岁）",
            "马赫穆德·特雷泽盖 #7（埃及边锋，雷恩）",
            "马修·莱基 #11（澳大利亚边锋，墨尔本城）",
            "阿蒂姆·布塔 #9（澳大利亚前锋）"
        ],
        "key_players_en": [
            "Mohamed Salah #10 (Egypt captain, Liverpool striker, 34)",
            "Mahmoud Trezeguet #7 (Egypt winger, Stade Rennais loan from Aston Villa)",
            "Mathew Leckie #11 (Australia winger, Melbourne City)",
            "Awer Mabil #9 (Australia forward)",
        ],
        "news_focus_zh": "萨拉赫本届 0 球——他是金球奖级别的球星，本场必须进球才能带埃及走远",
        "news_focus_en": "Salah is goalless this WC — the Ballon d'Or-caliber star MUST score to drag Egypt forward",
        "record_potential_zh": [
            "澳大利亚若晋级将是 2006 年后首次 16 强——20 年等一回（2006 是队史最佳 16 强）",
            "埃及若晋级将是 2014 年后首次 16 强——12 年等一回",
            "萨拉赫若登场将追平埃及队史世界杯出场纪录"
        ],
        "record_potential_en": [
            "An AUS R16 would be their first since 2006 — a 20-year wait.",
            "An EGY R16 would be their first since 2014 — a 12-year wait.",
            "A Salah appearance ties EGY's all-time WC appearance record.",
        ],
        "manual_author": "claude",
    },

    # ── 760500 — Fri 7/3 5:00 PM — ARG vs CPV (J1 vs H2) at Hard Rock Stadium ──
    "760500": {
        "headline_zh": "梅西迈阿密主场告别？",
        "headline_en": "Messi's Miami homecoming — last WC run?",
        "watch_for_zh": [
            "阿根廷（J 组头名 9 分）本届 3 战全胜（3-0 阿尔及利亚、2-0 奥地利、3-1 约旦）——卫冕冠军状态极佳",
            "佛得角（H 组第二 3 分）本届 0-0 西班牙、0-0 沙特、0-0 乌拉圭——3 场全平，史上最\"闷\"晋级者之一",
            "Hard Rock Stadium（迈阿密花园）是梅西在 MLS 球队（国际迈阿密）的主场——他是迈阿密的国王",
            "阿根廷 2021-2022 连续美洲杯+世界杯，2024 年卫冕美洲杯失败，本届目标卫冕世界杯",
            "38 岁的梅西本届小组赛 1 球 2 助状态极佳——他需要用淘汰赛进球完成告别"
        ],
        "watch_for_en": [
            "Argentina (J1, 9 pts) went 3-for-3 (3-0 ALG, 2-0 AUT, 3-1 JOR) — defending champions in form.",
            "Cape Verde (H2, 3 pts) went 0-0 ESP / 0-0 KSA / 0-0 URU — three goalless draws, the 'dullest' R32 qualifier.",
            "Hard Rock is Messi's Inter Miami home — he IS the king of this city.",
            "ARG won Copa América 2021 + WC 2022 + Copa 2024 — they failed to defend the 2024 Copa; WC 2026 is the next chapter.",
            "Messi (38) had 1G 2A in the group — still the tournament's most decisive player.",
        ],
        "key_players_zh": [
            "里奥·梅西 #10（阿根廷队长，迈阿密国际）",
            "朱利安·阿尔瓦雷斯 #9（马德里竞技前锋）",
            "罗德里戈·德保罗 #7（马德里竞技中场）",
            "罗德里·平托 #7（佛得角中场，葡萄牙体育）"
        ],
        "key_players_en": [
            "Lionel Messi #10 (Argentina captain, Inter Miami)",
            "Julián Álvarez #9 (Atlético Madrid striker)",
            "Rodrigo De Paul #7 (Atlético Madrid midfielder)",
            "Rodrigo Pina #7 (Cape Verde midfielder, Sporting CP)",
        ],
        "news_focus_zh": "梅西 2026 是他第 6 届世界杯（创纪录）——也是他 2022 后首次冲击卫冕",
        "news_focus_en": "Messi's 6th WC (record) — and his first title defense since winning in 2022",
        "record_potential_zh": [
            "梅西本届出场将追平自己保持的世界杯 26 场出场纪录",
            "阿根廷若卫冕将是 1962 年巴西后首支蝉联世界杯的球队——64 年等一回",
            "阿尔瓦雷斯本届若再进 1 球将成为本届最年轻的 4 球球员"
        ],
        "record_potential_en": [
            "Messi's appearance ties his own WC record (26 games).",
            "An ARG repeat would be the first back-to-back WC title since Brazil 1958-1962 — 64 years.",
            "An Álvarez goal would make him the youngest 4-goal scorer at this WC.",
        ],
        "manual_author": "claude",
    },

    # ── 760501 — Fri 7/3 8:30 PM — COL vs GHA (K1 vs L3rd) at GEHA Field ──
    "760501": {
        "headline_zh": "J 罗告别？哥伦比亚 vs 加纳",
        "headline_en": "James's last dance? Colombia vs Ghana",
        "watch_for_zh": [
            "哥伦比亚（K 组头名 7 分）本届 3-1 乌兹别克、1-0 葡萄牙、0-0 葡萄牙——5 队中胜葡萄牙的最大牌队伍",
            "加纳（L 组第三 4 分）本届 1-0 巴拿马、0-0 英格兰、1-2 克罗地亚——靠末轮输给克罗地亚但仍以最佳第三晋级",
            "GEHA Field（堪萨斯城）是 NFL 酋长队主场，8:30PM 体感 30°C——当日最热时段",
            "J 罗（34 岁）本届首轮 1 助——他需要在淘汰赛重新找回 2014 金靴的自己",
            "哥伦比亚 2014 年打入 8 强（最佳战绩），2022 缺席，本届目标重回 8 强"
        ],
        "watch_for_en": [
            "Colombia (K1, 7 pts) went 3-1 UZB / 1-0 POR / 0-0 POR — sealed top of K with the MD2 win over Portugal, then closed with a 0-0 draw in MD3.",
            "Ghana (L3, 4 pts) went 1-0 PAN / 0-0 ENG / 1-2 CRO — lost MD3 to Croatia but advanced as a best 3rd on GD.",
            "GEHA Field (KC) is the NFL Chiefs' home; 8:30 PM = ~86°F, the hottest R32 kickoff of the day.",
            "James Rodríguez (34) had 1 assist in MD1 — he needs the R32 to channel his 2014 Golden Boot form.",
            "COL made the 2014 QF (their best ever); they missed 2022; 2026 is about returning to the QF.",
        ],
        "key_players_zh": [
            "路易斯·迪亚斯 #10（哥伦比亚前锋，利物浦）",
            "J 罗 #11（哥伦比亚中场，皇家马德里旧将，34 岁）",
            "达文森·桑切斯 #2（热刺中卫）",
            "穆罕默德·库杜斯 #19（加纳边锋，热刺）"
        ],
        "key_players_en": [
            "Luis Díaz #10 (Colombia winger, Liverpool)",
            "James Rodríguez #11 (Colombia midfielder, ex-Real Madrid, 34)",
            "Davinson Sánchez #2 (Tottenham CB)",
            "Mohammed Kudus #19 (Ghana winger, Tottenham)",
        ],
        "news_focus_zh": "哥伦比亚本届的口号是\"J 罗的最后一舞\"——34 岁的他已暗示这届是告别",
        "news_focus_en": "Colombia's 2026 storyline is \"James's last dance\" — he's hinted at retirement after this WC",
        "record_potential_zh": [
            "J 罗若再进 2 球将追平 6 球的世界杯单届进球纪录——刷新南美球员纪录",
            "哥伦比亚若晋级 8 强将是 2014 年后首次——12 年等一回",
            "加纳若晋级将是 2010 年后首次 16 强——16 年等一回（2010 打入 8 强是队史最佳）"
        ],
        "record_potential_en": [
            "Two more James goals ties his 6-goal WC record (most for a South American in a single WC).",
            "A COL QF would be their first in 12 years (since 2014).",
            "A GHA R16 would be their first since 2010 — a 16-year wait.",
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
        "\n\n"
        "本届 R32 几大必看：墨西哥城主场回归（40 年来首次淘汰赛胜利）、美国 vs 波黑"
        "（东道主冲击 8 强）、英格兰 vs 刚果（金）（凯恩冲击鲁尼纪录）、"
        "法国 vs 瑞典（死亡半区预演）、C 罗 vs 莫德里奇（金球奖告别战）、"
        "阿根廷 vs 佛得角（梅西迈阿密主场）。"
    )
    round_intro_en = (
        "Group stage done — 32 teams enter single-elimination. This R32 spans 6 days "
        "(Sun 6/28 - Fri 7/3): top 2 of each group plus 8 best 3rd-placers advance, "
        "bracket set by draw. 16 matches across 14 venues in the US/Canada/Mexico — "
        "including three 70,000+ Super Bowl stadiums (SoFi, MetLife, AT&T) and Mexico "
        "City's Estadio Banorte, where a co-host (Mexico) plays its first-ever home "
        "knockout game at a WC."
        "\n\n"
        "Five R32 matches you really can't miss: MEX vs ECU (Mexico's first home "
        "knockout in 40 years), USA vs BIH (co-host's QF push), ENG vs COD "
        "(Kane chases Rooney's record), FRA vs SWE (death-bracket preview), "
        "POR vs CRO (Ronaldo vs Modrić — two Ballon d'Or farewells), and "
        "ARG vs CPV (Messi's Miami homecoming)."
    )

    # Find the R32 round and overwrite its matches.
    r32_round = None
    for r in doc.get("rounds", []):
        if r.get("stage_slug") == "round-of-32":
            r32_round = r
            break
    if r32_round is None:
        # Fall back to v1: doc itself is the round.
        if doc.get("stage_slug") == "round-of-32" or any(
            m.get("stage_slug") == "round-of-32" for m in doc.get("matches", [])
        ):
            r32_round = doc
    if r32_round is None:
        print("err: no R32 round found in weekly-picks.json", file=sys.stderr)
        return 1

    enriched = 0
    for m in r32_round.get("matches", []):
        mid = str(m.get("match_id"))
        a = ANALYSIS.get(mid)
        if not a:
            print(f"warn: no analysis for match {mid}", file=sys.stderr)
            continue
        for k, v in a.items():
            m[k] = v
        enriched += 1

    # Round intros — overwrite with the resolved-bracket version.
    r32_round["round_intro_zh"] = round_intro_zh
    r32_round["round_intro_en"] = round_intro_en
    r32_round["last_manual_update"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    r32_round["manual_count"] = sum(
        1 for m in r32_round.get("matches", [])
        if m.get("headline_zh") or m.get("headline_en")
    )

    # Recompute top-level rollup so the front-end sees the change.
    doc["manual_count"] = sum(
        sum(1 for m in (r.get("matches") or []) if m.get("headline_zh") or m.get("headline_en"))
        for r in doc.get("rounds", [])
    )

    with PATH.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {PATH} ({enriched}/{len(r32_round.get('matches', []))} R32 matches enriched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
