# JSON 文件落盘位置 — Grok 输出后怎么放

Grok(或其他 LLM)按 `prompts/grok_storyboard.md` 输出 5 个 JSON 文件后,你需要把每个文件放到 ai-video-director 项目里的**固定位置**。

## 工作流程

```
1. 你写一段中文故事 text
2. 打开 Grok / 其他 LLM
3. 粘贴 prompts/grok_storyboard.md + 你的故事 text
4. LLM 输出 5 个 JSON 文件(用 [FILE: filename] 分隔)
5. 你把每个 JSON 保存到对应路径
6. 运行: video-director validate-imports <project_id>
7. 全部通过 → video-director build <project_id>  (生成 yaml)
8. video-director validate <project_id>  (交叉验证)
9. video-director generate <project_id> --backend comfyui  (跑视频)
```

## 项目目录结构(Grok 输出应该落在这里)

```
projects/<project_id>/
├── imports/                  ← Grok 输出放这里
│   ├── story.json
│   ├── characters.json
│   ├── scenes.json
│   ├── shots.json             ← 对白/台词已合并进 shot 的 action/emotion/prompt 字段
│   └── references/            ← 参考图(可选,但强烈推荐)
│       ├── lin_xi/
│       │   └── hero.png
│       ├── old_monk/
│       │   └── hero.png
│       └── ...
├── shots/                    ← framework 自动生成的(由 imports/ build 出来)
├── characters/
├── scenes/
├── story.yaml
├── project.yaml
├── output/clips/
└── state/
```

## 每个 JSON 文件的精确路径

| Grok 输出 | 落到这里 |
|---|---|
| `[FILE: story.json]` | `projects/<project_id>/imports/story.json` |
| `[FILE: characters.json]` | `projects/<project_id>/imports/characters.json` |
| `[FILE: scenes.json]` | `projects/<project_id>/imports/scenes.json` |
| `[FILE: shots.json]` | `projects/<project_id>/imports/shots.json` |

(对白/台词已合并进 shots.json 字段里 — 没有单独的 dialogues.json)

参考图:
- `imports/references/<character_id>/hero.jpg` — 每个角色一张 hero 参考图
- `imports/references/<character_id>/face.png` — 可选,仅脸部特写
- `imports/references/<character_id>/costume_*.png` — 可选,特定服装

**两种目录约定**(都支持,Grok 看用户实际放哪里就输出对应路径):

A. 目录名 = character_id(推荐):
```
imports/references/lin_xi/hero.jpg    ← character_id: "lin_xi"
imports/references/lao_seng/hero.jpg ← character_id: "lao_seng"
```

B. 数字/通用目录(用户已用 `1/`, `2/` 等):
```
imports/references/1/hero.jpg  ← character_id: "young_woman"
imports/references/2/hero.jpg  ← character_id: "young_man"
```

**关键**:`validate-imports` 会检查 `reference_image` 指向的文件**真实存在**。如果指向不存在路径,会报 `MISSING_REFERENCE_IMAGE` ERROR,build 直接拒绝。所以**先 `ls imports/references/` 看实际布局**,再让 Grok 输出。

## `<project_id>` 怎么定

`<project_id>` 是个 slug,跟 `story.json` 里的 `story_id` 一致。

例: `story.json` 里 `story_id: "chang_an_xiyang_gu"`,则项目目录是 `projects/chang_an_xiyang_gu/`,命令是:

```bash
video-director validate-imports chang_an_xiyang_gu
```

**第一次使用前需要创建项目目录**:

```bash
# 如果项目目录还不存在,先 init
video-director init chang_an_xiyang_gu

# 然后把 Grok 输出放到 imports/
mkdir -p projects/chang_an_xiyang_gu/imports/references
# ... 把 JSON 文件 cp 进去 ...
```

## 校验流程

```bash
# 第 1 步: 校验 imports/*.json 是否符合 schema + 引用一致性
video-director validate-imports chang_an_xiyang_gu

# 输出示例(成功):
# [ok] story.json: schema valid, 1/1 fields present
# [ok] characters.json: 7 characters, all IDs valid
# [ok] scenes.json: 6 scenes, all character references resolved
# [ok] shots.json: 87 shots, all scene/character refs resolved
# [ok] chain integrity: shot links form valid DAG
# [ok] ALL CHECKS PASSED

# 输出示例(失败):
# [ERROR] shots.json: BROKEN_CHAIN: scene_001_shot_003.previous_shot=scene_001_shot_002 但 scene_001_shot_002.next_shot != scene_001_shot_003
# [ERROR] characters.json: MISSING_REFERENCE: shot 087 references character 'old_monk_v2' which does not exist
# [FAIL] 2 errors found, fix them in imports/ and re-run

# 第 2 步: 把校验通过的 imports/ 转换成 framework 的 yaml
video-director build chang_an_xiyang_gu

# 第 3 步: 交叉验证(framework 内置的 validate)
video-director validate chang_an_xiyang_gu

# 第 4 步: 跑生成(可选先 mock 后 comfyui)
video-director generate chang_an_xiyang_gu --backend mock   # 不耗 GPU, 验证流程
video-director generate chang_an_xiyang_gu --backend comfyui # 真跑
```

## 防重复生成的关键约束(很重要)

`build` 命令**只读取 imports/,不会覆盖已经存在的 yaml**。如果你重跑 `build`:
- yaml 会被覆盖(这是预期行为,imports 是 source of truth)
- `output/clips/` 里已经生成的 mp4 **不会被删除**
- 但 **imports 里被删除的 shot 对应的 mp4 会被标记为 orphan**,下次 `assemble` 会被拒绝

所以:
- **删 shot 后必须删对应的 output/clips/<shot_id>.mp4**,否则 checker 会报警
- **不要手动复制 Grok 输出之外的 JSON**,每个项目 5 个 JSON 文件是上限

## 如果某个 JSON 缺失或损坏

| 情况 | 处理 |
|---|---|
| Grok 输出还是带了 dialogues.json | framework 仍会加载(向后兼容),但下次新项目应去掉它 |
| Grok 输出漏掉 shots.json | **不能继续**,这是核心,重跑 Grok |
| shots.json 有语法错误(逗号、引号) | `validate-imports` 会报 `INVALID_JSON: <line> <col>`, 修 Grok 输出 |
| 某个 shot 缺 prompt | `validate-imports` 会报 `EMPTY_PROMPT: <shot_id>`, 加 prompt |
| shot 包含对白但 action 里没有中文台词 | 报 `MISSING_DIALOGUE_TEXT: <shot_id>`, 修 Grok 输出 |

## 跑完视频后清理

```bash
# imports/ 永远不删(它是 source of truth, 可以重建 yaml)
# shots/, characters/, scenes/, story.yaml 是 build 出来的, 可以从 imports/ 重建
# output/clips/ 是真生成的视频, 不要轻易删
# state/ 是 framework 状态, 重跑会复用
```
