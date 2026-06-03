#!/usr/bin/env python3
"""Pure static HTTP server for system-monitor dashboard (dev only).

Reads happen via fetch() directly against the data files in this directory.
There is intentionally NO PUT/POST here — uploads go through the GitHub
Contents API from index.html (so the upload hits the same git history as
everything else and the sync-machines workflow can pick it up). This server
is only for when you want to test the dashboard against local data without
going through GitHub Pages.

Usage:  python3 server.py
        → http://localhost:8765
"""

import http.server
import socketserver
from pathlib import Path

PORT = 8765
DIR = Path(__file__).parent.resolve()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIR), **kwargs)

    def end_headers(self):
        # No-cache so iterative development is sane; in production this is
        # served by GitHub Pages with its own caching.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"System Monitor Dashboard (local) → http://localhost:{PORT}")
        httpd.serve_forever()
