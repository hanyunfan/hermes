#!/usr/bin/env python3
"""Minimal WS server to test gevent-websocket frame parsing."""
from geventwebsocket import WebSocketApplication, Resource
from geventwebsocket.server import WebSocketServer
from flask import Flask
import json, logging

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)

class TestApp(WebSocketApplication):
    def on_open(self):
        print(f"[ON_OPEN] ws={type(self.ws).__name__}, environ={self.environ.get('PATH_INFO')}")

    def on_message(self, raw):
        print(f"[ON_MESSAGE] raw type={type(raw)}, len={len(raw) if raw else 0}")
        print(f"[ON_MESSAGE] raw bytes[:50]: {raw[:50] if raw else b''}")
        if raw:
            try:
                msg = json.loads(raw)
                print(f"[ON_MESSAGE] JSON OK: {msg.get('type')}")
                self.ws.send(json.dumps({"type": "ok", "received": msg}))
            except json.JSONDecodeError as e:
                print(f"[ON_MESSAGE] JSON error: {e}")
                self.ws.send(json.dumps({"type": "error", "reason": "invalid JSON"}))
        else:
            print("[ON_MESSAGE] empty raw")

    def on_close(self):
        print("[ON_CLOSE]")


ws_app = Resource({"/ws": TestApp, "/": app})
server = WebSocketServer(("0.0.0.0", 8766), ws_app, debug=False)
print("Test server starting on :8766")
server.serve_forever()