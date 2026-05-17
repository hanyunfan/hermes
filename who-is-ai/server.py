#!/usr/bin/env python3
"""
Who-is-AI server — Flask + gevent-websocket (correct masking)
Routes:
  GET  /             → index.html
  WS   /ws           → WebSocket handler
"""

import os, json, time, asyncio, threading, random
from flask import Flask, send_from_directory, request, jsonify
from geventwebsocket import WebSocketApplication, Resource
from geventwebsocket.server import WebSocketServer
import logging

from game import Game, GameMode, GamePhase, rooms, Player
from ai_player import AIManager, load_llm_config

# ── app setup ─────────────────────────────────────────────────────
app = Flask(__name__)
app.logger.setLevel(logging.WARNING)  # quiet Flask

llm_cfg = load_llm_config()

# ws_id → {game, player_seat, is_spectator, is_host}
conn_state: dict[str, dict] = {}

# ws_id → ws object
connected_ws: dict[str, object] = {}

# ── helpers ──────────────────────────────────────────────────────
def broadcast(room_id: str, msg: dict, exclude: str = None):
    """Broadcast JSON to all WS connections in a room."""
    data = json.dumps(msg)
    for wid, ws in list(connected_ws.items()):
        if wid == exclude:
            continue
        state = conn_state.get(wid, {})
        g = state.get("game")
        if g and g.room_id == room_id:
            try:
                ws.send(data)
            except Exception:
                pass


def send_to(ws_id: str, msg: dict):
    ws = connected_ws.get(ws_id)
    if ws:
        try:
            ws.send(json.dumps(msg))
        except Exception:
            pass


# ── background round timer ─────────────────────────────────────────
async def chat_timer(game: Game, ai_mgr: AIManager):
    """Wait for chat_duration, then auto-start voting."""
    await asyncio.sleep(game.chat_duration)
    if game.phase != GamePhase.CHATTING:
        return

    await generate_ai_round(game, ai_mgr)

    game.lock_chat_start_vote()
    broadcast(game.room_id, {
        "type": "phase_change",
        "phase": "voting",
        "message": "聊天结束，开始投票",
    })
    t = threading.Thread(target=run_vote_timer, args=(game, ai_mgr), daemon=True)
    vote_timer_threads[game.room_id] = t
    t.start()


async def generate_ai_round(game: Game, ai_mgr: AIManager):
    """Each AI decides whether to speak this round."""
    for seat, ai in ai_mgr.players.items():
        p = game.seats.get(seat)
        if not p or not p.is_alive:
            continue
        if not ai.should_speak_this_round():
            continue
        text = await ai.generate()
        if text:
            delay = ai.typing_delay() + random.uniform(0.5, 2.0)
            broadcast(game.room_id, {"type": "typing_start", "seat": seat})
            await asyncio.sleep(delay)
            game.add_message(seat, text)
            broadcast(game.room_id, {
                "type": "chat",
                "seat": seat,
                "text": text,
                "is_ai": True,
            })
            broadcast(game.room_id, {"type": "typing_end", "seat": seat})


def run_chat_timer(game: Game, ai_mgr: AIManager):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(chat_timer(game, ai_mgr))
    loop.close()


async def vote_timer_task(game: Game, ai_mgr: AIManager):
    """Hard 60-second vote timeout."""
    await asyncio.sleep(60)
    if game.phase != GamePhase.VOTING:
        return
    game.force_resolve_vote()

    eliminated_seat = next(
        (s for s, p in game.seats.items()
         if not p.is_alive and
         any(r.eliminated == s for r in game.round_records)),
        None
    )
    broadcast(game.room_id, {
        "type": "elimination",
        "seat": eliminated_seat,
        "message": f"{eliminated_seat}号已被淘汰",
    })

    if game.phase == GamePhase.ENDED:
        if ai_mgr:
            ai_mgr.finalize_game(game.seats)
        all_identities = {
            s: ("AI" if p.is_ai else "真人")
            for s, p in game.seats.items()
        }
        broadcast(game.room_id, {
            "type": "game_end",
            "winner": game.final_winner,
            "identities": all_identities,
            "chat_log": game.chat_log,
            "message": f"游戏结束，{'人类' if game.final_winner == 'human' else 'AI'}获胜！",
        })
    else:
        game.round_num += 1
        game.phase = GamePhase.CHATTING
        game.phase_start = time.time()
        for p in game.seats.values():
            p.voted_for = None
        broadcast(game.room_id, {
            "type": "phase_change",
            "phase": "chatting",
            "round": game.round_num,
            "message": f"第{game.round_num}轮开始，聊天进行中...",
        })
        t2 = threading.Thread(target=run_chat_timer, args=(game, ai_mgr), daemon=True)
        timer_threads[game.room_id] = t2
        t2.start()


def run_vote_timer(game: Game, ai_mgr: AIManager):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(vote_timer_task(game, ai_mgr))
    loop.close()


# ── AI game manager map ────────────────────────────────────────────
ai_managers: dict[str, AIManager] = {}
timer_threads: dict[str, threading.Thread] = {}
vote_timer_threads: dict[str, threading.Thread] = {}


# ── WebSocket Application ──────────────────────────────────────────
class GameApplication(WebSocketApplication):
    def on_open(self):
        ws_id = str(id(self.ws))
        conn_state[ws_id] = {"game": None, "player_seat": None, "is_spectator": False, "is_host": False}
        connected_ws[ws_id] = self.ws

    def on_message(self, message):
        if not message:
            return
        ws_id = str(id(self.ws))
        state = conn_state.get(ws_id, {})

        try:
            msg = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            self.ws.send(json.dumps({"type": "error", "reason": "invalid JSON"}))
            return

        msg_type = msg.get("type", "")

        # ── create_room ────────────────────────────────────────────
        if msg_type == "create_room":
            mode_str = msg.get("mode", "standard")
            mode = GameMode.STANDARD if mode_str == "standard" else GameMode.LIGHT
            chat_dur = int(msg.get("chat_duration", 480))
            is_public = bool(msg.get("is_public", True))
            password = msg.get("password", "")
            spectator_on = bool(msg.get("spectator_on", True))
            god_view = bool(msg.get("god_view", False))
            ai_independent = bool(msg.get("ai_independent", False))
            max_spec = int(msg.get("max_spectators", 50))

            game = rooms.create(
                mode=mode, host_ws_id=ws_id,
                chat_duration=chat_dur,
                is_public=is_public, password=password,
                spectator_on=spectator_on, god_view=god_view,
                ai_independent=ai_independent, max_spectators=max_spec,
            )
            state["game"] = game
            state["player_seat"] = None
            state["is_spectator"] = False
            state["is_host"] = True
            conn_state[ws_id] = state

            self.ws.send(json.dumps({
                "type": "room_created",
                "room_id": game.room_id,
                "mode": mode.value,
            }))

        # ── join_room ─────────────────────────────────────────────
        elif msg_type == "join_room":
            room_id = msg.get("room_id", "").strip().upper()
            password = msg.get("password", "")
            game = rooms.get(room_id)

            if not game:
                self.ws.send(json.dumps({"type": "error", "reason": "房间不存在"}))
                return
            if game.password and game.password != password:
                self.ws.send(json.dumps({"type": "error", "reason": "房间密码错误"}))
                return
            if game.phase not in (GamePhase.WAITING,):
                self.ws.send(json.dumps({"type": "error", "reason": "游戏已开始，无法加入"}))
                return

            existing_seat = None
            for seat, p in game.seats.items():
                if p.ws_id == ws_id:
                    existing_seat = seat
                    break

            if existing_seat:
                state["player_seat"] = existing_seat
                state["is_spectator"] = False
            else:
                seat = game.available_seat()
                if seat is None:
                    game.add_spectator(ws_id)
                    state["is_spectator"] = True
                    state["player_seat"] = None
                    self.ws.send(json.dumps({"type": "spectating", "room_id": room_id}))
                    self.ws.send(json.dumps({"type": "room_state", **game.public_state(ws_id)}))
                    conn_state[ws_id] = state
                    return

                game.add_player(seat, ws_id)
                state["player_seat"] = seat
                state["is_spectator"] = False

            state["game"] = game
            state["is_host"] = game.host_ws_id == ws_id
            conn_state[ws_id] = state

            self.ws.send(json.dumps({
                "type": "joined",
                "seat": state["player_seat"],
                "room_id": game.room_id,
            }))
            self.ws.send(json.dumps({
                "type": "room_state",
                **game.public_state(ws_id),
            }))

            # ── Auto-start when minimum humans are reached ─────────────
            min_humans = Game.MODE_HUMANS[game.mode]
            current_humans = sum(1 for p in game.seats.values() if not p.is_ai)
            if current_humans >= min_humans:
                # Fill remaining seats with AI
                ai_seats = [i for i in range(1, Game.MODE_SEATS[game.mode] + 1)
                            if i not in game.seats]
                ai_mgr = AIManager(llm_cfg, independent=game.ai_independent)
                ai_mgr.spawn_ais(ai_seats)
                ai_managers[game.room_id] = ai_mgr
                for s in ai_seats:
                    game.add_ai(s)

                game.start_game()
                broadcast(game.room_id, {
                    "type": "game_start",
                    "message": f"游戏开始！共{Game.MODE_SEATS[game.mode]}人",
                })
                t = threading.Thread(target=run_chat_timer, args=(game, ai_mgr), daemon=True)
                timer_threads[game.room_id] = t
                t.start()

        # ── chat ──────────────────────────────────────────────────
        elif msg_type == "chat":
            game = state.get("game")
            if not game or game.phase != GamePhase.CHATTING:
                return
            seat = state.get("player_seat")
            if seat is None or state.get("is_spectator"):
                return
            player = game.seats.get(seat)
            if not player or not player.is_alive:
                return

            text = msg.get("text", "").strip()
            if not text or len(text) > 500:
                return

            game.add_message(seat, text)
            ai_mgr = ai_managers.get(game.room_id)
            if ai_mgr:
                ai_mgr.inject_to_all(seat, text)

            broadcast(game.room_id, {
                "type": "chat",
                "seat": seat,
                "text": text,
                "is_ai": False,
            }, exclude=ws_id)
            self.ws.send(json.dumps({"type": "chat_ack", "seat": seat}))

        # ── vote ───────────────────────────────────────────────────
        elif msg_type == "vote":
            game = state.get("game")
            if not game or game.phase != GamePhase.VOTING:
                return
            seat = state.get("player_seat")
            if seat is None or state.get("is_spectator"):
                return
            player = game.seats.get(seat)
            if not player or not player.is_alive or player.voted_for is not None:
                return

            vote_for = int(msg.get("vote_for", 0))
            complete = game.apply_vote(seat, vote_for)

            broadcast(game.room_id, {"type": "vote_cast", "seat": seat})

            if complete:
                game_obj = state["game"]
                ai_mgr = ai_managers.get(game_obj.room_id)

                # Find eliminated seat
                eliminated_seat = next(
                    (s for s, p in game_obj.seats.items()
                     if not p.is_alive and
                     any(r.eliminated == s for r in game_obj.round_records)),
                    None
                )
                broadcast(game_obj.room_id, {
                    "type": "elimination",
                    "seat": eliminated_seat,
                    "message": f"{eliminated_seat}号已被淘汰",
                })

                if game_obj.phase == GamePhase.ENDED:
                    if ai_mgr:
                        ai_mgr.finalize_game(game_obj.seats)
                    all_identities = {
                        s: ("AI" if p.is_ai else "真人")
                        for s, p in game_obj.seats.items()
                    }
                    broadcast(game_obj.room_id, {
                        "type": "game_end",
                        "winner": game_obj.final_winner,
                        "identities": all_identities,
                        "chat_log": game_obj.chat_log,
                        "message": f"游戏结束，{'人类' if game_obj.final_winner == 'human' else 'AI'}获胜！",
                    })
                else:
                    t = threading.Thread(target=run_chat_timer, args=(game_obj, ai_mgr), daemon=True)
                    timer_threads[game_obj.room_id] = t
                    t.start()
                    broadcast(game_obj.room_id, {
                        "type": "phase_change",
                        "phase": "chatting",
                        "round": game_obj.round_num,
                        "message": f"第{game_obj.round_num}轮开始，聊天进行中...",
                    })

        # ── get_state ─────────────────────────────────────────────
        elif msg_type == "get_state":
            game = state.get("game")
            if game:
                self.ws.send(json.dumps({"type": "room_state", **game.public_state(ws_id)}))

        # ── restart ───────────────────────────────────────────────
        elif msg_type == "restart":
            game = state.get("game")
            if not game or game.phase != GamePhase.ENDED or not state.get("is_host"):
                return
            # Stop existing timers
            timer_threads.pop(game.room_id, None)
            vote_timer_threads.pop(game.room_id, None)
            rooms.delete(game.room_id)
            ai_managers.pop(game.room_id, None)
            new_game = rooms.create(
                mode=game.mode, host_ws_id=ws_id,
                chat_duration=game.chat_duration,
                is_public=game.is_public, password=game.password,
                spectator_on=game.spectator_on, god_view=game.god_view,
                ai_independent=game.ai_independent, max_spectators=game.max_spectators,
            )
            state["game"] = new_game
            state["player_seat"] = None
            state["is_spectator"] = False
            state["is_host"] = True
            conn_state[ws_id] = state
            self.ws.send(json.dumps({
                "type": "room_created",
                "room_id": new_game.room_id,
                "mode": new_game.mode.value,
            }))

        # ── leave ──────────────────────────────────────────────────
        elif msg_type == "leave":
            self.ws.close()

    def on_close(self, reason=None):
        ws_id = str(id(self.ws))
        state = conn_state.pop(ws_id, {})
        connected_ws.pop(ws_id, None)
        game = state.get("game")
        if game:
            seat = state.get("player_seat")
            if state.get("is_spectator"):
                game.spectators.discard(ws_id)
            elif seat and seat in game.seats:
                game.seats[seat].ws_id = None  # keep seat, allow reconnect


# ── HTTP routes ────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/room/<room_id>")
def room_route(room_id):
    return send_from_directory(".", "index.html")


@app.route("/api/rooms")
def list_rooms():
    out = []
    for r in rooms.rooms.values():
        if r.phase == GamePhase.WAITING and r.is_public:
            out.append({
                "room_id": r.room_id,
                "mode": r.mode.value,
                "human_count": sum(1 for p in r.seats.values() if not p.is_ai),
                "total_seats": Game.MODE_SEATS[r.mode],
            })
    return jsonify(out)


@app.route("/style.css")
def style_css():
    return send_from_directory(".", "style.css")


# ── start ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8766))
    print(f"→ Who-is-AI server running on http://localhost:{port}")

    ws_app = Resource({
        "/ws": GameApplication,
        "/": app,
    })

    server = WebSocketServer(
        ("0.0.0.0", port),
        ws_app,
        debug=False,
    )
    server.serve_forever()