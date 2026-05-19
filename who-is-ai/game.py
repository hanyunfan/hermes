#!/usr/bin/env python3
"""Game logic — room management, chat, voting, win/loss conditions."""

import json, uuid, time, random, math
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class GamePhase(Enum):
    WAITING = "waiting"          # waiting for players
    CHATTING = "chatting"         # active chat round
    VOTING = "voting"             # voting in progress
    ELIMINATING = "eliminating"  # eliminating player
    ENDED = "ended"              # game over


@dataclass
class Player:
    seat: int           # 1-9
    is_ai: bool = False
    is_alive: bool = True
    voted_for: Optional[int] = None
    ws_id: Optional[str] = None  # WebSocket client id


@dataclass
class RoundRecord:
    round_num: int
    phase: str
    messages: list = field(default_factory=list)
    votes: dict = field(default_factory=dict)
    eliminated: Optional[int] = None


class Game:
    CHAT_DURATIONS = [300, 480, 600]  # 5/8/10 min in seconds

    def __init__(self, room_id: str,
                 total_seats: int,
                 ai_count: int,
                 host_ws_id: str,
                 chat_duration: int = 480,
                 is_public: bool = True,
                 password: str = "",
                 spectator_on: bool = True,
                 god_view: bool = False,
                 ai_independent: bool = False,
                 max_spectators: int = 50):
        if not (1 <= total_seats <= 9):
            raise ValueError("total_seats must be 1-9")
        if not (1 <= ai_count < total_seats):
            raise ValueError("ai_count must be 1 to total_seats-1")

        self.room_id = room_id
        self.total_seats = total_seats
        self.ai_count = ai_count
        self.host_ws_id = host_ws_id
        self.chat_duration = chat_duration
        self.is_public = is_public
        self.password = password
        self.spectator_on = spectator_on
        self.god_view = god_view
        self.ai_independent = ai_independent
        self.max_spectators = max_spectators

        self.seats: dict[int, Player] = {}   # seat -> Player
        self.phase = GamePhase.WAITING
        self.round_num = 0
        self.created_at = time.time()
        self.phase_start: float = 0

        self.chat_log: list[dict] = []       # {"seat": int, "text": str, "ts": float}
        self.round_records: list[RoundRecord] = []
        self.spectators: set[str] = set()    # ws_ids

        # pending AI generation tasks
        self._pending_ai_tasks: dict[int, str] = {}  # seat -> message text

    # ── seat helpers ────────────────────────────────────────────────
    def available_seat(self) -> Optional[int]:
        for i in range(1, self.total_seats + 1):
            if i not in self.seats:
                return i
        return None

    def add_player(self, seat: int, ws_id: str) -> Player:
        p = Player(seat=seat, ws_id=ws_id)
        self.seats[seat] = p
        return p

    def add_ai(self, seat: int) -> Player:
        p = Player(seat=seat, ws_id=None, is_ai=True)
        self.seats[seat] = p
        return p

    def seat_player(self, ws_id: str) -> Optional[int]:
        """Assign a human player to the next available seat. Returns seat number or None if full."""
        # If ws_id already has a seat, return it
        for seat, p in self.seats.items():
            if p.ws_id == ws_id:
                return seat
        seat = self.available_seat()
        if seat is None:
            return None
        self.add_player(seat, ws_id)
        return seat

    def fill_ai_slots(self):
        """Fill remaining seats with AI players up to ai_count."""
        ai_seats = random.sample(
            [i for i in range(1, self.total_seats + 1) if i not in self.seats],
            k=min(self.ai_count, self.total_seats - len(self.seats))
        )
        for seat in ai_seats:
            self.add_ai(seat)

    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.seats.values() if p.is_alive]

    @property
    def alive_human_count(self) -> int:
        return sum(1 for p in self.alive_players if not p.is_ai)

    @property
    def alive_ai_count(self) -> int:
        return sum(1 for p in self.alive_players if p.is_ai)

    def is_full(self) -> bool:
        return len(self.seats) >= self.total_seats

    def ready_to_start(self) -> bool:
        human_count = sum(1 for p in self.seats.values() if not p.is_ai)
        return human_count >= (self.total_seats - self.ai_count) and self.is_full()

    # ── state transitions ───────────────────────────────────────────
    def start_game(self):
        self.phase = GamePhase.CHATTING
        self.round_num = 1
        self.phase_start = time.time()

    def lock_chat_start_vote(self):
        self.phase = GamePhase.VOTING
        self.phase_start = time.time()
        # clear previous votes
        for p in self.seats.values():
            p.voted_for = None

    def apply_vote(self, seat: int, vote_for: int) -> bool:
        """Returns True if voting is now complete."""
        voter = self.seats.get(seat)
        target = self.seats.get(vote_for)
        if not voter or not target or not voter.is_alive or not target.is_alive:
            return False
        if vote_for == seat:
            return False
        voter.voted_for = vote_for

        # check if all alive non-spectators have voted
        alive = self.alive_players
        if len(alive) > 0 and all(p.voted_for is not None for p in alive):
            self._resolve_vote()
            return True
        return False

    def _resolve_vote(self):
        votes: dict[int, int] = {}
        for p in self.alive_players:
            v = p.voted_for
            if v and v > 0:  # skip abstain (0) from timeout
                votes[v] = votes.get(v, 0) + 1

        if not votes:
            # Everyone abstained — random elimination among tied
            alive_seats = [s for s, p in self.seats.items() if p.is_alive]
            if alive_seats:
                eliminated_seat = random.choice(alive_seats)
                self._eliminate(eliminated_seat)
            return

        max_votes = max(votes.values())
        tied = [s for s, c in votes.items() if c == max_votes]

        # simple tie-break: lowest seat number eliminated (or random)
        eliminated_seat = tied[0] if len(tied) == 1 else random.choice(tied)
        self._eliminate(eliminated_seat)

    def force_resolve_vote(self):
        """Force-resolve after 60s timeout: mark unvoted connected players as abstain (0)."""
        for p in self.alive_players:
            if p.voted_for is None:
                p.voted_for = 0  # abstain
        self._resolve_vote()

    def _eliminate(self, seat: int):
        player = self.seats.get(seat)
        if not player:
            return
        player.is_alive = False

        self.phase = GamePhase.ELIMINATING
        self.phase_start = time.time()

        # record elimination
        rec = RoundRecord(round_num=self.round_num, phase="elimination", eliminated=seat)
        self.round_records.append(rec)

        # ── win/loss check ──────────────────────────────────────────
        winner = self._check_winner()
        if winner:
            self.phase = GamePhase.ENDED
            self._record_final(winner)
        else:
            # next round
            self.round_num += 1
            self.phase = GamePhase.CHATTING
            self.phase_start = time.time()

    def _check_winner(self) -> Optional[str]:
        """Returns 'human' or 'ai' or None."""
        alive = self.alive_players
        ai_alive = sum(1 for p in alive if p.is_ai)

        # Human wins if all AI eliminated
        if ai_alive == 0:
            return "human"
        # AI wins when alive < (total_seats + 1) / 2
        # e.g. 9 players → threshold = 5, AI wins at ≤ 4
        #      6 players → threshold = 3, AI wins at ≤ 2
        #      4 players → threshold = 2, AI wins at ≤ 1
        if len(alive) < (self.total_seats + 1) // 2:
            return "ai"
        return None

    def _record_final(self, winner: str):
        self.final_winner = winner

    # ── chat ────────────────────────────────────────────────────────
    def add_message(self, seat: int, text: str):
        self.chat_log.append({"seat": seat, "text": text, "ts": time.time()})

    # ── spectators ──────────────────────────────────────────────────
    def add_spectator(self, ws_id: str) -> bool:
        if len(self.spectators) >= self.max_spectators:
            return False
        self.spectators.add(ws_id)
        return True

    # ── serialization ──────────────────────────────────────────────
    def public_state(self, viewer_ws_id: str) -> dict:
        alive = self.alive_players
        players_out = []
        for i in range(1, self.total_seats + 1):
            p = self.seats.get(i)
            if p:
                info = {
                    "seat": i,
                    "is_alive": p.is_alive,
                    "is_you": p.ws_id == viewer_ws_id,
                    "is_host": self.host_ws_id == p.ws_id,
                }
                if self.god_view and self.host_ws_id == viewer_ws_id:
                    info["is_ai"] = p.is_ai
                players_out.append(info)

        return {
            "room_id": self.room_id,
            "total_seats": self.total_seats,
            "ai_count": self.ai_count,
            "phase": self.phase.value,
            "round_num": self.round_num,
            "chat_duration": self.chat_duration,
            "players": players_out,
            "spectator_count": len(self.spectators),
            "chat_log": self.chat_log[-50:],   # last 50 messages
            "chat_seconds_left": max(0, int(self.chat_duration - (time.time() - self.phase_start)))
                                 if self.phase == GamePhase.CHATTING else 0,
            "vote_seconds_left": max(0, int(60 - (time.time() - self.phase_start)))
                                 if self.phase == GamePhase.VOTING else 0,
            "voted_seats": [p.seat for p in self.alive_players if p.voted_for is not None]
                           if self.phase == GamePhase.VOTING else [],
        }

    def voting_state(self, viewer_ws_id: str) -> dict:
        """Full voting detail — only sent to voters, not spectators."""
        state = self.public_state(viewer_ws_id)
        if self.phase == GamePhase.VOTING:
            # who has voted already
            voted = [p.seat for p in self.alive_players if p.voted_for is not None]
            state["voted_seats"] = voted
        return state


# ── room manager ─────────────────────────────────────────────────
class RoomManager:
    def __init__(self):
        self.rooms: dict[str, Game] = {}

    def create(self, host_ws_id: str,
               total_seats: int,
               ai_count: int,
               chat_duration: int = 480,
               is_public: bool = True,
               password: str = "",
               spectator_on: bool = True,
               god_view: bool = False,
               ai_independent: bool = False,
               max_spectators: int = 50) -> Game:
        room_id = str(uuid.uuid4())[:6].upper()
        while room_id in self.rooms:
            room_id = str(uuid.uuid4())[:6].upper()
        game = Game(
            room_id=room_id,
            total_seats=total_seats,
            ai_count=ai_count,
            host_ws_id=host_ws_id,
            chat_duration=chat_duration,
            is_public=is_public, password=password,
            spectator_on=spectator_on, god_view=god_view,
            ai_independent=ai_independent, max_spectators=max_spectators,
        )
        self.rooms[room_id] = game
        return game

    def get(self, room_id: str) -> Optional[Game]:
        return self.rooms.get(room_id.upper())

    def delete(self, room_id: str):
        self.rooms.pop(room_id.upper(), None)


# singleton
rooms = RoomManager()