#!/usr/bin/env python3
"""
FreeRoute - a tiny self-hosted LLM router by Paarth Jawalkar.

One OpenAI-compatible endpoint that spreads requests across the free tiers
of several LLM providers, using YOUR OWN API keys, with automatic failover.

Clean-room implementation: written from scratch, standard library only,
so it runs anywhere Python 3 runs (Termux on Android, Colab, a free VPS).
No code taken from any other project.

How it works:
  - You list providers in keys.json (name, base_url, api_key, models, priority).
  - POST /v1/chat/completions with {"model": "auto", ...} and FreeRoute picks
    the highest-priority healthy provider and forwards the request.
  - If a provider rate-limits (429), errors (5xx), or times out, it goes on
    cooldown and the request automatically retries on the next provider.
  - Usage is counted per key so you can watch free-tier budgets.
"""

import json
import time
import threading
import urllib.request
import urllib.error
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG_PATH = "keys.json"
STATE_PATH = "state.json"

# How long a key is benched after each kind of failure (seconds)
COOLDOWN_RATE_LIMIT = 65      # 429: most free tiers reset per minute
COOLDOWN_SERVER_ERROR = 30    # 5xx / timeout / connection failure
COOLDOWN_AUTH_ERROR = 3600    # 401/403: key probably wrong, bench it long

REQUEST_TIMEOUT = 45          # seconds per upstream attempt


class Provider:
    def __init__(self, cfg):
        self.name = cfg["name"]
        self.base_url = cfg["base_url"].rstrip("/")
        self.api_key = cfg["api_key"]
        self.models = cfg.get("models", [])
        self.priority = cfg.get("priority", 99)
        self.cooldown_until = 0.0
        self.stats = {"ok": 0, "rate_limited": 0, "failed": 0, "served": 0}

    def healthy(self):
        return time.time() >= self.cooldown_until

    def bench(self, seconds, reason):
        self.cooldown_until = time.time() + seconds
        log(f"[{self.name}] benched {seconds}s ({reason})")


class Router:
    def __init__(self, providers):
        self.providers = sorted(providers, key=lambda p: p.priority)
        self.lock = threading.Lock()
        self.load_state()

    def candidates(self, model):
        """Providers that can serve this model, healthiest first."""
        if model in (None, "", "auto"):
            pool = self.providers
        else:
            pool = [p for p in self.providers if model in p.models]
        healthy = [p for p in pool if p.healthy()]
        return healthy if healthy else list(pool)  # if all benched, try anyway

    def chat(self, payload):
        """Try the request on each candidate until one answers. Returns
        (status, body_dict, provider_name)."""
        model = payload.get("model", "auto")
        if model not in (None, "", "auto") and not any(model in p.models for p in self.providers):
            return 400, {"error": {"message": f"Unknown model: {model}. "
                                   "No configured provider lists it.",
                                   "type": "freeroute_unknown_model"}}, None
        tried = []
        last_err = None
        for prov in self.candidates(model):
            tried.append(prov.name)
            out = self._attempt(prov, payload)
            if out["ok"]:
                with self.lock:
                    prov.stats["ok"] += 1
                    prov.stats["served"] += 1
                self.save_state()
                log(f"[{prov.name}] OK (tried: {' -> '.join(tried)})")
                return 200, out["body"], prov.name
            status = out["status"]
            last_err = out["error"]
            with self.lock:
                if status == 429:
                    prov.stats["rate_limited"] += 1
                else:
                    prov.stats["failed"] += 1
            if status == 429:
                prov.bench(COOLDOWN_RATE_LIMIT, "rate limited")
            elif status in (401, 403):
                prov.bench(COOLDOWN_AUTH_ERROR, "auth rejected")
            else:
                prov.bench(COOLDOWN_SERVER_ERROR, f"error {status}")
            log(f"[{prov.name}] failed ({status}), failing over")
            self.save_state()
        return 502, {
            "error": {
                "message": f"All providers failed. Tried: {', '.join(tried)}. "
                           f"Last error: {last_err}",
                "type": "freeroute_all_providers_down",
            }
        }, None

    def _attempt(self, prov, payload):
        body = dict(payload)
        if body.get("model") in (None, "", "auto"):
            if not prov.models:
                return {"ok": False, "status": 0, "error": "no models configured"}
            body["model"] = prov.models[0]
        req = urllib.request.Request(
            prov.base_url + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + prov.api_key,
                "User-Agent": "freeroute/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return {"ok": True, "status": resp.status,
                        "body": json.loads(resp.read().decode())}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return {"ok": False, "status": 0, "error": f"malformed upstream response: {e}"}
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()[:300]
            except Exception:
                detail = ""
            return {"ok": False, "status": e.code, "error": f"HTTP {e.code}: {detail}"}
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            return {"ok": False, "status": 0, "error": str(e)}

    # --- persistence: usage stats survive restarts ---
    def save_state(self):
        try:
            with self.lock:
                data = {p.name: p.stats for p in self.providers}
            with open(STATE_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def load_state(self):
        try:
            with open(STATE_PATH) as f:
                data = json.load(f)
            for p in self.providers:
                if p.name in data:
                    p.stats.update(data[p.name])
        except (OSError, ValueError):
            pass

    def status(self):
        return [{
            "name": p.name, "priority": p.priority, "models": p.models,
            "healthy": p.healthy(),
            "cooldown_remaining_s": max(0, int(p.cooldown_until - time.time())),
            "stats": p.stats,
        } for p in self.providers]


def log(msg):
    print(f"[freeroute {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def make_handler(router):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status, obj, extra_headers=None):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length", 0))
            if length > 1_000_000:
                raise ValueError("body too large")
            data = json.loads(self.rfile.read(length).decode())
            if not isinstance(data, dict):
                raise ValueError("body must be a JSON object")
            return data

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"status": "ok"})
            elif self.path == "/v1/models":
                models = []
                for p in router.providers:
                    for m in p.models:
                        models.append({"id": m, "object": "model", "owned_by": p.name})
                models.append({"id": "auto", "object": "model", "owned_by": "freeroute"})
                self._send(200, {"object": "list", "data": models})
            elif self.path == "/status":
                self._send(200, {"providers": router.status()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path.rstrip("/") == "/v1/chat/completions":
                try:
                    payload = self._body()
                except ValueError:
                    self._send(400, {"error": "invalid JSON body"})
                    return
                if payload.get("stream"):
                    self._send(400, {"error": "streaming not supported yet, set stream=false"})
                    return
                status, body, prov = router.chat(payload)
                headers = {"X-FreeRoute-Provider": prov} if prov else {}
                self._send(status, body, headers)
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, fmt, *args):  # silence default access log
            pass

    return Handler


def main():
    import os, sys
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except OSError:
        print(f"No {CONFIG_PATH} found. Copy keys.example.json to keys.json and add your keys.")
        sys.exit(1)
    providers = [Provider(p) for p in cfg["providers"]]
    if not providers:
        print("keys.json has no providers.")
        sys.exit(1)
    router = Router(providers)
    port = int(cfg.get("port", 8080))
    host = cfg.get("host", "127.0.0.1")  # localhost by default; set "host" to expose
    srv = ThreadingHTTPServer((host, port), make_handler(router))
    log(f"listening on http://{host}:{port} with {len(providers)} providers: "
        + ", ".join(p.name for p in router.providers))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")


if __name__ == "__main__":
    main()
