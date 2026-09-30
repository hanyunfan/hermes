"""Story analysis: turn a :class:`Story` into a :class:`StoryBible`.

The first version is deterministic and rule-based: we don't call an LLM
because the framework must work offline / in CI. LLM-driven analysis can
slot in later behind the same interface.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from ..models import Story, StoryBible
from ..utils.logging import get_logger


_LOG = get_logger("video_director.story.analyzer")


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LOCATION_HINT = re.compile(
    r"\b(?:at|in|on|inside|outside|near|by|within)\s+([A-Z][\w' \-]{1,40})",
)


@dataclass
class StoryAnalyzer:
    """Compile a :class:`StoryBible` from a :class:`Story`."""

    min_acts: int = 3
    max_acts: int = 5

    def analyze(self, story: Story) -> StoryBible:
        if not story.script:
            _LOG.warning("story has no script sections; producing empty bible")
            return StoryBible(title=story.title, logline=story.story_summary)

        characters = self._extract_characters(story)
        locations = self._extract_locations(story)
        beats = self._extract_beats(story)
        acts = self._split_into_acts(beats)

        return StoryBible(
            title=story.title,
            logline=story.story_summary or self._summarise(story),
            acts=acts,
            themes=self._extract_themes(story),
            beats=beats,
            characters=characters,
            locations=locations,
        )

    # ---- extractors --------------------------------------------------

    def _extract_characters(self, story: Story) -> list[str]:
        """Union of declared section.characters + PROPER_NOUN mentions in body."""
        declared: list[str] = []
        seen: set[str] = set()
        for s in story.script:
            for ch in s.characters:
                if ch not in seen:
                    declared.append(ch)
                    seen.add(ch)
        # Add first-mention proper nouns (heuristic for unnamed scripts)
        proper_nouns: Counter[str] = Counter()
        for s in story.script:
            for match in re.finditer(r"\b([A-Z][a-z]{2,})\b", s.body):
                token = match.group(1)
                if token in {"The", "And", "But", "Then", "Now", "When", "While", "After", "Before"}:
                    continue
                proper_nouns[token] += 1
        for name, _ in proper_nouns.most_common(8):
            if name not in seen:
                declared.append(name)
                seen.add(name)
        return declared

    def _extract_locations(self, story: Story) -> list[str]:
        locs: list[str] = []
        seen: set[str] = set()
        for s in story.script:
            candidates: list[str] = []
            if s.location:
                candidates.append(s.location)
            for m in _LOCATION_HINT.finditer(s.body):
                candidates.append(m.group(1))
            for c in candidates:
                c = c.strip()
                if c and c not in seen:
                    seen.add(c)
                    locs.append(c)
        return locs

    def _extract_beats(self, story: Story) -> list[str]:
        beats: list[str] = []
        for s in story.script:
            text = s.body or s.summary
            if not text:
                continue
            for sentence in _SENTENCE_END.split(text):
                sentence = sentence.strip()
                if sentence:
                    beats.append(sentence)
        return beats

    def _split_into_acts(self, beats: Iterable[str]) -> list[str]:
        beats_list = list(beats)
        if not beats_list:
            return []
        n = len(beats_list)
        if n <= 1:
            return [b for b in beats_list]
        # Aim for min_acts..max_acts; pick the smallest that leaves >=2 beats/act.
        chosen = max(self.min_acts, 1)
        for cand in range(self.min_acts, self.max_acts + 1):
            if n // cand >= 2:
                chosen = cand
        size = max(1, n // chosen)
        acts = []
        for i in range(chosen):
            chunk = beats_list[i * size : (i + 1) * size]
            if chunk:
                acts.append(" | ".join(chunk))
        return acts

    def _extract_themes(self, story: Story) -> list[str]:
        if story.genre:
            return [story.genre]
        return []

    def _summarise(self, story: Story) -> str:
        body = story.full_text.strip()
        if not body:
            return ""
        # First sentence, capped at 240 chars.
        first = _SENTENCE_END.split(body)[0]
        return first[:240].strip()