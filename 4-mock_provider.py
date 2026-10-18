#!/usr/bin/env python3
"""Mock OpenAI-compatible provider for offline testing of FreeRoute.
Usage: python3 mock_provider.py PORT MODE NAME
MODE: ok (always 200) | ratelimit (always 429) | flaky (429 once, then ok) | down (never answers)
"""
import json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port, mode, name = int(sys.argv[1]), sys.argv[2], sys.argv[3]
hits = {}

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _send(self, status, obj):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode() or "{}")
        hits[self.path] = hits.get(self.path, 0) + 1
        if mode == "ratelimit" or (mode == "flaky" and hits[self.path] == 1):
            self._send(429, {"error": {"message": f"{name}: rate limit exceeded", "type": "rate_limit"}})
            return
        self._send(200, {
            "id": "chatcmpl-mock", "object": "chat.completion", "created": 1,
            "model": body.get("model", "mock"),
            "choices": [{"index": 0, "message": {"role": "assistant",
                         "content": f"hello from {name} (model={body.get('model')})"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        })
    def log_message(self, *a): pass

ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
