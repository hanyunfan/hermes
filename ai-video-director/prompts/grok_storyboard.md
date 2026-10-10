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

**人物名 ↔ ID 对应规则**(Grok 必须遵守,所有角色统一):

从中文名生成 `character_id` slug 的固定规则:

| 中文名(部分)| 拼音(全拼,无音调)| character_id |
|---|---|---|
| 林夕      | linxi        | `lin_xi`     |
| 苏清      | suqing       | `su_qing`    |
| 长安      | changan      | `changan`    |
| 老僧      | laoseng      | `lao_seng`   |
| 王二狗    | wangergou    | `wang_er_gou`|
| 主角(无名) | —           | `hero` 或 `protagonist` |

**生成规则**:
1. 取中文名的**全拼**(不带声调):林夕 → `linxi`,长安 → `changan`
2. 把拼音按**汉字边界**用下划线连接(每个汉字一个音节):
   - 林夕(2 字)→ `lin_xi`
   - 苏清(2 字)→ `su_qing`
   - 王二狗(3 字)→ `wang_er_gou`
3. 全部**小写**,只允许 `[a-z0-9_]`,**禁止**大写、空格、连字符
4. **多人同音不同字** → 加序号:张三 / 张山 都拼 `zhangshan`,改成 `zhang_san` / `zhang_shan`
5. **无明确名字的角色**(只叫"主角"/"老人"/"路人甲")→ 用英文 slug `hero` / `old_man` / `passerby_a`
6. **人物简称**(故事里多次出现"将军"/"公主")→ 用角色定位而不是姓氏:`general` / `princess` / `master`
7. **同一角色在不同幕换称呼**(例:"李公子" vs "李郎中")→ 用**最正式/全的那个**作 character_id,其他称呼放在 `appearance` 或 `personality` 字段里描述

**绝对不要**:
- ❌ 用中文名直接当 id(违反 slug 规则)
- ❌ 加数字后缀除非真有重复(`hero_1`, `hero_2` 不行 — 这是同名 alias)
- ❌ 加版本号或日期后缀

**Story 里的引用一致性**:同一角色的 `name` 在 `characters.json` / `scenes.json` / `shots.json` / `dialogues.json` 全部用同一个值。

```json
[
  {
    "character_id": "lin_xi",
    "name": "林夕",
    "age": 23,
    "gender": "male" | "female" | "other",
    "appearance": "<一段中文外貌描述, 100-200 字>",
    "clothing_default": "<默认服装中文描述>",
    "personality": "<中文性格描述, 50 字以内>",
    "reference_image": "<相对路径: imports/references/<character_id>/hero.<ext> 或 .jpg>"
  },
  ...
]
```

**约束**:
- 每个角色**必须有外貌描述**(AI video generation 用)
- 每个角色**必须有 reference_image 路径**(若没有图片,ai-video-director 会用 prompt-only 模式)
- `character_id` slug 必须匹配 `[a-z0-9_]+`
- **不要重复**:同一角色在多幕出现,只列一次

### Reference picture 路径约定(必读)

ai-video-director 接受两种放参考图的方式 — Grok 必须根据用户**实际**的目录结构输出对应路径。

**方式 A:目录名 = character_id**(推荐,清晰对应)

```
imports/references/lin_xi/hero.jpg
```

对应的 characters.json:

```json
{
  "character_id": "lin_xi",
  "reference_image": "imports/references/lin_xi/hero.jpg"
}
```

**方式 B:数字/通用目录**(用户已经把图放在 `1/` `2/` 等)

```
imports/references/1/hero.jpg
imports/references/2/hero.jpg
```

对应的 characters.json:

```json
[
  {"character_id": "young_woman", "reference_image": "imports/references/1/hero.jpg"},
  {"character_id": "young_man",   "reference_image": "imports/references/2/hero.jpg"}
]
```

**Grok 必须遵守**:
1. **看用户的参考图实际放在哪个目录** — 如果用户的图片在 `references/1/`,Grok 就输出 `references/1/`(不要瞎编一个 `references/young_woman/` 路径,validate-imports 会报 MISSING_REFERENCE_IMAGE)
2. **看文件扩展名** — 如果用户的图片是 `.jpg`,输出 `.jpg`(不要输出 `.png`)
3. **绝不允许**编一个看似合理但用户根本没放图的路径(会导致人物生成时无参考图,产生与设计图完全不符的脸)

### 验证-checker (会检查这些)

| 规则 | 错误信息 |
|---|---|
| `reference_image` 指向的文件存在 | `MISSING_REFERENCE_IMAGE: <path> does not exist` |
| `reference_image` 路径里的目录名 = `character_id` | `REFERENCE_DIR_MISMATCH: character_id='lin_xi' but reference_image lives in references/1/` |

如果 `MISSING_REFERENCE_IMAGE` 报错,**Grok 不要重试同一份输出** — 它必须修改 reference_image 路径(如果用户实际放的目录是 `1/` 就改成 `1/`)。

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

**dialogue(对白)合并到 shots.json**:见下面 `shots.json` 章节里的"重要:对白处理方式"小节。


---

## 重要:对白处理方式(必须遵守)

**每个 shot 的对白信息必须直接写进 shot 字段里**(action / emotion / prompt / camera),**不允许再生成 dialogues.json 文件**。

具体规则:

1. **如果一个 shot 里有对白**(角色说话),在 `action` 字段里明确写出角色说了什么台词,以及说话时的神态/动作:
   ```json
   "action": "林夕蹲在角落,轻声对苏清说: '你听, 外面好像有人。' 说完紧张地看向门口。"
   ```

2. **在 `emotion` 字段里包含情绪关键词**(这会成为 prompt 的 emotion 引导):
   ```json
   "emotion": "紧张, 低声, 警觉"
   ```

3. **在 `prompt` (英文)里包含一段嘴部动作 + 说话状态**:
   ```
   "...Lin Xi crouches in the corner, lips slightly parted as she whispers 'Did you hear that? Someone is outside.', eyes darting toward the door, voice barely audible, breath trembling..."
   ```

4. **不要**输出 dialogues.json 文件。**不要**给 action 字段留空,把所有台词 + 说话动作都写进 shot 自带字段。

**为什么这样?** 视频生成模型 (MiniMaxH3 I2V) 会读取 prompt 里关于嘴部动作 / 说话的描述来生成嘴型动画;同时台词对白作为 metadata 由用户后续添加音频轨道(框架在 assemble 阶段会保留 ComfyUI 生成的 aac 音轨)。

**示例**:用户故事原文 = "林夕说:'你听, 外面好像有人。'" → 对应 shot:

```json
{
  "shot_id": "wooden_room_dawn_shot_003",
  "scene_id": "wooden_room_dawn",
  "shot_index": 3,
  "duration_sec": 8,
  "shot_type": "medium_close",
  "camera": "50mm 中近景",
  "camera_motion": "static",
  "character_ids": ["lin_xi"],
  "action": "林夕蹲在木屋角落, 紧张地看向门口, 同时低声对身后的苏清说:'你听, 外面好像有人。' 她的呼吸变急促, 手指攥紧衣角。",
  "emotion": "紧张, 低声, 警觉, 呼吸急促",
  "environment": "狭小的木屋内部, 晨光从破窗缝隙斜射进来, 照出空气中浮动的尘埃",
  "lighting": "微弱晨光, 暖黄色侧光, 阴影对比强",
  "prompt": "Cinematic medium close-up of Lin Xi, a young East Asian woman in traditional hanfu, crouching in the corner of a small wooden room. Her lips part slightly as she whispers 'Did you hear that? Someone is outside.' in Chinese. Her eyes dart nervously toward the door, breath trembling visibly. Mouth opens subtly for the whispered dialogue, jaw tension visible. Morning light from a broken window cuts across her face. Tight shallow depth of field, dust particles floating in the light beam. Atmospheric, tense, low-volume speaking.",
  "negative_prompt": "blurry, distorted, low quality, watermark, text, modern clothing, anime style, multiple faces, open mouth shouting, exaggerated lip sync",
  "start_frame_source": "previous_shot",
  "previous_shot": "wooden_room_dawn_shot_002",
  "next_shot": "wooden_room_dawn_shot_004"
}
```

**注意**:上面例子里,**中文台词 '你听, 外面好像有人。' 出现在 `action` 字段里**,**英文翻译出现在 `prompt` 字段里**。这种做法让 video model 知道要生成嘴部动作,也让用户后续 review 时知道这段对白属于哪个 shot。

---

## 输出顺序与文件边界

**每个 JSON 文件是独立、完整的、合法的 JSON**。

**严禁**:
- ❌ 把多个 JSON 文件塞进一个 markdown 代码块
- ❌ 在 JSON 周围加任何解释性文本(如果必须解释,放在文件外、单独 message)
- ❌ 用 ```json 包装(你的输出就是纯 JSON)
- ❌ 输出超过 5 个 JSON 文件(实际上现在只需要 4 个,见下)
- ❌ 输出 dialogues.json 文件(台词已合并到 shots.json 字段里)

**正确的输出格式**(4 个文件):
```
[FILE: story.json]
<纯 JSON>

[FILE: characters.json]
<纯 JSON 数组>

[FILE: scenes.json]
<纯 JSON 数组>

[FILE: shots.json]
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
| 包含对白的 shot,`action` 字段里有角色说的中文台词 | `MISSING_DIALOGUE_TEXT: <shot_id>` |

---

## 用户故事 text 在下面

<USER 把故事 text 粘贴到这里>

---

## 输出前最后检查

在输出 JSON 前,请快速核对:
- [ ] 我输出了 4 个文件(没有 dialogues.json)
- [ ] 每个文件是纯 JSON(没有 ```json 标记, 没有 surrounding text)
- [ ] 所有 ID 都是 slug 格式
- [ ] 所有 reference(character_id, scene_id, previous_shot, next_shot)都指向真实存在的
- [ ] shot 总数不超过 150
- [ ] 包含对白的 shot,`action` 字段里有完整中文台词
- [ ] 每个 shot 的 prompt 是英文且详细
