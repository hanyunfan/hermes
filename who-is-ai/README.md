# 人机鉴别群聊游戏 — Who is AI

匿名数字编号群聊，纯文字交流中依靠发言风格、逻辑判断谁是真人、谁是 AI。

## 玩法

- **4人轻量局**：3 真人 + 1 AI
- **9人标准局**：7 真人 + 2 AI

1. 创建房间，选择模式，等待真人凑齐
2. 系统自动填充 AI 开局，全程仅显示数字编号
3. 自由闲聊（房主设定时长：5/8/10 分钟）
4. 聊天结束 → 全员投票淘汰一人（禁止自投）
5. 重复聊天→投票循环，直至分出胜负

**胜负判定**
- 人类胜利：所有 AI 被淘汰
- AI 胜利：存活人数 ≤ 4 且仍有 AI 存活

## 本地运行

```bash
cd who-is-ai
pip install -r requirements.txt
python server.py
# 打开 http://localhost:8766
```

## 配置 AI 大模型

通过 `LLM_API_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME` 环境变量配置：

```bash
export LLM_API_URL=http://localhost:11434/v1/chat/completions
export LLM_API_KEY=ollama
export LLM_MODEL_NAME=deepseek-v4-flash
python server.py
```

或通过游戏内 `/api/config/ai` (POST) 动态调整。

## 技术栈

- **前端**：原生 HTML/CSS/JS，无框架依赖
- **后端**：Flask + gevent-websocket
- **AI**：OpenAI-compatible `/v1/chat/completions` 接口，适配 Ollama / vLLM / DeepSeek 等