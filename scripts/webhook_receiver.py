#!/usr/bin/env python
"""Tiny test webhook receiver that verifies signatures.

Usage: WEBHOOK_SECRET=<secret from POST /v1/watches> python scripts/webhook_receiver.py 8081
For local testing set WEBHOOK_ALLOW_PRIVATE_DESTINATIONS=true on the API/poller so that
http://127.0.0.1:8081/ is accepted as a destination (never do this in production).
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from _bootstrap import ROOT  # noqa: F401 - ensures app is importable

from app.core.security import verify_webhook_signature

SECRET = os.environ.get("WEBHOOK_SECRET", "")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        ok = verify_webhook_signature(
            SECRET,
            self.headers.get("X-Signature-Timestamp", ""),
            self.headers.get("X-Signature", ""),
            body,
        )
        print(
            json.dumps(
                {
                    "signature_valid": ok,
                    "event_id": self.headers.get("X-Event-Id"),
                    "body": json.loads(body or b"{}"),
                }
            )
        )
        self.send_response(200 if ok else 400)
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"bad signature")

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    if not SECRET:
        print("Set WEBHOOK_SECRET", file=sys.stderr)
        sys.exit(2)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    print(f"listening on http://127.0.0.1:{port}/")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
