# ai-video-director × Grok Storyboard Prompt

**这是你贴给 Grok(或其他 LLM)的整段文本**。Grok 读完你的故事后,会输出 5 个 JSON 文件。你把每个 JSON 保存到对应路径,ai-video-director 就能用 `video-director import` 把它们变成项目。

---

## 你(Grok)需要做的事

用户会给一段中文故事 text。你的任务是把它拆解成 **5 个 JSON 文件**,每个文件是合法的 JSON。

**不要修改用户的故事情节,不要补写台词,不要简化场景** — 严格按用户给的 text 拆。如果用户 text 里某角色没说某句话,你不要给它补一句。

---

## 必须输出的 5 个 JSON 文件

### 1. `story.json` — 故事元数据(顶层)

```json
{
  "story_id": "<slug, e.g. 'chang_an_xiyang_gu' >",
  "title": "<中文标题>",
  "language": "zh",
  "genre": "<e.g. 古装悬疑 / 都市爱情 / 科幻>",
  "tone": "<e.g. 紧张 / 温馨 / 史诗>",
  "style": "<视觉风格, e.g. '电影感实拍风格, 暖色调' >",
  "target_duration_sec": <整数, 600 = 10 分钟>,
  "character_ids": ["<character_id>", ...],
  "scene_ids": ["<scene_id>", ...]
}
```

### 2. `characters.json` — 所有角色(数组)

```json
[
  {
    "character_id": "<slug, e.g. 'lin_xi' >",
    "name": "<中文角色名>",
    "age": <整数>,
    "gender": "male" | "female" | "other",
    "appearance": "<一段中文外貌描述, 100-200 字>",
    "clothing_default": "<默认服装中文描述>",
    "personality": "<中文性格描述, 50 字以内>",
    "reference_image": "<参考图相对路径, 在 imports/references/<character_id>/hero.png>"
  },
  ...
]
```

**约束**:
- 每个角色**必须有外貌描述**(AI video generation 用)
- 每个角色**必须有 reference_image 路径**(若没有图片,ai-video-director 会用 prompt-only 模式)
- `character_id` slug 必须匹配 `[a-z0-9_]+`
- **不要重复**:同一角色在多幕出现,只列一次

### 3. `scenes.json` — 所有场景(数组)

```json
[
  {
    "scene_id": "<slug, e.g. 'chang_an_city_gate_dusk' >",
    "title": "<中文场景名>",
    "location": "<地点, e.g. 长安城外城门>",
    "time_of_day": "dawn" | "morning" | "noon" | "afternoon" | "dusk" | "night" | "late_night",
    "weather": "<晴 / 雨 / 雪 / 雾 等>",
    "lighting": "<中文光线描述, 50-100 字>",
    "environment": "<中文环境描述, 100-200 字>",
    "character_ids": ["<在此场景出现的角色 character_id>"],
    "duration_sec": <整数, 此幕大概时长>
  },
  ...
]
```

**约束**:
- scene_id slug 必须匹配 `[a-z0-9_]+`
- `character_ids` **必须引用 characters.json 里真实存在的 character_id**(否则 checker 会报错)

### 4. `shots.json` — 所有镜头(数组, 核心)

```json
[
  {
    "shot_id": "<slug, e.g. 'chang_an_city_gate_dusk_shot_001' >",
    "scene_id": "<scene_id, 必须引用 scenes.json 里真实存在的>",
    "shot_index": <此场景内序号, 从 1 开始>,
    "duration_sec": <整数, 5-10 秒最佳, 不要超过 15>,
    "shot_type": "extreme_wide" | "wide" | "medium_wide" | "medium" | "medium_close" | "close_up" | "extreme_close_up",
    "camera": "<中文镜头/焦距描述, e.g. '35mm 中景' >",
    "camera_motion": "static" | "slow_dolly_in" | "slow_dolly_out" | "pan_left" | "pan_right" | "tilt_up" | "tilt_down" | "handheld" | "tracking" | "crane_up" | "crane_down",
    "character_ids": ["<出镜角色 ids>"],
    "action": "<中文动作描述, 50-150 字, 描述角色在做什么>",
    "emotion": "<中文情绪关键词, e.g. '紧张, 决绝' >",
    "environment": "<中文环境补充, 此镜头特定的环境细节, 50-100 字>",
    "lighting": "<中文光线细节, 此镜头特定的光线变化, 50-100 字>",
    "prompt": "<英文 prompt, 详细, 包含所有视觉信息, 200-400 字. 必须是英文, 因为模型是 MiniMax-H3>",
    "negative_prompt": "<英文负面 prompt, e.g. 'blurry, distorted, low quality, watermark, text, modern clothing, anime style, multiple faces'>",
    "start_frame_source": "manual" | "previous_shot",
    "start_frame": "<仅当 start_frame_source='manual' 时填, 参考图相对路径>",
    "previous_shot": "<上一镜头 shot_id, 用于衔接, 通常是数组中前一个 shot>",
    "next_shot": "<下一镜头 shot_id, 通常是数组中后一个 shot>"
  },
  ...
]
```

**约束(很重要)**:
- **每个 shot 必须填 `prompt`**,且必须是英文(因为 video model 是英文训练的)
- **prompt 必须包含**: shot_type + character appearance + action + environment + lighting + camera(基本是 shot 字段的英文综合)
- **shot_id slug 必须匹配 `[a-z0-9_]+`**
- **scene_id, character_ids, previous_shot, next_shot 都必须引用真实存在的 entity**
- **同一 scene 内的 shots 按 shot_index 升序排列**
- **first shot 的 `previous_shot = ""`**(没有上一镜头)
- **last shot 的 `next_shot = ""`**(没有下一镜头)
- **相邻 shot 的 previous_shot / next_shot 必须互相指向**(形成链)
- `start_frame_source: 'previous_shot'` 推荐用于**对话/剧情连续**的镜头;`'manual'` 用于场景转换(开场/切场景)

**shot 总数建议**:
- 10 分钟 = 600 秒, 假设每 shot 7 秒 → **85 个 shot 左右**
- 不要超过 150 个 shot(超出 framework 的并发限制)

### 5. `dialogues.json` — 所有对话(数组, 可选但强烈推荐)

```json
[
  {
    "dialogue_id": "<slug>",
    "shot_id": "<此台词所在的 shot_id>",
    "character_id": "<说话角色 id>",
    "line": "<中文台词, 用户原话, 不要修改>",
    "timing_sec": <此台词在 shot 内的时刻, 0.0 到 shot duration_sec 之间>,
    "emotion": "<说话情绪, e.g. '愤怒' '平静' '颤抖'>",
    "volume": "whisper" | "normal" | "shout"
  },
  ...
]
```

**约束**:
- **每条台词必须对应用户故事 text 里的实际台词**
- **不要补写台词**(用户没写的不要加)
- `shot_id` / `character_id` 必须引用真实存在的
- 每个 shot 可以有 0-N 条 dialogue

---

## 输出顺序与文件边界

**每个 JSON 文件是独立、完整的、合法的 JSON**。

**严禁**:
- ❌ 把多个 JSON 文件塞进一个 markdown 代码块
- ❌ 在 JSON 周围加任何解释性文本(如果必须解释,放在文件外、单独 message)
- ❌ 用 ```json 包装(你的输出就是纯 JSON)
- ❌ 输出超过 5 个 JSON 文件

**正确的输出格式**:
```
[FILE: story.json]
<纯 JSON>

[FILE: characters.json]
<纯 JSON 数组>

[FILE: scenes.json]
<纯 JSON 数组>

[FILE: shots.json]
<纯 JSON 数组>

[FILE: dialogues.json]
<纯 JSON 数组>
```

或者直接每条 message 一个 JSON 文件,每个 message 以 `[FILE: <filename>]` 开头。

---

## 关键规则(checker 会检查这些)

| 规则 | 错误信息 |
|---|---|
| 所有 ID 都是 slug 格式 `[a-z0-9_]+` | `INVALID_SLUG: <id>` |
| `scene_id` / `character_id` / `previous_shot` / `next_shot` 引用真实存在 | `MISSING_REFERENCE: <ref>` |
| 相邻 shot 的 previous_shot/next_shot 互相指向 | `BROKEN_CHAIN: shot_X.next_shot=shot_Y 但 shot_Y.previous_shot != shot_X` |
| shot 总数 ≤ 150 | `TOO_MANY_SHOTS: 151 > 150` |
| 每个 shot 有 `prompt` 且非空 | `EMPTY_PROMPT: <shot_id>` |
| 每个 shot 有 `negative_prompt` | `EMPTY_NEGATIVE_PROMPT: <shot_id>` |
| duration_sec 在 [2, 15] | `BAD_DURATION: <shot_id> duration=X` |
| 同一 scene 的 shot_index 单调递增 | `OUT_OF_ORDER_INDEX: <shot_id>` |
| shot_id 在 shots 数组内唯一 | `DUPLICATE_SHOT_ID: <shot_id>` |
| dialogue 的 shot_id/character_id 引用真实 | `DIALOGUE_BAD_REFERENCE: <id>` |

---

## 用户故事 text 在下面

<USER 把故事 text 粘贴到这里>

---

## 输出前最后检查

在输出 JSON 前,请快速核对:
- [ ] 我输出了 5 个文件(或者 dialogues 空数组可省)
- [ ] 每个文件是纯 JSON(没有 ```json 标记, 没有 surrounding text)
- [ ] 所有 ID 都是 slug 格式
- [ ] 所有 reference(character_id, scene_id, previous_shot, next_shot)都指向真实存在的
- [ ] shot 总数不超过 150
- [ ] 每个 shot 的 prompt 是英文且详细
