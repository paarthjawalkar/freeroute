# Contributing to FreeRoute

FreeRoute is a small personal project that is happy to get help. Issues and
pull requests are welcome.

## The one big rule: standard library only

The whole point of FreeRoute is that it runs anywhere Python 3.8+ runs with
zero `pip install`. So:

- No new dependencies. Not even small ones.
- The router stays a single file, `freeroute.py`.
- Keep it readable. A beginner should be able to read the whole thing.

If your idea needs a dependency, a build step, or a second service, it is
probably a different project — open an issue first and we can talk about it.

## How to propose something

1. **Open an issue first** for anything bigger than a typo. Describe the
   problem, not just the fix.
2. For bugs, include how to reproduce, your Python version, where it runs
   (Termux / Colab / VPS / ...), and the `[freeroute ...]` log lines.

## Testing your change

You do not need real API keys. `mock_provider.py` fakes providers offline:

```sh
python3 mock_provider.py 9001 ratelimit mock-a &
python3 mock_provider.py 9002 ok mock-b &
```

Point a test `keys.json` at them and check that failover, `/status` and the
usage counters behave the way your change intends. Please describe in your PR
what you tested and how.

## Never commit secrets

`keys.json` is gitignored on purpose. Never paste real API keys into code,
issues, or PRs — a key in a commit history is compromised even after you
delete it. PRs containing secrets will be closed, not merged.

## License

By contributing you agree your changes are released under the MIT license.
