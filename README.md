# Planning poker

A planning poker for a team: pick a nickname, create a room, share its link.

[![Tests unitaires](https://github.com/Y-Blues/planningpoker/raw/badges/coverage.svg)](https://github.com/Y-Blues/planningpoker/actions/workflows/ci.yml)

## What it does

- No account; a room is a link with a random id, and unknown rooms look the same as expired ones.
- Votes stay hidden until the host reveals them, then shows each card, average, min and max.
- Recap of finished tasks as an Epic > Story > Sub-task tree, with optional read-only Jira Cloud import.
- Live over WebSocket; French UI.
- A showcase of a small app built only from framework pieces.

## Quick start

```bash
./run.sh                                  # memory storage, HTTP_PORT=... to change the port
source scripts/env.sh && python -m unittest discover -s src/unittest/python
GH_TOKEN=... docker compose -f deploy/docker-compose.yml up -d --build
```

The framework's repositories are private: building needs them checked out beside this repo, or their release wheels (see `deploy/`).

## How it fits

App. Works with `ui_web` and `client` (the Pyodide page), `storage` (rooms), `remote` (live votes).

## Status

Version 0.1.0.

More: [docs/DETAILS.md](docs/DETAILS.md) (full reference).

## License

Apache-2.0.

---

*YCappuccino is a personal project, developed in my free time for my band Y.Blues, independently of any professional activity and of any employer.*
