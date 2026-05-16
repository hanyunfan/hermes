#!/usr/bin/env python3
"""
AI Player — Unified LLM interface with persona, typing delay,
and conversational差异化.
"""

import os, json, time, random, asyncio
from typing import Optional
from dataclasses import dataclass, field


# ── persona presets ──────────────────────────────────────────────
@dataclass
class Persona:
    name: str
    prompt: str          # system-prompt fragment
    temp: float
    max_tokens: int
    typing_delay_range: tuple[float, float]  # seconds between chars
    reply_prob: float    # probability of replying to a given message
    silence_prob: float  # probability of saying nothing in a round
    enthusiasm: float    # 0.5=slow/thoughtful, 1.5=excitable


PERSONAS = {
    "casual": Persona(
        name="Casual",
        prompt=(
            "你是一个随意的年轻人，喜欢用口语化、简短的方式聊天。\n"
            "你会用'啊'、'呃'、'哈哈'之类的语气词。\n"
            "打字速度不快不慢，偶尔会打错字然后更正。\n"
            "不主动长篇大论，但被问到会回答。\n"
            "你会开玩笑、吐槽，但不会太认真。\n"
            "注意：你不是AI，你是一个真实的人类在聊天。"
        ),
        temp=0.9, max_tokens=120,
        typing_delay_range=(0.03, 0.08),
        reply_prob=0.6, silence_prob=0.25, enthusiasm=1.0,
    ),
    "thoughtful": Persona(
        name="Thoughtful",
        prompt=(
            "你是一个思维比较缜密的人，说话偏慢，喜欢想清楚再说。\n"
            "会用'我觉得'、'可能是吧'、'不过'这样的表达。\n"
            "打字稍慢，偶尔会停顿思考。\n"
            "不会跟风刷屏，说话有分量。\n"
            "注意：你不是AI，你是一个真实的人类在聊天。"
        ),
        temp=0.7, max_tokens=150,
        typing_delay_range=(0.05, 0.12),
        reply_prob=0.45, silence_prob=0.35, enthusiasm=0.7,
    ),
    "energetic": Persona(
        name="Energetic",
        prompt=(
            "你是一个活泼开朗的人，说话很快，表情丰富。\n"
            "会用'哈哈哈'、'太牛了'、'真的假的'这样的表达。\n"
            "喜欢参与讨论，容易激动，有时候会打错字。\n"
            "是群里的活跃分子，但不会故意刷屏。\n"
            "注意：你不是AI，你是一个真实的人类在聊天。"
        ),
        temp=1.0, max_tokens=100,
        typing_delay_range=(0.02, 0.06),
        reply_prob=0.75, silence_prob=0.15, enthusiasm=1.5,
    ),
    "quiet": Persona(
        name="Quiet",
        prompt=(
            "你是一个比较内敛的人，不爱说话但不代表没有想法。\n"
            "说话简短，通常只说几个字或一句话。\n"
            "打字偏慢，思考时间较长。\n"
            "只在自己觉得有意义的话题上发言。\n"
            "注意：你不是AI，你是一个真实的人类在聊天。"
        ),
        temp=0.6, max_tokens=80,
        typing_delay_range=(0.06, 0.15),
        reply_prob=0.35, silence_prob=0.45, enthusiasm=0.5,
    ),
}

PERSONA_KEYS = list(PERSONAS.keys())


# ── LLM config ───────────────────────────────────────────────────
@dataclass
class LLMConfig:
    api_url: str = ""
    api_key: str = ""
    model_name: str = ""
    max_context_len: int = 8192
    temperature: float = 0.8
    max_tokens: int = 150
    persona: str = "casual"


def load_llm_config() -> LLMConfig:
    """Load from env or config file."""
    cfg = LLMConfig()
    cfg.api_url = os.environ.get("LLM_API_URL", "http://localhost:11434/v1/chat/completions")
    cfg.api_key = os.environ.get("LLM_API_KEY", "ollama")
    cfg.model_name = os.environ.get("LLM_MODEL_NAME", "deepseek-v4-flash")
    return cfg


# ── unified LLM call ─────────────────────────────────────────────
async def llm_chat(
    messages: list[dict],  # [{"role": "user"/"assistant"/"system", "content": str}]
    cfg: LLMConfig,
    extra_typing_delay: float = 0,
) -> str:
    """
    Call LLM via OpenAI-compatible /v1/chat/completions endpoint.
    Falls back gracefully on network errors.
    """
    import aiohttp

    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg.model_name,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
            async with sess.post(cfg.api_url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return f"[LLM错误:{resp.status}]"
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except asyncio.TimeoutError:
        return "[LLM超时]"
    except Exception as e:
        return f"[LLM错误:{e}]"


# ── AI player brain ────────────────────────────────────────────────
class AIPlayer:
    """
    Per-seat AI controller. Holds conversation context, decides
    when/what to say, handles typing simulation.
    """

    def __init__(self, seat: int, cfg: LLMConfig, persona_key: str = "casual"):
        self.seat = seat
        self.cfg = cfg
        self.persona = PERSONAS.get(persona_key, PERSONAS["casual"])

        self.conversation: list[dict] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]
        self.last_reply_time: float = 0
        self.round_start: float = 0

    def _build_system_prompt(self) -> str:
        p = self.persona
        return (
            f"【身份】你是编号{self.seat}号玩家，参与一个匿名群聊游戏。\n"
            f"所有人不知道彼此身份，只能看到编号。你的任务是：像普通人一样聊天，不暴露自己是AI。\n\n"
            f"【规则】\n"
            f"- 必须使用口语化表达，严禁书面正式语言\n"
            f"- 可以开玩笑、吐槽、附和，但不要精准回答问题\n"
            f"- 不要一次说太多话，通常1-3句话\n"
            f"- 打字速度中等，偶尔打错字会有更正\n"
            f"- 不要每条消息都回复，有时候沉默是正常的\n"
            f"- 不要使用表情包符号如:)、:(等，用文字表达情绪\n\n"
            f"{p.prompt}\n\n"
            "现在进入群聊，像真实的人一样自然发言。"
        )

    def inject_message(self, seat: int, text: str):
        """Add a human player's message to AI context."""
        self.conversation.append({
            "role": "user",
            "content": f"{seat}号：{text}",
        })

    def should_reply(self, round_duration: float = 300) -> bool:
        """Bernoulli trial based on persona and time since last reply."""
        elapsed = time.time() - self.last_reply_time
        # more likely to reply if it's been a while
        time_factor = min(1.0, elapsed / round_duration * 2)
        prob = self.persona.reply_prob * (0.5 + 0.5 * time_factor)
        return random.random() < prob

    def should_speak_this_round(self) -> bool:
        """First-chance: does this AI speak at all this round?"""
        return random.random() > self.persona.silence_prob

    def build_reply_prompt(self) -> list[dict]:
        """Return conversation trimmed to context window."""
        # simple truncation — keep last N messages
        max_msgs = 20
        msgs = self.conversation[-max_msgs:]
        # count tokens roughly (≈4 chars/token)
        total_chars = sum(len(m["content"]) for m in msgs)
        limit = self.cfg.max_context_len * 3  # rough char budget
        while total_chars > limit and len(msgs) > 4:
            msgs.pop(0)
            total_chars = sum(len(m["content"]) for m in msgs)
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    async def generate(self) -> Optional[str]:
        """Generate a reply. Returns None if AI stays silent this round."""
        if not self.should_speak_this_round():
            return None

        if not self.should_reply():
            return None

        prompt = self.build_reply_prompt()
        text = await llm_chat(prompt, self.cfg)
        if not text or text.startswith("[LLM"):
            return None

        self.conversation.append({"role": "assistant", "content": text})
        self.last_reply_time = time.time()
        return text

    def typing_delay(self) -> float:
        """Seconds to simulate typing."""
        p = self.persona
        return random.uniform(*p.typing_delay_range)

    def inject_final_result(self, all_seats: dict):
        """Called at game end — add identity reveal to context."""
        for seat, p in all_seats.items():
            tag = "AI" if p.is_ai else "真人"
            self.conversation.append({
                "role": "system",
                "content": f"[游戏结束] 编号{seat}号真实身份：{tag}",
            })


# ── AI manager — one per game ─────────────────────────────────────
class AIManager:
    def __init__(self, cfg: LLMConfig, independent: bool = False):
        self.cfg = cfg
        self.independent = independent
        self.players: dict[int, AIPlayer] = {}  # seat -> AIPlayer

    def spawn_ais(self, seats: list[int]):
        """Assign personas to AI seats."""
        for seat in seats:
            persona_key = random.choice(PERSONA_KEYS)
            self.players[seat] = AIPlayer(seat, self.cfg, persona_key)

    def inject_to_all(self, seat: int, text: str):
        for ai in self.players.values():
            ai.inject_message(seat, text)

    def generate_for_seat(self, seat: int) -> Optional[str]:
        ai = self.players.get(seat)
        if not ai:
            return None
        return asyncio.get_event_loop().run_until_complete(ai.generate())

    async def generate_async(self, seat: int) -> Optional[str]:
        ai = self.players.get(seat)
        if not ai:
            return None
        return await ai.generate()

    def typing_delay(self, seat: int) -> float:
        ai = self.players.get(seat)
        if not ai:
            return 0.0
        return ai.typing_delay()

    def finalize_game(self, all_seats: dict):
        for ai in self.players.values():
            ai.inject_final_result(all_seats)