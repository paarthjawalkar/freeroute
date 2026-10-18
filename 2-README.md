# FreeRoute

**One OpenAI-compatible endpoint over everyone's free tiers, with automatic failover.**
Built by Paarth Jawalkar. Written from scratch (clean-room), Python standard library only.

You bring your own free API keys. FreeRoute forwards each chat request to the
highest-priority healthy provider, and when one rate-limits or dies, the next
one answers instead. Your app talks to `http://localhost:8080/v1` and never
cares which provider served it.

## Why not just use one provider?

Free tiers have small per-minute and per-day caps. One provider's cap stops
your app; three providers' caps, stacked behind a router, mostly don't.

## Run it (Android / Termux)

```sh
pkg install python
git clone <this repo> && cd freeroute   # or just copy the 3 files over
cp keys.example.json keys.json           # then paste your keys into keys.json
python freeroute.py                      # listening on http://localhost:8080
```

No pip install. No dependencies. Python 3.8+ is enough.

Test it:

```sh
curl http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"hi"}]}'
```

The response header `X-FreeRoute-Provider` tells you who actually answered.

## Run it (Colab)

Upload `freeroute.py` and your `keys.json`, then:

```python
!nohup python freeroute.py &        # listens on port 8080 inside the runtime
```

Call `http://localhost:8080/v1/...` from the notebook, or expose it with a
free tunnel (cloudflared / ngrok) if another device needs it.

## Run it (a free host)

Any always-on free Python host works (a free VPS tier, Railway/Fly trial,
a Raspberry Pi, an old phone running Termux with `termux-wake-lock`).
It is a single file with no build step.

## Get free keys (no card needed, as of Oct 2026)

| Provider | Where | Free tier |
|---|---|---|
| Google AI Studio (Gemini) | aistudio.google.com/apikey | gemini-3.5-flash etc., per-day caps |
| Groq | console.groq.com/keys | qwen3.8-27b, gpt-oss-120b, ~30 req/min |
| OpenRouter | openrouter.ai/settings/keys | models ending in `:free`, ~50 req/day |

## How failover works

- Request comes in with `"model": "auto"` → try providers in `priority` order.
- 429 (rate limit) → provider benched 65s, next provider tried instantly.
- 5xx / timeout → benched 30s.
- 401/403 (bad key) → benched 1 hour.
- All down → honest HTTP 502 saying what was tried and why it failed.
- Ask for a specific model (e.g. `"qwen/qwen3.8-27b"`) and only providers
  listing that model are tried.
- `/status` shows health, cooldowns and per-key usage counters
  (persisted to `state.json`).

## Honest limits

- No streaming yet (`stream:true` gets a 400). Non-streaming only.
- No admin dashboard, no auth on the router itself — it binds to
  127.0.0.1 by default (set `"host"` in keys.json to change). Do not
  expose it openly without putting auth in front of it.
- Chat completions only; no embeddings/images/audio yet.
- This aggregates *your own* free-tier keys for *your own* use.
  Reselling routed access or sharing one key across users breaks
  provider terms — don't.

## Files

- `freeroute.py` — the whole router (~250 lines, stdlib only)
- `keys.example.json` — provider config template
- `mock_provider.py` — fake providers for offline failover testing
